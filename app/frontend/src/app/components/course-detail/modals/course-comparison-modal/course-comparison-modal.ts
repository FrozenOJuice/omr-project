import { AfterViewInit, ChangeDetectorRef, Component, ElementRef, EventEmitter, Injector, Input, OnDestroy, Output, ViewChild, afterNextRender, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Chart, type ChartConfiguration } from 'chart.js';
import { forkJoin, of } from 'rxjs';

import { ApiCourse, Course, CourseComparison, CourseStats, ExamComparisonMapping, ExamComparisonStats, formatAcademicPeriod } from '../../../../models/course.model';
import { CourseService } from '../../../../services/course.service';
import { UserService } from '../../../../services/user.service';
import { LoadingSpinner } from '../../../../sub-components/loading-spinner/loading-spinner';

function cssVar(name: string): string {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

@Component({
  selector: 'app-course-comparison-modal',
  imports: [FormsModule, LoadingSpinner],
  templateUrl: './course-comparison-modal.html',
  styleUrl: './course-comparison-modal.css',
})
export class CourseComparisonModal implements AfterViewInit, OnDestroy {
  @Input({ required: true }) courseId = '';
  @Input({ required: true }) courseOwnerId = '';
  @Input({ required: true }) course!: Course;
  @Input({ required: true }) courseStats!: CourseStats;
  @Output() closed = new EventEmitter<void>();
  @ViewChild('historicalAverageChart') historicalAverageCanvas?: ElementRef<HTMLCanvasElement>;

  private courseService = inject(CourseService);
  private userService = inject(UserService);
  private cdr = inject(ChangeDetectorRef);
  private injector = inject(Injector);
  private historicalAverageChart?: Chart<'line'>;

  comparisonCourseOptions: ApiCourse[] = [];
  savedCourseComparisons: CourseComparison[] = [];
  selectedComparisonCourseId = '';
  historicalComparisons: { comparison: CourseComparison; stats: CourseStats }[] = [];
  savingComparisonId: string | null = null;
  removingComparisonId: string | null = null;
  isLoadingComparison = true;
  comparisonError = '';

  readonly formatAcademicPeriod = formatAcademicPeriod;

  ngAfterViewInit(): void {
    this.loadComparisons();
  }

  ngOnDestroy(): void {
    this.historicalAverageChart?.destroy();
  }

  close(): void {
    this.closed.emit();
  }

  private loadComparisons(): void {
    forkJoin({
      courses: this.courseService.listCourses(true),
      comparisons: this.courseService.listCourseComparisons(this.courseId),
    }).subscribe({
      next: ({ courses, comparisons }) => {
        this.comparisonCourseOptions = courses
          .filter(course => course.id !== this.courseId
            && (this.userService.isAdmin() || course.created_by === this.courseOwnerId))
          .sort((a, b) => a.academic_year_start - b.academic_year_start
            || a.academic_term.name.localeCompare(b.academic_term.name));
        this.savedCourseComparisons = comparisons;
        const automaticallyIncluded = this.comparisonCourseOptions.filter(course =>
          course.archived_at !== null || comparisons.some(item => item.comparison_course.id === course.id));
        if (automaticallyIncluded.length === 0) {
          this.isLoadingComparison = false;
          this.cdr.markForCheck();
          return;
        }
        const requests = automaticallyIncluded.map(course => {
          const existing = comparisons.find(item => item.comparison_course.id === course.id);
          return existing ? of(existing) : this.courseService.createCourseComparison(this.courseId, course.id);
        });
        forkJoin(requests).subscribe({
          next: loadedComparisons => {
            forkJoin(loadedComparisons.map(comparison => forkJoin({
              comparison: of(comparison),
              stats: this.courseService.getCourseStats(comparison.comparison_course.id),
            }))).subscribe({
              next: historical => {
                this.savedCourseComparisons = loadedComparisons;
                this.historicalComparisons = historical.sort((a, b) =>
                  a.comparison.comparison_course.academic_year_start - b.comparison.comparison_course.academic_year_start);
                this.isLoadingComparison = false;
                this.cdr.markForCheck();
                afterNextRender(() => this.initHistoricalAverageChart(), { injector: this.injector });
              },
              error: () => this.failLoad(),
            });
          },
          error: () => this.failLoad(),
        });
      },
      error: () => this.failLoad(),
    });
  }

  availableAdditionalCourses(): ApiCourse[] {
    const displayedIds = new Set(this.historicalComparisons.map(item => item.comparison.comparison_course.id));
    return this.comparisonCourseOptions.filter(course => !displayedIds.has(course.id));
  }

  addSelectedComparisonCourse(): void {
    if (!this.selectedComparisonCourseId) return;
    this.isLoadingComparison = true;
    this.comparisonError = '';
    const existing = this.savedCourseComparisons.find(item => item.comparison_course.id === this.selectedComparisonCourseId);
    const request = existing ? of(existing) : this.courseService.createCourseComparison(this.courseId, this.selectedComparisonCourseId);
    request.subscribe({
      next: comparison => this.courseService.getCourseStats(comparison.comparison_course.id).subscribe({
        next: stats => {
          this.savedCourseComparisons = existing ? this.savedCourseComparisons : [...this.savedCourseComparisons, comparison];
          this.historicalComparisons = [...this.historicalComparisons, { comparison, stats }]
            .sort((a, b) => a.comparison.comparison_course.academic_year_start - b.comparison.comparison_course.academic_year_start);
          this.selectedComparisonCourseId = '';
          this.isLoadingComparison = false;
          this.cdr.markForCheck();
          afterNextRender(() => this.initHistoricalAverageChart(), { injector: this.injector });
        },
        error: () => this.failLoad(),
      }),
      error: () => this.failLoad(),
    });
  }

  saveMappings(comparison: CourseComparison): void {
    this.savingComparisonId = comparison.id;
    this.comparisonError = '';
    const mappings = comparison.mappings.map(({ base_exam_id, comparison_exam_id }) => ({ base_exam_id, comparison_exam_id }));
    this.courseService.updateCourseComparison(this.courseId, comparison.id, mappings).subscribe({
      next: updated => {
        const entry = this.historicalComparisons.find(item => item.comparison.id === updated.id);
        if (entry) entry.comparison = updated;
        this.savedCourseComparisons = this.savedCourseComparisons.map(item => item.id === updated.id ? updated : item);
        this.savingComparisonId = null;
        this.cdr.markForCheck();
      },
      error: () => {
        this.comparisonError = 'Unable to save exam mappings. Each historical exam can only be mapped once.';
        this.savingComparisonId = null;
        this.cdr.markForCheck();
      },
    });
  }

  removeComparison(comparison: CourseComparison): void {
    this.removingComparisonId = comparison.id;
    this.comparisonError = '';
    this.courseService.deleteCourseComparison(this.courseId, comparison.id).subscribe({
      next: () => {
        this.historicalComparisons = this.historicalComparisons.filter(item => item.comparison.id !== comparison.id);
        this.savedCourseComparisons = this.savedCourseComparisons.filter(item => item.id !== comparison.id);
        this.removingComparisonId = null;
        this.cdr.markForCheck();
        afterNextRender(() => this.initHistoricalAverageChart(), { injector: this.injector });
      },
      error: () => {
        this.comparisonError = 'Unable to remove this course comparison.';
        this.removingComparisonId = null;
        this.cdr.markForCheck();
      },
    });
  }

  formatStat(value: number | null | undefined, suffix = ''): string {
    return value === null || value === undefined ? '—' : `${value}${suffix}`;
  }

  baseStatsFor(mapping: ExamComparisonMapping): ExamComparisonStats | undefined {
    return this.courseStats.exams.find(exam => exam.exam_id === mapping.base_exam_id);
  }

  historicalStatsFor(mapping: ExamComparisonMapping, stats: CourseStats): ExamComparisonStats | undefined {
    return stats.exams.find(exam => exam.exam_id === mapping.comparison_exam_id);
  }

  private failLoad(): void {
    this.comparisonError = 'Unable to load historical course comparisons.';
    this.isLoadingComparison = false;
    this.cdr.markForCheck();
  }

  private initHistoricalAverageChart(): void {
    if (!this.historicalAverageCanvas) return;
    this.historicalAverageChart?.destroy();
    const historical = this.historicalComparisons.map(item => ({
      label: formatAcademicPeriod(
        item.comparison.comparison_course.academic_term,
        item.comparison.comparison_course.academic_year_start,
      ),
      mean: item.stats.mean_percentage,
    }));
    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels: [...historical.map(item => item.label), 'Current'],
        datasets: [{
          label: 'Course average',
          data: [...historical.map(item => item.mean), this.courseStats.mean_percentage],
          borderColor: cssVar('--highlight2'),
          backgroundColor: cssVar('--highlight2'),
          tension: 0.25,
          pointRadius: 5,
          pointHoverRadius: 7,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false } },
        scales: {
          x: { grid: { display: false }, ticks: { color: cssVar('--color-text') } },
          y: { beginAtZero: true, max: 100, ticks: { color: cssVar('--color-text'), callback: value => `${value}%` } },
        },
      },
    };
    this.historicalAverageChart = new Chart(this.historicalAverageCanvas.nativeElement, config);
  }
}
