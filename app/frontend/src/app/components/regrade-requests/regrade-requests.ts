import { ChangeDetectorRef, Component, DestroyRef, inject, OnDestroy, OnInit } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { DatePipe, NgClass } from '@angular/common';
import { ActivatedRoute } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ReviewRequestService } from '../../services/review-request.service';
import { ExamService } from '../../services/exam.service';
import {
  ApiReviewRequest,
  ApiReviewRequestBase,
  ApiStudentReviewRequest,
  ReviewRequestAuditEntry,
} from '../../models/regrade-requests.model';
import { ExamGrade, QuestionAnnotation } from '../../models/exam.model';
import { RegradeStatus, RegradeStatusClass, RegradeStatusLabel } from '../../enums/tags.enum';
import { LoadingSpinner } from '../../sub-components/loading-spinner/loading-spinner';
import { ExamPageViewer, PositionedBox, PositionedRegion } from '../../sub-components/exam-page-viewer/exam-page-viewer';
import { UserService } from '../../services/user.service';

// One flagged question's answer-key entry for the detail pane's "Rubric"
// panel: the correct answer(s) plus what the student actually answered, so
// staff/students can compare them without hunting through the scan.
interface AnswerKeyRow {
  questionNumber: string;
  correctAnswers: string[];
  studentAnswers: string[];
  correct: boolean;
  score: number;
  maxScore: number;
}

// Rows created from the same submission share a batch_id. A RequestGroup
// represents them as one request: the shared fields from the lowest
// question-numbered row, plus every row in the group and a combined label.
type RequestGroup<T extends ApiReviewRequestBase> = T & { requests: T[]; questionLabel: string };

function groupByBatch<T extends ApiReviewRequestBase>(requests: T[]): RequestGroup<T>[] {
  const groups = new Map<string, T[]>();
  for (const request of requests) {
    const key = request.batch_id ?? request.id;
    const existing = groups.get(key);
    if (existing) existing.push(request);
    else groups.set(key, [request]);
  }
  return [...groups.values()].map((rows) => {
    const sorted = [...rows].sort((a, b) => Number(a.question_number) - Number(b.question_number));
    const questionLabel =
      sorted.length === 1
        ? `Question ${sorted[0].question_number}`
        : `Questions ${sorted.map((r) => r.question_number).join(', ')}`;
    return { ...sorted[0], requests: sorted, questionLabel };
  });
}

@Component({
  selector: 'app-regrade-requests',
  imports: [NgClass, DatePipe, LoadingSpinner, ExamPageViewer],
  templateUrl: './regrade-requests.html',
  styleUrl: './regrade-requests.css',
})
export class RegradeRequests implements OnInit, OnDestroy {
  readonly RegradeStatus = RegradeStatus;
  readonly RegradeStatusClass = RegradeStatusClass;
  readonly RegradeStatusLabel = RegradeStatusLabel;

  private reviewRequestService = inject(ReviewRequestService);
  private examService = inject(ExamService);
  readonly userService = inject(UserService);
  private cdr = inject(ChangeDetectorRef);
  private route = inject(ActivatedRoute);
  private destroyRef = inject(DestroyRef);

  requests: ApiReviewRequest[] = [];
  myRequests: ApiStudentReviewRequest[] = [];
  searchQuery = '';
  selectedTerm = '';
  selectedStatus = '';
  selectedRequestId = '';
  selectedMyRequestId = '';
  isResolving = false;
  isLoading = true;
  loadError = false;
  isLoadingRequestHistory = false;
  requestHistoryError = '';
  requestHistory: ReviewRequestAuditEntry[] = [];
  // History is fetched eagerly alongside the preview whenever a request is
  // selected (see loadSelectedRequestHistory); this just gates whether the
  // popup showing it is open, so opening it never has to wait on a request.
  showHistoryModal = false;
  confirmingRequest: RequestGroup<ApiReviewRequest> | null = null;
  // First click on the confirm pop-up's Resolve button just arms it (and
  // flips its label to "Are you sure?"); the actual resolve only fires on
  // the second click, so a resolution can't be submitted by a single
  // misclick.
  resolveArmed = false;
  // Keyed by question_number -- each question in a batch gets its own
  // decision, not one decision shared across the whole batch.
  draftProposedScore: Record<string, number | null> = {};
  draftProposedCorrect: Record<string, boolean | null> = {};
  // Whatever a question's score was before it got marked Incorrect (and
  // forced to zero), so marking it Correct again restores that value
  // instead of leaving the zero behind.
  private draftProposedScoreBeforeIncorrect: Record<string, number | null> = {};
  draftInstructorResponse = '';
  resolveError = '';

  // Scanned-sheet + answer-key preview for whichever request is selected.
  // Reuses the same page-image/annotations calls as the exam results view
  // (AnnotatedExamView/StudentExamView), just aimed at the page holding the
  // flagged question(s) instead of starting at page 0.
  previewLoading = false;
  previewError = '';
  previewPage = 0;
  previewPageCount = 1;
  previewImageUrl: string | null = null;
  previewBoxes: PositionedBox[] = [];
  previewRegions: PositionedRegion[] = [];
  previewAnswerKey: AnswerKeyRow[] = [];
  // The flagged question(s) this request is actually about, so the preview
  // can outline them on the page instead of (or as well as) listing them in
  // the Answer Key panel.
  previewFlaggedQuestions: string[] = [];
  previewGradeId = '';
  // The full grade behind the currently selected request, so the "Current
  // Grade"/"Proposed Re-grade" boxes can show the real overall total instead
  // of a single question's own current_score/proposed_score.
  previewGrade: ExamGrade | null = null;
  private previewObjectUrl: string | null = null;

  ngOnInit(): void {
    this.loadRequests();
    if (!this.isStudentView()) {
      this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() =>
        this.selectRequestFromQueryParamsOrDefault(),
      );
    }
  }

  loadRequests(): void {
    if (this.isStudentView()) {
      this.loadMyRequests();
      return;
    }

    this.loadStaffRequests();
  }

  private loadStaffRequests(): void {
    this.isLoading = true;
    this.loadError = false;
    this.reviewRequestService.listReviewRequests().subscribe({
      next: (apiRequests) => {
        this.requests = apiRequests;
        this.selectRequestFromQueryParamsOrDefault();
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.requests = [];
        this.loadError = true;
        this.isLoading = false;
        this.cdr.markForCheck();
      },
    });
  }

  private loadMyRequests(): void {
    this.isLoading = true;
    this.loadError = false;
    this.reviewRequestService.listMyReviewRequests().subscribe({
      next: (apiRequests) => {
        this.myRequests = apiRequests;
        this.selectMyRequestFromDefault();
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.myRequests = [];
        this.loadError = true;
        this.isLoading = false;
        this.cdr.markForCheck();
      },
    });
  }

  dismissError(): void {
    this.loadError = false;
  }

  get terms(): string[] {
    return [...new Set(this.requests.map(r => r.term))].sort();
  }

  get hasActiveFilters(): boolean {
    if (this.isStudentView()) {
      return !!this.searchQuery.trim() || !!this.selectedStatus;
    }
    return !!this.searchQuery.trim() || !!this.selectedTerm || !!this.selectedStatus;
  }

  get filteredRequests(): ApiReviewRequest[] {
    const q = this.searchQuery.trim().toLowerCase();
    return this.requests.filter(r => {
      const matchesTerm = !this.selectedTerm || r.term === this.selectedTerm;
      const matchesStatus = !this.selectedStatus || r.status === this.selectedStatus;
      const matchesSearch = !q || r.student_name.toLowerCase().includes(q) || r.course_code.toLowerCase().includes(q);
      return matchesTerm && matchesStatus && matchesSearch;
    });
  }

  // A multi-question submission becomes several rows sharing a batch_id.
  // Grouping them here means staff see and act on one request card instead
  // of several nearly identical ones.
  get groupedRequests(): RequestGroup<ApiReviewRequest>[] {
    return groupByBatch(this.filteredRequests);
  }

  get selectedRequest(): RequestGroup<ApiReviewRequest> | null {
    return this.groupedRequests.find(g => g.id === this.selectedRequestId) ?? null;
  }

  get selectedMyRequest(): RequestGroup<ApiStudentReviewRequest> | null {
    return this.groupedMyRequests.find(g => g.id === this.selectedMyRequestId) ?? null;
  }

  get filteredMyRequests(): ApiStudentReviewRequest[] {
    const q = this.searchQuery.trim().toLowerCase();
    return this.myRequests.filter((request) => {
      const matchesStatus = !this.selectedStatus || request.status === this.selectedStatus;
      const comment = (request.student_comment ?? '').toLowerCase();
      const response = (request.instructor_response ?? '').toLowerCase();
      const matchesSearch = !q
        || request.question_number.toLowerCase().includes(q)
        || comment.includes(q)
        || response.includes(q);
      return matchesStatus && matchesSearch;
    });
  }

  get groupedMyRequests(): RequestGroup<ApiStudentReviewRequest>[] {
    return groupByBatch(this.filteredMyRequests);
  }

  isStudentView(): boolean {
    return this.userService.isStudent();
  }

  selectRequest(request: RequestGroup<ApiReviewRequest>): void {
    this.selectedRequestId = request.id;
    this.showHistoryModal = false;
    this.loadSelectedRequestHistory();
    this.loadPreview(request);
  }

  selectMyRequest(request: RequestGroup<ApiStudentReviewRequest>): void {
    this.selectedMyRequestId = request.id;
    this.showHistoryModal = false;
    this.loadSelectedRequestHistory();
    this.loadPreview(request);
  }

  private selectMyRequestFromDefault(): void {
    if (this.groupedMyRequests.length === 0) return;
    if (!this.selectedMyRequestId) {
      const request = this.groupedMyRequests[0];
      this.selectedMyRequestId = request.id;
      this.loadSelectedRequestHistory();
      this.loadPreview(request);
    }
  }

  // Deep-links from a notification (e.g. "/regrade?requestId=X") take priority
  // over the default "select the first request" behavior. The linked id can
  // be any row in a group, not just the one chosen to represent it, so this
  // matches against every row's id, not just the group's own id.
  private selectRequestFromQueryParamsOrDefault(): void {
    const groups = this.groupedRequests;
    if (groups.length === 0) return;

    const requestId = this.route.snapshot.queryParamMap.get('requestId');
    const requested = requestId ? groups.find(g => g.requests.some(r => r.id === requestId)) : null;
    if (requested) {
      if (this.selectedRequestId !== requested.id) {
        this.selectedRequestId = requested.id;
        this.loadSelectedRequestHistory();
        this.loadPreview(requested);
      }
    } else if (!this.selectedRequestId) {
      this.selectedRequestId = groups[0].id;
      this.loadSelectedRequestHistory();
      this.loadPreview(groups[0]);
    }
  }

  // Only reachable via the resolve confirm pop-up -- the instructor's note
  // and each question's decision are decided at the moment of resolution,
  // not edited freely beforehand, so this reads from the draft fields
  // rather than the (read-only, in the main pane) selectedRequest.
  private resolve(): void {
    const request = this.confirmingRequest;
    if (!request || this.isResolving) return;

    const proposedCorrect: Record<string, boolean> = {};
    const proposedScores: Record<string, number> = {};
    for (const row of request.requests) {
      const correct = this.draftProposedCorrect[row.question_number];
      if (correct != null) proposedCorrect[row.question_number] = correct;
      // Left out of the payload unless the staff member explicitly typed an
      // override -- when resolving, the backend defaults an omitted score to
      // that question's own full/zero credit, which a stale prefilled value
      // would silently clobber.
      const score = this.draftProposedScore[row.question_number];
      if (score != null) proposedScores[row.question_number] = score;
    }

    this.resolveError = '';
    this.isResolving = true;
    this.reviewRequestService.updateReviewRequest(request.id, {
      status: RegradeStatus.Resolved,
      instructor_response: this.draftInstructorResponse.trim(),
      proposed_correct: proposedCorrect,
      proposed_scores: proposedScores,
    }).subscribe({
      next: (updatedBatch) => {
        // The response only has the base fields (see updateReviewRequest's
        // return type), so merge rather than replace to keep each row's
        // student_name/course_code/term/exam_name/max_score.
        const updatedById = new Map(updatedBatch.map((row) => [row.id, row]));
        this.requests = this.requests.map((r) => {
          const updated = updatedById.get(r.id);
          return updated ? { ...r, ...updated } : r;
        });
        this.loadSelectedRequestHistory();
        // Resolving now updates the grade's question status, so the scan
        // overlay/rubric panel (sourced from the grade, not the review
        // request) needs a fresh fetch to reflect it.
        const group = this.groupedRequests.find((g) => g.id === request.id);
        if (group) this.loadPreview(group);
        this.isResolving = false;
        this.confirmingRequest = null;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.isResolving = false;
        this.resolveArmed = false;
        // Backend error responses are wrapped as {"error": {"code","message",...}}
        // (see app/backend/errors/handler.py's _error_response), not a bare
        // "detail" field.
        const message = err?.error?.error?.message;
        this.resolveError = typeof message === 'string' ? message : 'Unable to save this decision. Please try again.';
        this.cdr.markForCheck();
      },
    });
  }

  confirmResolve(): void {
    if (!this.selectedRequest) return;
    this.confirmingRequest = this.selectedRequest;
    const proposedScore: Record<string, number | null> = {};
    const proposedCorrect: Record<string, boolean | null> = {};
    for (const row of this.selectedRequest.requests) {
      // Pre-filled with whatever the student originally proposed for this
      // question, so staff see it and can adjust rather than retyping it --
      // left blank only when the student didn't propose a score, in which
      // case the backend defaults to full/zero credit driven by the
      // correct/incorrect decision below.
      proposedScore[row.question_number] = row.proposed_score ?? null;
      proposedCorrect[row.question_number] = row.proposed_correct ?? null;
    }
    this.draftProposedScore = proposedScore;
    this.draftProposedCorrect = proposedCorrect;
    this.draftProposedScoreBeforeIncorrect = {};
    this.draftInstructorResponse = this.selectedRequest.instructor_response ?? '';
    this.resolveError = '';
    this.resolveArmed = false;
  }

  cancelResolve(): void {
    this.confirmingRequest = null;
    this.draftProposedScore = {};
    this.draftProposedCorrect = {};
    this.draftProposedScoreBeforeIncorrect = {};
    this.draftInstructorResponse = '';
    this.resolveError = '';
    this.resolveArmed = false;
  }

  setDraftProposedCorrect(question: string, value: boolean): void {
    // Changing a decision after arming the Resolve button means the staff
    // member has to re-confirm against the new decision, not the one they
    // already clicked "are you sure?" on.
    this.resolveArmed = false;
    this.draftProposedCorrect = { ...this.draftProposedCorrect, [question]: value };
    if (!value) {
      // Incorrect always means zero credit -- the score field is disabled in
      // the template for this case, but reset the draft too so a value typed
      // in before switching to Incorrect doesn't linger and get submitted.
      // Remember it first so switching back to Correct can restore it.
      if (!(question in this.draftProposedScoreBeforeIncorrect)) {
        this.draftProposedScoreBeforeIncorrect[question] = this.draftProposedScore[question];
      }
      this.draftProposedScore = { ...this.draftProposedScore, [question]: 0 };
    } else if (question in this.draftProposedScoreBeforeIncorrect) {
      this.draftProposedScore = {
        ...this.draftProposedScore,
        [question]: this.draftProposedScoreBeforeIncorrect[question],
      };
      delete this.draftProposedScoreBeforeIncorrect[question];
    }
  }

  executeResolve(): void {
    const request = this.confirmingRequest;
    if (!request) return;
    if (!this.draftInstructorResponse.trim()) {
      this.resolveError = 'Enter feedback for the student before resolving.';
      return;
    }

    const undecided = request.requests.filter((row) => this.draftProposedCorrect[row.question_number] == null);
    if (undecided.length > 0) {
      const questions = undecided.map((row) => row.question_number).join(', ');
      this.resolveError = `Mark question(s) ${questions} correct or incorrect before resolving.`;
      return;
    }

    for (const row of request.requests) {
      // Optional: left blank, the backend defaults to that question's own
      // full/zero credit (driven by the correct/incorrect decision above).
      const score = this.draftProposedScore[row.question_number];
      if (score == null) continue;
      if (!Number.isFinite(score)) {
        this.resolveError = `Enter a valid proposed score for question ${row.question_number}.`;
        return;
      }
      const maxScore = this.questionMaxScore(row.question_number);
      if (score < 0 || (maxScore != null && score > maxScore)) {
        this.resolveError = `Proposed score for question ${row.question_number} must be between 0 and ${maxScore}.`;
        return;
      }
    }
    if (!this.resolveArmed) {
      this.resolveArmed = true;
      return;
    }

    // Left set until the request settles (resolve() clears it on both
    // success and failure) rather than cleared here, so a fresh submission
    // doesn't briefly flash the confirm dialog closed on a stale error.
    this.resolve();
  }

  updateDraftProposedScore(question: string, value: string): void {
    if (value.trim() === '') return;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    // Clamp here rather than only rejecting at submit time -- the number
    // input's min/max attrs only constrain the spinner arrows, not typed or
    // pasted values, so an unclamped score could otherwise sit in state as
    // e.g. 500 or -20 until the user notices the submit-time error.
    const max = this.questionMaxScore(question) ?? Infinity;
    this.draftProposedScore = { ...this.draftProposedScore, [question]: Math.min(max, Math.max(0, parsed)) };
    this.resolveArmed = false;
  }

  // The disputed question's own max_score, sourced from previewAnswerKey
  // (already computed per question for this exact group by loadPreview),
  // not the grade's overall max_score.
  questionMaxScore(question: string): number | null {
    return this.previewAnswerKey.find((row) => row.questionNumber === question)?.maxScore ?? null;
  }

  // Same source as questionMaxScore -- the disputed question's own answer-key
  // entry, so staff can see what should have been selected without leaving
  // the confirm pop-up to check the Answer Key panel.
  questionCorrectAnswer(question: string): string {
    const answers = this.previewAnswerKey.find((row) => row.questionNumber === question)?.correctAnswers ?? [];
    return answers.length ? answers.join(', ') : 'N/A';
  }

  // "Current Grade" -- the exam's real overall total, not a single
  // question's own current_score.
  currentGradeTotal(): number | null {
    return this.previewGrade?.total_score ?? null;
  }

  currentGradeMax(): number | null {
    return this.previewGrade?.max_score ?? null;
  }

  // "Proposed Re-grade" -- the exam's overall total assuming every question
  // in the group gets its own proposed_score (falling back to its
  // current_score when the group has no proposal for it yet).
  proposedGradeTotal(group: RequestGroup<ApiReviewRequestBase> | null): number | null {
    if (!this.previewGrade || !group) return null;
    const delta = group.requests.reduce((sum, row) => {
      const current = row.current_score ?? 0;
      const proposed = row.proposed_score ?? current;
      return sum + (proposed - current);
    }, 0);
    return Math.round((this.previewGrade.total_score + delta) * 100) / 100;
  }

  // Same as proposedGradeTotal, but for the confirm pop-up specifically:
  // reflects the draft Correct/Incorrect calls and typed score overrides
  // live, as staff make them, rather than the row's already-stored
  // proposed_score (which doesn't change until the request is actually
  // resolved).
  draftProposedGradeTotal(): number | null {
    const request = this.confirmingRequest;
    if (!this.previewGrade || !request) return null;
    const delta = request.requests.reduce((sum, row) => {
      const current = row.current_score ?? 0;
      const typedScore = this.draftProposedScore[row.question_number];
      let proposed: number;
      if (typedScore != null) {
        proposed = typedScore;
      } else if (this.draftProposedCorrect[row.question_number] === true) {
        proposed = this.questionMaxScore(row.question_number) ?? current;
      } else if (this.draftProposedCorrect[row.question_number] === false) {
        proposed = 0;
      } else {
        proposed = current;
      }
      return sum + (proposed - current);
    }, 0);
    return Math.round((this.previewGrade.total_score + delta) * 100) / 100;
  }

  updateDraftInstructorResponse(value: string): void {
    this.draftInstructorResponse = value;
    this.resolveArmed = false;
  }

  openHistoryModal(): void {
    this.showHistoryModal = true;
  }

  closeHistoryModal(): void {
    this.showHistoryModal = false;
  }

  historyEventLabel(entry: ReviewRequestAuditEntry): string {
    const actor = entry.actor_name ?? 'System';
    return entry.event_type === RegradeStatus.Resolved
      ? `Resolved by ${actor}`
      : `Rejected by ${actor}`;
  }

  historyChanges(entry: ReviewRequestAuditEntry): { label: string; before: string; after: string }[] {
    return Object.entries(entry.changes ?? {})
      .filter(([, value]) => typeof value === 'object' && value !== null && 'before' in value && 'after' in value)
      .map(([key, value]) => {
        const change = value as { before: unknown; after: unknown };
        return {
          label: this.humanizeChangeKey(key),
          before: this.formatChangeValue(change.before),
          after: this.formatChangeValue(change.after),
        };
      });
  }

  private loadSelectedRequestHistory(): void {
    const requestId = this.isStudentView() ? this.selectedMyRequestId : this.selectedRequestId;
    if (!requestId) {
      this.requestHistory = [];
      this.requestHistoryError = '';
      this.isLoadingRequestHistory = false;
      return;
    }

    this.isLoadingRequestHistory = true;
    this.requestHistoryError = '';
    this.reviewRequestService.getReviewRequestHistory(requestId).subscribe({
      next: (entries) => {
        this.requestHistory = entries;
        this.isLoadingRequestHistory = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.requestHistory = [];
        this.isLoadingRequestHistory = false;
        this.requestHistoryError = 'Unable to load decision history.';
        this.cdr.markForCheck();
      },
    });
  }

  private humanizeChangeKey(key: string): string {
    return key.replace(/_/g, ' ').replace(/\b\w/g, (char) => char.toUpperCase());
  }

  private formatChangeValue(value: unknown): string {
    if (value === null || value === undefined) return 'None';
    if (typeof value === 'string') return value.trim() === '' ? 'None' : value;
    return String(value);
  }

  ngOnDestroy(): void {
    this.revokePreviewUrl();
  }

  private loadPreview(group: RequestGroup<ApiReviewRequestBase>): void {
    this.previewGradeId = group.exam_grade_id;
    this.previewFlaggedQuestions = group.requests.map((r) => r.question_number);
    this.previewLoading = true;
    this.previewError = '';
    this.previewAnswerKey = [];
    this.previewBoxes = [];
    this.previewRegions = [];
    this.previewGrade = null;
    this.revokePreviewUrl();
    this.previewImageUrl = null;

    this.examService.getGrade(this.previewGradeId).subscribe({
      next: (grade) => {
        if (group.exam_grade_id !== this.previewGradeId) return;
        this.previewPageCount = grade.page_count ?? 1;
        this.previewAnswerKey = this.buildAnswerKey(grade, this.previewFlaggedQuestions);
        this.previewGrade = grade;
        this.cdr.markForCheck();
        this.findPreviewPage(this.previewGradeId, 0, this.previewPageCount, new Set(this.previewFlaggedQuestions));
      },
      error: () => {
        this.previewLoading = false;
        this.previewError = 'Unable to load the scanned sheet.';
        this.cdr.markForCheck();
      },
    });
  }

  private buildAnswerKey(grade: ExamGrade, questionNumbers: string[]): AnswerKeyRow[] {
    return questionNumbers.map((questionNumber) => {
      const result = grade.question_results[questionNumber];
      return {
        questionNumber,
        correctAnswers: result?.correct_answers ?? [],
        studentAnswers: result?.student_answers ?? [],
        correct: result?.correct ?? false,
        score: result?.score ?? 0,
        maxScore: result?.max_score ?? 0,
      };
    });
  }

  // There's no "which page is question N on" endpoint, so this walks pages
  // in order, checking each page's annotations for a flagged question,
  // until it finds one (or runs out of pages).
  private findPreviewPage(gradeId: string, pageIndex: number, pageCount: number, remaining: Set<string>): void {
    if (gradeId !== this.previewGradeId) return;
    if (pageIndex >= pageCount) {
      this.previewLoading = false;
      this.previewError = 'Unable to locate the flagged question on the scan.';
      this.cdr.markForCheck();
      return;
    }
    this.examService.getGradePageAnnotations(gradeId, pageIndex).subscribe({
      next: (annotations) => {
        if (gradeId !== this.previewGradeId) return;
        if (annotations.some((a) => remaining.has(a.question_id))) {
          this.loadPreviewPage(pageIndex);
        } else {
          this.findPreviewPage(gradeId, pageIndex + 1, pageCount, remaining);
        }
      },
      error: () => this.findPreviewPage(gradeId, pageIndex + 1, pageCount, remaining),
    });
  }

  loadPreviewPage(pageIndex: number): void {
    const gradeId = this.previewGradeId;
    this.previewLoading = true;
    this.previewError = '';
    forkJoin({
      annotations: this.examService.getGradePageAnnotations(gradeId, pageIndex),
      image: this.examService.getGradePageImage(gradeId, pageIndex),
    }).subscribe({
      next: ({ annotations, image }) => {
        if (gradeId !== this.previewGradeId) return;
        this.revokePreviewUrl();
        this.previewObjectUrl = URL.createObjectURL(image);
        this.previewImageUrl = this.previewObjectUrl;
        this.previewBoxes = annotations.flatMap((a) => this.toPreviewBoxes(a));
        this.previewRegions = annotations.map((a) => this.toPreviewRegion(a));
        this.previewPage = pageIndex;
        this.previewLoading = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.previewLoading = false;
        this.previewError = 'Unable to load this page of the exam.';
        this.cdr.markForCheck();
      },
    });
  }

  prevPreviewPage(): void {
    if (this.previewPage > 0) this.loadPreviewPage(this.previewPage - 1);
  }

  nextPreviewPage(): void {
    if (this.previewPage < this.previewPageCount - 1) this.loadPreviewPage(this.previewPage + 1);
  }

  private toPreviewBoxes(annotation: QuestionAnnotation): PositionedBox[] {
    const selectedClass = annotation.ambiguous
      ? 'status-ambiguous'
      : annotation.correct
        ? 'status-correct'
        : 'status-incorrect';
    return annotation.boxes.map((box) => ({
      key: `${annotation.question_id}-${box.label}`,
      questionId: annotation.question_id,
      x: box.x,
      y: box.y,
      width: box.width,
      height: box.height,
      statusClass: box.selected ? selectedClass : 'status-empty',
    }));
  }

  private toPreviewRegion(annotation: QuestionAnnotation): PositionedRegion {
    const answered = annotation.student_answers.length
      ? `answered ${annotation.student_answers.join(', ')}`
      : 'left blank';
    return {
      questionId: annotation.question_id,
      x: annotation.bounds.x,
      y: annotation.bounds.y,
      width: annotation.bounds.width,
      height: annotation.bounds.height,
      title: `Q${annotation.question_id}: ${answered}`,
    };
  }

  private revokePreviewUrl(): void {
    if (this.previewObjectUrl) {
      URL.revokeObjectURL(this.previewObjectUrl);
      this.previewObjectUrl = null;
    }
  }
}
