import { Component, DestroyRef, OnDestroy, OnInit, computed, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { forkJoin } from 'rxjs';
import { ExamService } from '../../services/exam.service';
import { CourseService } from '../../services/course.service';
import {
  ExamGrade,
  ExamStats,
  IdentityAnnotations,
  QuestionAnnotation,
  VersionAnnotation,
} from '../../models/exam.model';
import { Student, studentFullName } from '../../models/course.model';
import { QuestionList } from '../../sub-components/question-list/question-list';
import { GradeRoster, RosterSelection } from '../../sub-components/grade-roster/grade-roster';
import { GradeHistory } from '../../sub-components/grade-history/grade-history';
import { ExamPageViewer, PositionedBox, PositionedRegion } from '../../sub-components/exam-page-viewer/exam-page-viewer';
import { ExamResultLayout } from '../../sub-components/exam-result-layout/exam-result-layout';
import { ScoreSummary } from '../../sub-components/score-summary/score-summary';
import { IdentityCard } from '../../sub-components/identity-card/identity-card';
import { VersionLabel } from '../../sub-components/version-label/version-label';
import { ScoreBoxplot } from '../../sub-components/score-boxplot/score-boxplot';
import { UserService } from '../../services/user.service';
import { ExamStatsView } from '../exam-stats-view/exam-stats-view';

// Raw flag_reason codes from grading_service.py, mapped to something
// readable at a glance. Anything not listed falls back to a humanized
// version of the raw code.
const FLAG_REASON_LABELS: Record<string, string> = {
  version_not_detected: 'Version not detected',
  version_not_recognized: 'Unrecognized version',
  name_no_match: 'Unmatched name',
  name_ambiguous: 'Ambiguous name',
  student_id_no_match: 'Unmatched ID',
  student_id_ambiguous: 'Ambiguous ID',
  identity_mismatch: 'Name/ID mismatch',
  name_low_confidence: 'Low-confidence name',
  student_id_low_confidence: 'Low-confidence ID',
  duplicate_student_grade: 'Possible duplicate scan',
};

@Component({
  selector: 'app-annotated-exam-view',
  imports: [
    FormsModule,
    QuestionList,
    GradeRoster,
    GradeHistory,
    ExamPageViewer,
    ExamResultLayout,
    ScoreSummary,
    IdentityCard,
    VersionLabel,
    ScoreBoxplot,
    ExamStatsView,
  ],
  templateUrl: './annotated-exam-view.html',
  styleUrl: './annotated-exam-view.css',
})
export class AnnotatedExamView implements OnInit, OnDestroy {
  private examService = inject(ExamService);
  private courseService = inject(CourseService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);
  readonly userService = inject(UserService);

  gradeId = '';
  // Once known, this exam's roster/stats/grade list stay valid across a
  // student switch, so loadGrade only re-fetches them if it changes.
  examId: string | null = null;
  // So goBack() can return to the specific course instead of the courses list.
  private courseId: string | null = null;
  pageCount = signal(1);
  // Every grade for this exam, for the roster panel and the score box plot.
  // Persists across a student switch (see examId).
  examGrades = signal<ExamGrade[]>([]);
  classScorePercentages = computed(() =>
    this.examGrades()
      .filter((grade) => grade.max_score)
      .map((grade) => Math.round((grade.total_score / grade.max_score) * 1000) / 10),
  );
  // Passed in by whoever linked here, so the header has a name immediately;
  // superseded by studentLabel once the grade and roster have loaded.
  private initialStudentLabel = '';
  studentId = signal<string | null>(null);
  totalScore = signal<number | null>(null);
  maxScore = signal<number | null>(null);
  gradeStatus = signal('');
  flagReason = signal<string | null>(null);
  // Only populated for staff, since the stats endpoint is prof/admin-only.
  classStats = signal<ExamStats | null>(null);
  roster = signal<Student[]>([]);
  assigningStudentId = '';
  isSavingAssign = signal(false);
  assignError = signal('');
  assignSuccess = signal('');
  confirmingDuplicateAssignment = signal(false);
  // Conflicting grade ids reported by the backend's 409, used when the local
  // grade list is stale and the client-side pre-check found nothing.
  serverConflictGradeIds = signal<string[]>([]);
  showGradeHistory = signal(false);
  showExamStats = signal(false);

  studentLabel = computed(() => {
    const id = this.studentId();
    if (!id) return this.initialStudentLabel || 'Unmatched';
    const student = this.roster().find((s) => s.userId === id);
    return student ? studentFullName(student) : this.initialStudentLabel || id;
  });

  percentage = computed(() => {
    const total = this.totalScore();
    const max = this.maxScore();
    return total !== null && max ? Math.round((total / max) * 1000) / 10 : null;
  });
  classMeanPercent = computed(() => {
    const mean = this.classStats()?.mean_percentage;
    return mean != null ? Math.round(mean * 10) / 10 : null;
  });
  percentDiff = computed(() => {
    const mine = this.percentage();
    const mean = this.classMeanPercent();
    return mine !== null && mean !== null ? Math.round((mine - mean) * 10) / 10 : null;
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
  // page. Read-only: see VersionAnnotation for why.
  version = signal<VersionAnnotation | null>(null);
  imageUrl = signal<string | null>(null);
  loading = signal(true);
  error = signal('');
  // A question can have more than one selected bubble, so hovering it
  // highlights all of them together as one answer.
  hoveredQuestionId = signal<string | null>(null);
  // Set when a region is clicked, telling the question list to jump to and
  // expand that question's card.
  selectedQuestionId = signal<string | null>(null);

  private currentObjectUrl: string | null = null;

  ngOnInit(): void {
    // Drives both the initial load and every later student switch from the
    // roster panel: paramMap emits the current value immediately on
    // subscribe, so there's no separate snapshot read to keep in sync.
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      const gradeId = params.get('gradeId') ?? '';
      if (!gradeId) return;
      this.gradeId = gradeId;
      this.initialStudentLabel = this.route.snapshot.queryParamMap.get('student') ?? '';
      this.loadForGrade();
    });
  }

  private loadForGrade(): void {
    this.page.set(0);
    this.studentId.set(null);
    this.gradeStatus.set('');
    this.flagReason.set(null);
    this.gradeIdentity.set(null);
    this.assigningStudentId = '';
    this.assignError.set('');
    this.assignSuccess.set('');
    this.confirmingDuplicateAssignment.set(false);
    this.serverConflictGradeIds.set([]);

    this.loadGrade();
    this.loadPage(0);
    // The detected marks never change from an assign action, so unlike
    // loadGrade this only needs to run once per grade.
    this.examService.getGradeIdentity(this.gradeId).subscribe({
      next: (identity) => this.gradeIdentity.set(identity),
      error: () => {},
    });
  }

  private loadGrade(): void {
    this.examService.getGrade(this.gradeId).subscribe({
      next: (grade) => {
        this.pageCount.set(grade.page_count ?? 1);
        this.totalScore.set(grade.total_score);
        this.maxScore.set(grade.max_score);
        this.studentId.set(grade.student_id);
        this.gradeStatus.set(grade.status);
        this.flagReason.set(grade.flag_reason);
        if (grade.exam_id && grade.exam_id !== this.examId) {
          this.examId = grade.exam_id;
          this.loadExamContext(grade.exam_id);
        }
      },
    });
  }

  // Stays valid across a student switch within the same exam, so this only
  // re-runs when the exam itself changes.
  private loadExamContext(examId: string): void {
    this.examService.getExamStats(examId).subscribe({
      next: (stats) => this.classStats.set(stats),
      // Not staff, or nothing graded yet to compare against: the comparison
      // section just stays hidden.
      error: () => {},
    });
    this.examService.getExam(examId).subscribe({
      next: (exam) => {
        this.courseId = exam.course_id;
        this.courseService.getCourseStudents(exam.course_id).subscribe({
          // Only linked accounts have a userId to assign a grade to.
          next: (students) => this.roster.set(students.filter((s) => s.userId)),
          error: () => {},
        });
      },
      error: () => {},
    });
    this.examService.listExamGrades(examId).subscribe({
      next: (grades) => this.examGrades.set(grades),
      error: () => {},
    });
  }

  onSelectGrade(row: RosterSelection): void {
    if (row.gradeId === this.gradeId) return;
    this.router.navigate(['/grades', row.gradeId, 'annotations'], { queryParams: { student: row.name } });
  }

  ngOnDestroy(): void {
    this.revokeCurrentUrl();
  }

  // A fixed destination rather than browser history.back(): switching
  // students via the roster panel pushes a history entry per student, so
  // back() would walk through every student visited this session. Returns
  // to the specific course rather than the courses list, when that's known.
  // No examId query param: that deep link would immediately reopen a grade.
  goBack(): void {
    this.router.navigate(this.courseId ? ['/courses', this.courseId] : ['/courses']);
  }

  openStats(): void {
    if (!this.examId) return;
    this.showExamStats.set(true);
  }

  closeStats(): void {
    this.showExamStats.set(false);
  }

  prevPage(): void {
    if (this.page() > 0) this.loadPage(this.page() - 1);
  }

  nextPage(): void {
    if (this.page() < this.pageCount() - 1) this.loadPage(this.page() + 1);
  }

  // Re-fetches annotations for the page, plus the grade's own score/status
  // and its roster entry, since a correction can change any of them.
  onResolve(event: { questionId: string; answers: string[] }): void {
    this.examService
      .updateGrade(this.gradeId, { corrected_answers: { [event.questionId]: event.answers } })
      .subscribe({
        next: () => {
          this.refreshAnnotations();
          this.refreshGradeState();
        },
      });
  }

  flagReasonLabels(reason: string): string[] {
    return reason.split(',').map((code) => {
      const trimmed = code.trim();
      return FLAG_REASON_LABELS[trimmed] ?? trimmed.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
    });
  }

  rosterLabel(student: Student): string {
    const name = studentFullName(student);
    return student.studentNumber ? `${name} (${student.studentNumber})` : name;
  }

  get conflictingAssignments(): ExamGrade[] {
    if (!this.assigningStudentId) return [];
    return this.examGrades().filter(
      (grade) =>
        grade.id !== this.gradeId &&
        grade.student_id === this.assigningStudentId,
    );
  }

  get assigningStudentLabel(): string {
    const student = this.roster().find((item) => item.userId === this.assigningStudentId);
    return student ? studentFullName(student) : 'This student';
  }

  // How many existing results the target student already has, preferring the
  // locally known conflicts and falling back to the backend's 409 report when
  // this page's grade list didn't include them.
  get duplicateConflictCount(): number {
    const local = this.conflictingAssignments.length;
    return local > 0 ? local : this.serverConflictGradeIds().length;
  }

  onAssigningStudentChange(): void {
    this.assignError.set('');
    this.assignSuccess.set('');
    this.confirmingDuplicateAssignment.set(false);
    this.serverConflictGradeIds.set([]);
  }

  goToIdentityPage(): void {
    const index = this.gradeIdentity()?.page_index;
    if (index == null || index === this.page()) return;
    this.loadPage(index);
  }

  openGradeHistory(): void {
    this.showGradeHistory.set(true);
  }

  closeGradeHistory(): void {
    this.showGradeHistory.set(false);
  }

  assignStudent(): void {
    if (!this.assigningStudentId || this.isSavingAssign()) return;
    this.assignError.set('');
    this.assignSuccess.set('');
    if (this.conflictingAssignments.length > 0) {
      this.confirmingDuplicateAssignment.set(true);
      return;
    }
    this.executeStudentAssignment(false);
  }

  cancelDuplicateAssignment(): void {
    if (!this.isSavingAssign()) {
      this.confirmingDuplicateAssignment.set(false);
    }
  }

  confirmDuplicateAssignment(): void {
    if (!this.assigningStudentId || this.isSavingAssign()) return;
    this.executeStudentAssignment(true);
  }

  private executeStudentAssignment(confirmDuplicate: boolean): void {
    this.isSavingAssign.set(true);
    this.assignError.set('');
    this.examService
      .updateGrade(this.gradeId, {
        student_id: this.assigningStudentId,
        resolve_flag: true,
        confirm_duplicate_assignment: confirmDuplicate,
      })
      .subscribe({
        next: () => {
          this.assigningStudentId = '';
          this.isSavingAssign.set(false);
          this.confirmingDuplicateAssignment.set(false);
          this.assignSuccess.set('Student assigned and review flag resolved.');
          this.refreshGradeState();
        },
        error: (error) => {
          this.isSavingAssign.set(false);
          if (error?.status === 409 && error?.error?.error?.code === 'duplicate_student_assignment') {
            // The grade list may have changed after this page loaded. Surface
            // the same explicit warning the local pre-check would have shown,
            // using the ids the backend reported so the count is never "0".
            this.serverConflictGradeIds.set(error?.error?.error?.details?.grade_ids ?? []);
            this.confirmingDuplicateAssignment.set(true);
          } else {
            this.assignError.set('Unable to assign the student.');
          }
        },
      });
  }

  // Re-fetches this grade's own fields and its entry in the roster list,
  // since either can go stale after a correction or assignment.
  private refreshGradeState(): void {
    this.loadGrade();
    if (this.examId) {
      this.examService.listExamGrades(this.examId).subscribe({
        next: (grades) => this.examGrades.set(grades),
        error: () => {},
      });
    }
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
        this.applyAnnotations(annotations);
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

  private refreshAnnotations(): void {
    this.examService.getGradePageAnnotations(this.gradeId, this.page()).subscribe({
      next: (annotations) => this.applyAnnotations(annotations),
    });
  }

  private applyAnnotations(annotations: QuestionAnnotation[]): void {
    this.annotations.set(annotations);
    this.boxes.set(annotations.flatMap((annotation) => this.toBoxes(annotation)));
    this.regions.set(annotations.map((annotation) => this.toRegion(annotation)));
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
