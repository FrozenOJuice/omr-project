import { Component, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ExamService } from '../../services/exam.service';
import { ReviewRequestService } from '../../services/review-request.service';
import {
  ExamGrade,
  ExamScoreDistribution,
  IdentityAnnotations,
  QuestionAnnotation,
  VersionAnnotation,
} from '../../models/exam.model';
import { QuestionList } from '../../sub-components/question-list/question-list';
import { ExamPageViewer, PositionedBox, PositionedRegion } from '../../sub-components/exam-page-viewer/exam-page-viewer';
import { ExamResultLayout } from '../../sub-components/exam-result-layout/exam-result-layout';
import { ScoreSummary } from '../../sub-components/score-summary/score-summary';
import { IdentityCard } from '../../sub-components/identity-card/identity-card';
import { VersionLabel } from '../../sub-components/version-label/version-label';
import { FiveNumberSummary, ScoreBoxplot } from '../../sub-components/score-boxplot/score-boxplot';

// The student-facing counterpart to AnnotatedExamView: same per-page
// annotation overlay, question list, and read-only identity card, but no
// correct answers, no answer corrections, and no reassigning the scan to a
// different student (that stays professor-only in the UI and on the
// backend). Also adds the review-request form, which has no professor
// equivalent.
@Component({
  selector: 'app-student-exam-view',
  imports: [
    FormsModule,
    QuestionList,
    ExamPageViewer,
    ExamResultLayout,
    ScoreSummary,
    IdentityCard,
    VersionLabel,
    ScoreBoxplot,
  ],
  templateUrl: './student-exam-view.html',
  styleUrl: './student-exam-view.css',
})
export class StudentExamView implements OnInit, OnDestroy {
  private examService = inject(ExamService);
  private reviewRequestService = inject(ReviewRequestService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);

  gradeId = '';
  private courseId: string | null = null;
  grade = signal<ExamGrade | null>(null);
  loadingGrade = signal(true);
  // Only populated once results are released, since that's when the
  // backend allows a student to see the class's spread at all.
  scoreDistribution = signal<ExamScoreDistribution | null>(null);
  distributionSummary = computed<FiveNumberSummary | null>(() => {
    const d = this.scoreDistribution();
    if (
      !d ||
      d.count < 2 ||
      d.min_percentage == null ||
      d.q1_percentage == null ||
      d.median_percentage == null ||
      d.q3_percentage == null ||
      d.max_percentage == null
    ) {
      return null;
    }
    return { min: d.min_percentage, q1: d.q1_percentage, median: d.median_percentage, q3: d.q3_percentage, max: d.max_percentage };
  });

  pageCount = computed(() => this.grade()?.page_count ?? 1);
  percentage = computed(() => {
    const grade = this.grade();
    return grade && grade.max_score ? Math.round((grade.total_score / grade.max_score) * 1000) / 10 : null;
  });
  // Every question on the grade that wasn't already marked correct, not
  // just the current page, so the review request form can offer any of
  // them regardless of which page is open. A question already graded
  // correct has nothing to dispute.
  reviewQuestionNumbers = computed(() => {
    const results = this.grade()?.question_results ?? {};
    return Object.keys(results)
      .filter((q) => !results[q].correct)
      .sort((a, b) => Number(a) - Number(b));
  });

  page = signal(0);
  annotations = signal<QuestionAnnotation[]>([]);
  boxes = signal<PositionedBox[]>([]);
  regions = signal<PositionedRegion[]>([]);
  // Name/student-ID bubble fields on the current page, if any (typically a
  // dedicated back page rather than a question page).
  identity = signal<IdentityAnnotations | null>(null);
  // Not page-scoped, unlike identity above: fetched once so the identity
  // card can stay visible on every page and know which page to jump to.
  gradeIdentity = signal<IdentityAnnotations | null>(null);
  isOnIdentityPage = computed(() => this.page() === this.gradeIdentity()?.page_index);
  // The version-selector bubble, if this template has one and it's on this
  // page. Read-only for staff too: see VersionAnnotation for why.
  version = signal<VersionAnnotation | null>(null);
  imageUrl = signal<string | null>(null);
  loading = signal(true);
  error = signal('');
  hoveredQuestionId = signal<string | null>(null);
  selectedQuestionId = signal<string | null>(null);

  showReviewRequestForm = signal(false);
  // One submission can cover several questions, sharing the same
  // explanation, but each question gets its own proposed score.
  reviewRequestQuestions = signal<string[]>([]);
  reviewRequestExplanation = '';
  reviewRequestProposedScores = signal<Record<string, number | null>>({});
  isSubmittingReviewRequest = signal(false);
  reviewRequestError = signal('');
  reviewRequestSuccess = signal('');
  // Questions (on this grade) that already have a pending re-grade request,
  // so the form can block re-requesting them instead of only failing at
  // submit time -- there's no "current" request for staff to act on if two
  // pending rows both claim the same question.
  pendingReviewQuestions = signal<Set<string>>(new Set());

  private currentObjectUrl: string | null = null;

  ngOnInit(): void {
    this.gradeId = this.route.snapshot.paramMap.get('gradeId') ?? '';
    if (!this.gradeId) return;
    this.loadGrade();
    this.loadPage(0);
    this.loadPendingReviewQuestions();
    this.examService.getGradeIdentity(this.gradeId).subscribe({
      next: (identity) => this.gradeIdentity.set(identity),
      error: () => {},
    });
  }

  private loadPendingReviewQuestions(): void {
    // listMyReviewRequests() is scoped to the student, not this grade, so
    // filter down to the ones that actually apply here.
    this.reviewRequestService.listMyReviewRequests().subscribe({
      next: (requests) => {
        this.pendingReviewQuestions.set(
          new Set(
            requests
              .filter((r) => r.exam_grade_id === this.gradeId && r.status === 'pending')
              .map((r) => r.question_number),
          ),
        );
      },
      error: () => {},
    });
  }

  isQuestionPendingReview(question: string): boolean {
    return this.pendingReviewQuestions().has(question);
  }

  ngOnDestroy(): void {
    this.revokeCurrentUrl();
  }

  private loadGrade(): void {
    this.examService.getGrade(this.gradeId).subscribe({
      next: (grade) => {
        this.grade.set(grade);
        this.loadingGrade.set(false);
        if (grade.exam_id) {
          this.examService.getExam(grade.exam_id).subscribe({
            next: (exam) => (this.courseId = exam.course_id),
            error: () => {},
          });
          this.examService.getExamScoreDistribution(grade.exam_id).subscribe({
            next: (distribution) => this.scoreDistribution.set(distribution),
            error: () => {},
          });
        }
      },
      error: () => {
        this.error.set('Unable to load your results.');
        this.loadingGrade.set(false);
      },
    });
  }

  // A fixed destination rather than browser history.back(), same reasoning
  // as AnnotatedExamView.goBack().
  goBack(): void {
    this.router.navigate(this.courseId ? ['/courses', this.courseId] : ['/courses']);
  }

  prevPage(): void {
    if (this.page() > 0) this.loadPage(this.page() - 1);
  }

  nextPage(): void {
    if (this.page() < this.pageCount() - 1) this.loadPage(this.page() + 1);
  }

  goToIdentityPage(): void {
    const index = this.gradeIdentity()?.page_index;
    if (index == null || index === this.page()) return;
    this.loadPage(index);
  }

  openRequestReviewForm(): void {
    const questions = this.reviewQuestionNumbers();
    if (questions.length === 0) return;
    this.showReviewRequestForm.set(true);
    this.reviewRequestError.set('');
    this.reviewRequestSuccess.set('');
    this.reviewRequestQuestions.set(
      this.reviewRequestQuestions().filter(
        (q) => questions.includes(q) && !this.isQuestionPendingReview(q),
      ),
    );
    // Backfills a proposed score for any already-selected question that
    // doesn't have one yet (e.g. reopening the form), same default as
    // toggleReviewRequestQuestion.
    for (const question of this.reviewRequestQuestions()) {
      this.seedProposedScoreIfMissing(question);
    }
  }

  cancelReviewRequest(): void {
    this.showReviewRequestForm.set(false);
    this.reviewRequestError.set('');
  }

  isReviewRequestQuestionSelected(question: string): boolean {
    return this.reviewRequestQuestions().includes(question);
  }

  toggleReviewRequestQuestion(question: string): void {
    const current = this.reviewRequestQuestions();
    if (current.includes(question)) {
      this.reviewRequestQuestions.set(current.filter((q) => q !== question));
      return;
    }
    if (this.isQuestionPendingReview(question)) return;
    this.reviewRequestQuestions.set([...current, question]);
    this.seedProposedScoreIfMissing(question);
  }

  // Defaults a newly-checked question's proposed score to full credit,
  // rather than leaving it blank -- most students requesting a review on a
  // question think they deserve full marks unless they lower it themselves
  // for a partial-credit case.
  private seedProposedScoreIfMissing(question: string): void {
    if (this.reviewRequestProposedScores()[question] != null) return;
    const maxScore = this.grade()?.question_results?.[question]?.max_score ?? null;
    this.reviewRequestProposedScores.update((scores) => ({ ...scores, [question]: maxScore }));
  }

  updateReviewRequestProposedScore(question: string, value: string): void {
    if (value.trim() === '') return;
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return;
    const max = this.grade()?.question_results?.[question]?.max_score ?? Infinity;
    this.reviewRequestProposedScores.update((scores) => ({
      ...scores,
      [question]: Math.min(max, Math.max(0, parsed)),
    }));
  }

  reviewRequestMaxScoreFor(question: string): number | null {
    return this.grade()?.question_results?.[question]?.max_score ?? null;
  }

  submitReviewRequest(): void {
    if (this.isSubmittingReviewRequest()) return;
    const questions = this.reviewRequestQuestions();
    if (questions.length === 0) {
      this.reviewRequestError.set('Select at least one question to review.');
      return;
    }

    const explanation = this.reviewRequestExplanation.trim();
    if (!explanation) {
      this.reviewRequestError.set('Please explain why these questions should be reviewed.');
      return;
    }

    // Belt-and-suspenders: the checkboxes for these are already disabled,
    // but the pending set could have gone stale (e.g. staff resolved it just
    // before this submission started).
    const alreadyPending = questions.filter((q) => this.isQuestionPendingReview(q));
    if (alreadyPending.length > 0) {
      this.reviewRequestError.set(
        `Question(s) ${alreadyPending.join(', ')} already have a pending re-grade request.`,
      );
      return;
    }

    const scores = this.reviewRequestProposedScores();
    const proposedScores: Record<string, number> = {};
    for (const question of questions) {
      const score = scores[question];
      const maxScore = this.reviewRequestMaxScoreFor(question);
      if (score == null || !Number.isFinite(score)) {
        this.reviewRequestError.set(`Enter the score you think you should have gotten for question ${question}.`);
        return;
      }
      if (maxScore != null && (score < 0 || score > maxScore)) {
        this.reviewRequestError.set(`Proposed score for question ${question} must be between 0 and ${maxScore}.`);
        return;
      }
      proposedScores[question] = score;
    }

    this.isSubmittingReviewRequest.set(true);
    this.reviewRequestError.set('');
    this.reviewRequestSuccess.set('');
    this.reviewRequestService
      .createReviewRequest(this.gradeId, {
        question_numbers: questions,
        student_comment: explanation,
        proposed_scores: proposedScores,
      })
      .subscribe({
        next: () => {
          this.isSubmittingReviewRequest.set(false);
          this.showReviewRequestForm.set(false);
          this.reviewRequestSuccess.set('Review request submitted.');
          this.reviewRequestExplanation = '';
          this.reviewRequestProposedScores.set({});
          this.reviewRequestQuestions.set([]);
          this.pendingReviewQuestions.update(
            (pending) => new Set([...pending, ...questions]),
          );
        },
        error: (err) => {
          this.isSubmittingReviewRequest.set(false);
          // Backend error responses are wrapped as {"error": {"code","message",...}}
          // (see app/backend/errors/handler.py's _error_response), not a bare
          // "detail" field.
          const message = err?.error?.error?.message;
          this.reviewRequestError.set(
            typeof message === 'string' ? message : 'Unable to submit review request.',
          );
        },
      });
  }

  private loadPage(index: number): void {
    this.page.set(index);
    this.loading.set(true);
    this.error.set('');

    forkJoin({
      annotations: this.examService.getGradePageAnnotations(this.gradeId, index),
      identity: this.examService.getGradePageIdentity(this.gradeId, index),
      version: this.examService.getGradePageVersion(this.gradeId, index),
      image: this.examService.getGradePageImage(this.gradeId, index),
    }).subscribe({
      next: ({ annotations, identity, version, image }) => {
        this.revokeCurrentUrl();
        this.currentObjectUrl = URL.createObjectURL(image);
        this.imageUrl.set(this.currentObjectUrl);
        this.annotations.set(annotations);
        this.boxes.set(annotations.flatMap((annotation) => this.toBoxes(annotation)));
        this.regions.set(annotations.map((annotation) => this.toRegion(annotation)));
        this.identity.set(identity);
        this.version.set(version);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Unable to load this page of the exam.');
        this.loading.set(false);
      },
    });
  }

  private toBoxes(annotation: QuestionAnnotation): PositionedBox[] {
    // Selected bubbles are colored by correctness; unselected ones stay
    // neutral, since there's nothing right or wrong about a bubble nobody marked.
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

  private toRegion(annotation: QuestionAnnotation): PositionedRegion {
    return {
      questionId: annotation.question_id,
      x: annotation.bounds.x,
      y: annotation.bounds.y,
      width: annotation.bounds.width,
      height: annotation.bounds.height,
    };
  }

  private revokeCurrentUrl(): void {
    if (this.currentObjectUrl) {
      URL.revokeObjectURL(this.currentObjectUrl);
      this.currentObjectUrl = null;
    }
  }
}
