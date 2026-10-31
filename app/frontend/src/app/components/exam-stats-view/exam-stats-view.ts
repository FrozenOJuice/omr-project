import {
  ChangeDetectionStrategy,
  ChangeDetectorRef,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  inject,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import {
  ApiExam,
  ExamStats,
  ExamVersionStats,
  QuestionStats,
  ReleaseBlocker,
} from '../../models/exam.model';
import { ExamService } from '../../services/exam.service';

type StatsTab = 'stats' | 'questions';
type OverviewGraphMode = 'line' | 'bar';
type WarningLevel = 'warning' | 'danger';

@Component({
  selector: 'app-exam-stats-view',
  imports: [],
  templateUrl: './exam-stats-view.html',
  styleUrl: './exam-stats-view.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class ExamStatsView implements OnInit {
  private examService = inject(ExamService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private changeDetector = inject(ChangeDetectorRef);
  private questionWarningCache = new WeakMap<
    QuestionStats,
    { level: WarningLevel | null; message: string }
  >();

  @Input() examId = '';
  @Input() gradeId: string | null = null;
  @Input() releaseError = '';
  @Input() releaseBlockers: ReleaseBlocker[] = [];
  @Input() modal = false;
  @Output() close = new EventEmitter<void>();

  exam: ApiExam | null = null;
  resultsTab: StatsTab = 'stats';
  examStats: ExamStats | null = null;
  selectedQuestionVersion: string | null = null;
  versionComparisonInsights: string[] = [];
  overviewGraphMode: OverviewGraphMode = 'line';
  expandedQuestions = new Set<string>();
  isLoadingStats = true;
  statsError = '';

  ngOnInit(): void {
    this.examId ||= this.route.snapshot.paramMap.get('examId') ?? '';
    this.gradeId ??= this.route.snapshot.queryParamMap.get('gradeId');

    if (!this.examId) {
      this.isLoadingStats = false;
      this.statsError = 'Unable to identify this exam.';
      return;
    }

    this.examService.getExam(this.examId).subscribe({
      next: (exam) => {
        this.exam = exam;
        this.changeDetector.markForCheck();
      },
      error: () => {},
    });
    this.loadExamStats();
  }

  goBack(): void {
    if (this.modal) {
      this.close.emit();
      return;
    }
    if (this.gradeId) {
      this.router.navigate(['/grades', this.gradeId, 'annotations']);
      return;
    }
    this.router.navigate(this.exam?.course_id ? ['/courses', this.exam.course_id] : ['/courses']);
  }

  openCourseComparison(): void {
    if (!this.exam?.course_id) return;
    this.router.navigate(['/courses', this.exam.course_id], {
      queryParams: { action: 'comparison' },
    });
  }

  selectResultsTab(tab: StatsTab): void {
    this.resultsTab = tab;
  }

  selectQuestionVersion(version: string | null): void {
    this.selectedQuestionVersion = version;
    this.expandedQuestions = new Set<string>();
  }

  setOverviewGraphMode(mode: OverviewGraphMode): void {
    this.overviewGraphMode = mode;
  }

  isQuestionExpanded(questionNumber: string): boolean {
    return this.expandedQuestions.has(questionNumber);
  }

  toggleQuestion(questionNumber: string): void {
    const next = new Set(this.expandedQuestions);
    next.has(questionNumber) ? next.delete(questionNumber) : next.add(questionNumber);
    this.expandedQuestions = next;
  }

  setAllQuestionsExpanded(expanded: boolean): void {
    this.expandedQuestions = expanded
      ? new Set(
          this.selectedQuestionVersionStats?.question_stats.map(
            (question) => question.question_number,
          ),
        )
      : new Set<string>();
  }

  get allQuestionsExpanded(): boolean {
    const questions = this.selectedQuestionVersionStats?.question_stats ?? [];
    return (
      questions.length > 0 &&
      questions.every((question) => this.isQuestionExpanded(question.question_number))
    );
  }

  get selectedQuestionVersionStats(): ExamVersionStats | null {
    if (!this.examStats) return null;
    return (
      this.examStats.version_stats.find(
        (version) => version.exam_version === this.selectedQuestionVersion,
      ) ??
      this.examStats.version_stats[0] ??
      null
    );
  }

  formatStat(value: number | null | undefined, suffix = ''): string {
    return value === null || value === undefined ? 'N/A' : `${value}${suffix}`;
  }

  formatIndex(value: number | null | undefined): string {
    return value === null || value === undefined ? 'N/A' : value.toFixed(2);
  }

  formatExamVersion(version: string | null | undefined): string {
    return version ? `Version ${version}` : 'Single version';
  }

  questionWarningLevel(question: QuestionStats): WarningLevel | null {
    return this.getQuestionWarning(question).level;
  }

  questionWarningMessage(question: QuestionStats): string {
    return this.getQuestionWarning(question).message;
  }

  private getQuestionWarning(question: QuestionStats): {
    level: WarningLevel | null;
    message: string;
  } {
    const cached = this.questionWarningCache.get(question);
    if (cached) return cached;

    let warning: { level: WarningLevel | null; message: string };
    if (question.correct_percentage < 30 || (question.discrimination_index ?? 0) < 0) {
      warning = {
        level: 'danger',
        message:
          (question.discrimination_index ?? 0) < 0 ? 'Negative discrimination' : 'Very difficult',
      };
    } else if (
      question.correct_percentage < 50 ||
      question.correct_percentage > 90 ||
      (question.discrimination_index !== null && question.discrimination_index < 0.2) ||
      (question.distractor_efficiency !== null && question.distractor_efficiency < 0.5)
    ) {
      let message = 'Difficult question';
      if (question.correct_percentage > 90) message = 'Very easy';
      else if (question.discrimination_index !== null && question.discrimination_index < 0.2) {
        message = 'Low discrimination';
      } else if (question.distractor_efficiency !== null && question.distractor_efficiency < 0.5) {
        message = 'Weak distractors';
      }
      warning = { level: 'warning', message };
    } else {
      warning = { level: null, message: '' };
    }
    this.questionWarningCache.set(question, warning);
    return warning;
  }

  get distributionMaxCount(): number {
    return Math.max(1, ...(this.examStats?.score_distribution.map((bucket) => bucket.count) ?? []));
  }

  distributionX(index: number): number {
    const bucketCount = this.examStats?.score_distribution.length ?? 0;
    return bucketCount <= 1 ? 500 : 50 + (index * 900) / (bucketCount - 1);
  }

  distributionY(count: number): number {
    return 175 - (count / this.distributionMaxCount) * 135;
  }

  get distributionLinePath(): string {
    const buckets = this.examStats?.score_distribution ?? [];
    if (!buckets.length) return '';
    return buckets
      .map(
        (bucket, index) =>
          `${index === 0 ? 'M' : 'L'} ${this.distributionX(index)} ${this.distributionY(bucket.count)}`,
      )
      .join(' ');
  }

  private loadExamStats(): void {
    this.isLoadingStats = true;
    this.statsError = '';
    this.examService.getExamStats(this.examId).subscribe({
      next: (stats) => {
        this.examStats = stats;
        this.selectedQuestionVersion =
          stats.version_stats.find((version) => version.graded_count > 0)?.exam_version ??
          stats.version_stats[0]?.exam_version ??
          null;
        this.versionComparisonInsights = this.buildVersionComparisonInsights(stats.version_stats);
        this.isLoadingStats = false;
        this.changeDetector.markForCheck();
      },
      error: () => {
        this.statsError = 'Unable to load exam statistics.';
        this.isLoadingStats = false;
        this.changeDetector.markForCheck();
      },
    });
  }

  private buildVersionComparisonInsights(versions: ExamVersionStats[]): string[] {
    const comparable = versions.filter(
      (version) => version.graded_count > 0 && version.average_item_difficulty !== null,
    );
    if (comparable.length < 2) return [];

    const mostLowDiscrimination = comparable.reduce((current, version) =>
      version.low_discrimination_question_count > current.low_discrimination_question_count
        ? version
        : current,
    );
    const insights: string[] = [];
    if (mostLowDiscrimination.low_discrimination_question_count > 0) {
      insights.push(
        `${this.formatExamVersion(mostLowDiscrimination.exam_version)} has the most low-discrimination questions (${mostLowDiscrimination.low_discrimination_question_count}).`,
      );
    }
    return insights;
  }
}
