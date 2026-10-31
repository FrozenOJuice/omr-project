import { AfterViewInit, ChangeDetectionStrategy, Component, DestroyRef, ElementRef, HostListener, Injector, OnDestroy, OnInit, ViewChild, afterNextRender, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NgClass } from '@angular/common';
import { ActivatedRoute, ParamMap, Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { Chart, registerables, type ChartConfiguration } from 'chart.js';
import { Course, ApiCourse, CourseStats, apiCourseToCourse, Student } from '../../models/course.model';
import {
  ApiExam,
  Exam,
  apiExamToExam,
  DEFAULT_EXAM_DURATION_MINUTES,
  EXAM_DURATION_PRESETS,
  ExamGrade,
  ReleaseBlocker,
} from '../../models/exam.model';
import { ApiReviewRequest, ApiStudentReviewRequest } from '../../models/regrade-requests.model';
import { ExamStatus, ExamStatusClass, ReleaseStatus, ReleaseStatusClass, ReleaseStatusLabel } from '../../enums/tags.enum';
import { CourseService } from '../../services/course.service';
import { ExamService } from '../../services/exam.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { UserService } from '../../services/user.service';
import { ReviewRequestService } from '../../services/review-request.service';
import { NotificationService } from '../../services/notification.service';
import { ScanService } from '../../services/scan.service';
import { CreateCourse } from '../../sub-components/create-course/create-course';
import { CreateExam } from '../../sub-components/create-exam/create-exam';
import { StudentList } from '../../sub-components/student-list/student-list';
import { AddStudentsModal } from '../../sub-components/add-students-modal/add-students-modal';
import { ScanUploadModal } from '../../sub-components/scan-upload-modal/scan-upload-modal';
import { DashboardRegradeRequestsCard } from '../../sub-components/dashboard-regrade-requests-card/dashboard-regrade-requests-card';
import { CanvasGradeRelease } from '../../sub-components/canvas-grade-release/canvas-grade-release';
import { TemplateBuilder } from '../template-builder/template-builder';
import { AnswerKey } from '../answer-key/answer-key';
import { Scan, ScanJobStatus } from '../../models/scan.model';
import { ExamTemplateResponse } from '../../models/exam-template.model';
import { LoadingSpinner } from '../../sub-components/loading-spinner/loading-spinner';
import { CanvasGradeRelease as CanvasGradeReleaseStatus, CanvasRosterSync } from '../../models/canvas.model';
import { Subscription, catchError, forkJoin, interval, of, startWith, switchMap, takeWhile, timer } from 'rxjs';
import { CourseComparisonModal } from './modals/course-comparison-modal/course-comparison-modal';
import { RetentionPolicyModal } from './modals/retention-policy-modal/retention-policy-modal';
import { CourseHeader } from './sections/course-header/course-header';
import { ExamStatsView } from '../exam-stats-view/exam-stats-view';

Chart.register(...registerables);

// The backend only ever emits a notification for a scan/grading *failure* or
// a grade needing manual review -- an exam that finishes processing cleanly
// never generates one, so the notification stream (below) can't be relied on
// to catch that case. Poll exam statuses directly whenever one is still
// mid-processing, so a successful finish shows up without a manual reload.
const EXAM_STATUS_POLL_INTERVAL_MS = 2500;

function cssVar(name: string): string {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

@Component({
  selector: 'app-course-detail',
  imports: [
    NgClass, FormsModule,
    CreateCourse, CreateExam, StudentList, AddStudentsModal, ScanUploadModal,
    TemplateBuilder, AnswerKey, DashboardRegradeRequestsCard, LoadingSpinner,
    CanvasGradeRelease,
    CourseComparisonModal,
    RetentionPolicyModal,
    CourseHeader,
    ExamStatsView,
  ],
  templateUrl: './course-detail.html',
  styleUrl: './course-detail.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CourseDetail implements OnInit, AfterViewInit, OnDestroy {
  readonly ExamStatus = ExamStatus;
  readonly ExamStatusClass = ExamStatusClass;
  readonly ReleaseStatus = ReleaseStatus;
  readonly ReleaseStatusClass = ReleaseStatusClass;
  readonly ReleaseStatusLabel = ReleaseStatusLabel;

  private courseService = inject(CourseService);
  private examService = inject(ExamService);
  private scanService = inject(ScanService);
  private templateService = inject(ExamTemplateService);
  private reviewRequestService = inject(ReviewRequestService);
  private notificationService = inject(NotificationService);
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private injector = inject(Injector);
  private destroyRef = inject(DestroyRef);
  readonly userService = inject(UserService);

  readonly courseId = signal('');
  readonly courseOwnerId = signal('');
  private courseLoadRequest = 0;
  readonly course = signal<Course | null>(null);
  readonly isLoadingCourse = signal(true);
  readonly courseLoadError = signal('');

  // Course header (edit/delete course)
  readonly editingCourse = signal<Course | null>(null);
  readonly deletingCourse = signal<Course | null>(null);
  readonly isDeleting = signal(false);
  readonly courseActionError = signal('');
  readonly deleteRequiresArchive = signal(false);
  readonly isRestoringCourse = signal(false);
  readonly confirmingRestore = signal(false);

  // Exam CRUD / modals
  readonly examWizardStep = signal<0 | 1 | 2 | 3>(0);
  readonly examWizardExam = signal<Exam | null>(null);
  readonly examWizardMode = signal<'omr' | 'canvas'>('omr');
  readonly confirmingExamWizardExit = signal(false);
  readonly showAddExamMenu = signal(false);
  readonly deletingExam = signal<Exam | null>(null);
  readonly isDeletingExam = signal(false);
  readonly editingScheduleExam = signal<Exam | null>(null);
  readonly isSavingSchedule = signal(false);
  readonly scheduleError = signal('');
  readonly scheduleDurationPresets = EXAM_DURATION_PRESETS;
  scheduleDate = '';
  scheduleStartClock = '';
  scheduleDurationMinutes: number | null = DEFAULT_EXAM_DURATION_MINUTES;
  readonly confirmingReleaseExam = signal<Exam | null>(null);
  readonly viewingTemplates = signal(false);
  readonly viewingAnswerKeyExam = signal<Exam | null>(null);
  readonly uploadingScansForExam = signal<Exam | null>(null);
  // Live OMR job status for a batch currently being preprocessed, polled
  // directly by this component (see pollJobStatus below) so it keeps running
  // regardless of whether the upload modal that kicked it off is still open
  // -- the modal is a full-screen overlay that hides this page's own cards,
  // so tying the poll to the modal's lifecycle would mean it's torn down
  // before the user ever gets to see this card update. null when no upload
  // is actively processing, in which case the Grading Progress card falls
  // back to the scanned/total ratio below.
  readonly activeJobStatus = signal<ScanJobStatus | null>(null);
  // Which exam activeJobStatus belongs to, so the exam-list row for that
  // exam can show the same live sub-label as the dashboard card.
  readonly activeJobExamId = signal<string | null>(null);
  private jobStatusSub?: Subscription;
  readonly assigningTemplateExam = signal<Exam | null>(null);
  readonly canvasGradeExam = signal<Exam | null>(null);
  readonly templateOptions = signal<ExamTemplateResponse[]>([]);
  readonly selectedTemplateId = signal('');
  readonly isLoadingTemplateOptions = signal(false);
  readonly isAssigningTemplate = signal(false);
  readonly confirmingTemplateChange = signal(false);
  readonly templateAssignError = signal('');

  // Exam-wide stats (score distribution, per-question analysis, and
  // versions) are rendered by ExamStatsView; this just tracks which exam
  // (if any) is being shown in that modal.
  readonly viewingStatsExam = signal<Exam | null>(null);

  // Overflow menu ("...") on an exam row. It is rendered as a fixed overlay so
  // the exams list cannot clip it, then repositioned whenever any ancestor
  // scrolls so it still moves with its exam row.
  readonly openMenuExamId = signal<string | null>(null);
  readonly examMenuPosition = signal<{ top: number; right: number } | null>(null);
  private examMenuTrigger: HTMLElement | null = null;
  private readonly repositionExamMenuOnScroll = (): void => {
    this.repositionExamMenu();
  };

  readonly isReleasingExam = signal(false);
  readonly releaseError = signal('');
  readonly releaseNotice = signal('');
  readonly releaseBlockers = signal<ReleaseBlocker[]>([]);
  readonly isDownloadingExamPdf = signal(false);
  // Results-export state (UR2.29): both are tracked per exam id so exporting
  // one exam doesn't disable the download action on every other exam, and the
  // error renders inline under the row whose download failed.
  readonly exportingExamId = signal<string | null>(null);
  readonly exportErrorExamId = signal<string | null>(null);

  // Students section (inline, scroll target)
  readonly addingStudents = signal(false);

  // Dashboard charts, backed by real course data where it exists
  @ViewChild('jobProgressChart') jobProgressCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('gradeDistChart') gradeDistCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('regradeVolumeChart') regradeVolumeCanvas!: ElementRef<HTMLCanvasElement>;
  private jobProgressChart?: Chart<'doughnut'>;
  private gradeDistChart?: Chart<'bar'>;
  private regradeVolumeChart?: Chart<'bar'>;
  private darkModeObserver?: MutationObserver;

  // Grade Distribution: % of graded scans in this course landing in each bucket.
  readonly gradeDistributionLabels = ['<50', '50-60', '60-70', '70-80', '80-90', '90-100'];
  readonly gradeDistributionCounts = signal<number[]>([0, 0, 0, 0, 0, 0]);
  readonly gradedGradeCount = signal(0);
  readonly isLoadingGradeDistribution = signal(false);
  readonly courseStats = signal<CourseStats | null>(null);
  readonly courseStatsError = signal('');
  readonly showAllCourseStats = signal(false);
  readonly showingCourseComparison = signal(false);

  // Re-grade Volume: count of this course's review requests by weekday (Mon..Sun).
  readonly regradeVolumeLabels = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  readonly isLoadingRegradeVolume = signal(false);
  readonly regradeVolumeByDay = signal<number[]>([0, 0, 0, 0, 0, 0, 0]);

  readonly regradeRequests = signal<ApiReviewRequest[]>([]);

  readonly showCourseModal = computed(() => this.editingCourse() !== null);

  // Same ownership rule the backend enforces on the promote endpoint
  // (require_admin_or_prof + _get_mutable_course's owner-or-admin check).
  get isCourseOwner(): boolean {
    const uid = this.userService.currentUser()?.id;
    return this.userService.isAdmin() || (!!uid && this.courseOwnerId() === uid);
  }

  // Scans graded vs. total scans submitted across every exam in this course.
  readonly gradingProgress = computed(() => {
    const exams = this.course()?.exams ?? [];
    const scanned = exams.reduce((sum, e) => sum + e.scanned, 0);
    const total = exams.reduce((sum, e) => sum + e.total, 0);
    return { scanned, total, percent: total > 0 ? Math.round((scanned / total) * 100) : 0 };
  });

  // What the Grading Progress graph actually shows: live OMR job progress
  // while a batch upload is being preprocessed, otherwise the scanned/total
  // ratio above.
  readonly displayProgress = computed(() => {
    const jobStatus = this.activeJobStatus();
    if (jobStatus === null) return this.gradingProgress();
    const { scanned, total } = this.gradingProgress();
    return { scanned, total, percent: Math.round(jobStatus.progress * 100) };
  });

  // OMR reports preprocessing progress via a "rendering N pages" note (see
  // omr/internal/httpserver/handler/pdf.go) with no separate page-count
  // field, so this parses N back out of that note and combines it with the
  // live 0-1 progress fraction to show "rendered/total pages" instead of a
  // "scans graded" count that's meaningless before any scan has finished
  // preprocessing, let alone grading.
  private static readonly RENDERING_NOTES_RE = /rendering (\d+) pages/;
  readonly jobSubLabel = computed(() => {
    const jobStatus = this.activeJobStatus();
    const { scanned, total } = this.gradingProgress();
    if (!jobStatus || jobStatus.finished) return `${scanned}/${total} scans graded`;

    const match = CourseDetail.RENDERING_NOTES_RE.exec(jobStatus.notes);
    if (match) {
      const totalPages = Number(match[1]);
      const rendered = Math.min(totalPages, Math.round(jobStatus.progress * totalPages));
      return `${rendered}/${totalPages} pages rendered`;
    }
    return `${scanned}/${total} scans graded`;
  });

  // Same as jobSubLabel above, but for one exam-list row rather than the
  // course-wide dashboard card.
  examSubLabel(exam: Exam): string {
    const jobStatus = this.activeJobStatus();
    if (jobStatus && !jobStatus.finished && this.activeJobExamId() === exam.id) {
      const match = CourseDetail.RENDERING_NOTES_RE.exec(jobStatus.notes);
      if (match) {
        const totalPages = Number(match[1]);
        const rendered = Math.min(totalPages, Math.round(jobStatus.progress * totalPages));
        return `${rendered}/${totalPages} pages rendered`;
      }
    }
    return `${exam.scanned}/${exam.total} scans graded`;
  }

  // The card's footer while a job is active: OMR's own status note while
  // running (e.g. "rendering 4 pages"), or a terminal Completed/Failed once
  // the job finishes. null when no job is active, so the template falls back
  // to the usual "N scans remaining" text.
  readonly jobStatusLabel = computed(() => {
    const jobStatus = this.activeJobStatus();
    if (!jobStatus) return null;
    if (jobStatus.finished) return jobStatus.success === false ? 'Failed' : 'Completed';
    return jobStatus.notes || 'Processing...';
  });

  // The doughnut chart is a raw Chart.js instance, not template-bound, so it
  // needs an explicit push whenever displayProgress() changes -- otherwise it
  // would only ever redraw on the next full initCharts()/refreshCharts() call.
  private readonly jobProgressChartEffect = effect(() => {
    const percent = this.displayProgress().percent;
    if (this.jobProgressChart) {
      this.jobProgressChart.data.datasets[0].data = [percent, 100 - percent];
      this.jobProgressChart.update();
    }
  });

  ngOnInit(): void {
    // Reactive rather than a one-time snapshot read, so navigating from one
    // course straight to another re-triggers a load even when Angular's
    // default route-reuse strategy keeps this same component instance alive.
    this.route.paramMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      this.courseId.set(params.get('id') ?? '');
      this.loadCourse();
    });

    // Handles a notification deep-link ("?examId=...") arriving while this
    // course is already open, which loadCourse()'s own one-shot call to
    // openExamFromQueryParams (below) can't -- that only runs once per fetch.
    this.route.queryParamMap.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((params) => {
      if (!this.course()) return;
      this.openExamFromQueryParams(params);
    });

    // A background grading job finishing is exactly what changes an exam's
    // status/stats, but nothing else in this component ever hears about it --
    // the notification poll is the only thing that knows the moment it
    // happens, so use it to refresh instead of relying on a stale fetch-time
    // snapshot until the user manually reloads.
    this.notificationService.newNotifications$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe((notification) => {
      if (notification.type === 'Processing' && notification.courseId === this.courseId()) {
        this.refreshCourse();
      }
    });

    timer(EXAM_STATUS_POLL_INTERVAL_MS, EXAM_STATUS_POLL_INTERVAL_MS)
      .pipe(takeUntilDestroyed(this.destroyRef))
      .subscribe(() => this.pollExamStatuses());
  }

  // Lighter than refreshCourse()/loadCourse(): only re-fetches exams, and
  // only while one is actually mid-processing, so a course sitting idle
  // doesn't get an exams re-fetch every 2500ms forever.
  private pollExamStatuses(): void {
    const course = this.course();
    if (!course?.exams.some(exam => exam.status === ExamStatus.Processing)) return;
    this.examService.listExamsByCourse(this.courseId()).subscribe((apiExams) => {
      const current = this.course();
      if (!current) return;
      this.course.set({ ...current, exams: apiExams.map(apiExamToExam) });
    });
  }

  ngAfterViewInit(): void {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;

    // Scroll events do not bubble. Capture them at the document so both the
    // nested exams list and the application's .page-content scroller update
    // the overlay position.
    document.addEventListener('scroll', this.repositionExamMenuOnScroll, true);

    this.darkModeObserver = new MutationObserver(() => {
      if (this.userService.isProfessorOrAbove()) setTimeout(() => this.refreshCharts());
    });
    this.darkModeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  private initCharts(): void {
    if (!this.userService.isProfessorOrAbove() || !this.course() || !this.jobProgressCanvas) return;
    this.destroyCharts();
    this.jobProgressChart = this.createJobProgressChart();
    this.gradeDistChart = this.createGradeDistChart();
    this.regradeVolumeChart = this.createRegradeVolumeChart();
  }

  ngOnDestroy(): void {
    document.removeEventListener('scroll', this.repositionExamMenuOnScroll, true);
    this.darkModeObserver?.disconnect();
    this.destroyCharts();
  }

  private refreshCharts(): void {
    this.initCharts();
  }

  private destroyCharts(): void {
    this.jobProgressChart?.destroy();
    this.gradeDistChart?.destroy();
    this.regradeVolumeChart?.destroy();
    this.jobProgressChart = undefined;
    this.gradeDistChart = undefined;
    this.regradeVolumeChart = undefined;
  }

  private createJobProgressChart(): Chart<'doughnut'> {
    const config: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        datasets: [{
          data: [this.displayProgress().percent, 100 - this.displayProgress().percent],
          backgroundColor: [cssVar('--highlight2'), cssVar('--primary-darkened')],
          borderWidth: 0,
        }]
      },
      options: {
        cutout: '75%',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        }
      }
    };
    return new Chart(this.jobProgressCanvas.nativeElement, config);
  }

  private createGradeDistChart(): Chart<'bar'> {
    const config: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels: this.gradeDistributionLabels,
        datasets: [{
          data: this.gradeDistributionCounts(),
          backgroundColor: cssVar('--highlight2'),
          borderRadius: 4,
          borderWidth: 0,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
        },
        scales: {
          x: { grid: { display: false }, border: { display: false }, ticks: { color: cssVar('--color-text') } },
          y: { beginAtZero: true, ticks: { precision: 0, color: cssVar('--color-text') } },
        },
      }
    };
    return new Chart(this.gradeDistCanvas.nativeElement, config);
  }

  private createRegradeVolumeChart(): Chart<'bar'> {
    const config: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels: this.regradeVolumeLabels,
        datasets: [{
          data: this.regradeVolumeByDay(),
          backgroundColor: cssVar('--highlight2'),
          borderRadius: 4,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar('--color-text') },
          },
          y: { display: false, grid: { display: false } }
        }
      }
    };
    return new Chart(this.regradeVolumeCanvas.nativeElement, config);
  }

  readonly totalRegradeVolume = computed(() => this.regradeVolumeByDay().reduce((sum, count) => sum + count, 0));

  // Only called once `course` is loaded, so the course_id filter is always
  // meaningful (no window where every request briefly matches).
  //
  // Filtering by course_id (not the human-entered course code/name) avoids
  // cross-course leakage between two course offerings that share the same
  // name in different terms.
  private loadRegradeRequests(): void {
    const filterToCourse = (requests: ApiReviewRequest[]): ApiReviewRequest[] =>
      requests.filter((request) => request.course_id === this.courseId());

    if (this.userService.isProfessorOrAbove()) {
      this.isLoadingRegradeVolume.set(true);
      this.reviewRequestService.listReviewRequests().subscribe({
        next: (requests) => {
          const scoped = this.sortNewestFirst(filterToCourse(requests));
          this.regradeRequests.set(scoped.slice(0, 8));
          this.regradeVolumeByDay.set(this.computeRegradeVolumeByDay(scoped));
          this.isLoadingRegradeVolume.set(false);
          this.updateRegradeVolumeChart();
        },
        error: () => {
          this.regradeRequests.set([]);
          this.isLoadingRegradeVolume.set(false);
        },
      });
      return;
    }

    if (this.userService.isStudent()) {
      this.reviewRequestService.listMyReviewRequests().subscribe({
        next: (requests) => {
          const mapped = requests.map((request) => this.mapStudentRequest(request));
          const scoped = this.sortNewestFirst(filterToCourse(mapped));
          this.regradeRequests.set(scoped.slice(0, 8));
        },
        error: () => {
          this.regradeRequests.set([]);
        },
      });
      return;
    }

    this.regradeRequests.set([]);
  }

  // Buckets review requests by the weekday they were opened on (Mon..Sun),
  // matching the order of `regradeVolumeLabels`.
  private computeRegradeVolumeByDay(requests: ApiReviewRequest[]): number[] {
    const counts = [0, 0, 0, 0, 0, 0, 0];
    requests.forEach((request) => {
      const day = new Date(request.created_at).getDay(); // 0=Sun..6=Sat
      counts[day === 0 ? 6 : day - 1]++;
    });
    return counts;
  }

  private updateRegradeVolumeChart(): void {
    if (!this.regradeVolumeChart) return;
    this.regradeVolumeChart.data.datasets[0].data = this.regradeVolumeByDay();
    this.regradeVolumeChart.update();
  }

  private loadGradeDistribution(): void {
    this.isLoadingGradeDistribution.set(true);
    this.courseStatsError.set('');
    this.courseService.getCourseStats(this.courseId()).subscribe({
      next: (stats) => {
        this.courseStats.set(stats);
        this.gradedGradeCount.set(stats.graded_count);
        this.gradeDistributionCounts.set(this.gradeDistributionLabels.map(label => stats.distribution[label] ?? 0));
        this.isLoadingGradeDistribution.set(false);
        this.updateGradeDistChart();
      },
      error: () => {
        this.courseStatsError.set('Unable to load course statistics.');
        this.isLoadingGradeDistribution.set(false);
      },
    });
  }

  private updateGradeDistChart(): void {
    if (!this.gradeDistChart) return;
    this.gradeDistChart.data.datasets[0].data = this.gradeDistributionCounts();
    this.gradeDistChart.update();
  }

  openCourseComparison(): void {
    this.showingCourseComparison.set(true);
  }

  private sortNewestFirst(requests: ApiReviewRequest[]): ApiReviewRequest[] {
    return [...requests].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at));
  }

  private mapStudentRequest(request: ApiStudentReviewRequest): ApiReviewRequest {
    return {
      id: request.id,
      exam_grade_id: request.exam_grade_id,
      student_id: request.student_id,
      batch_id: request.batch_id,
      question_number: request.question_number,
      student_comment: request.student_comment,
      status: request.status,
      instructor_response: request.instructor_response,
      current_score: request.current_score,
      proposed_score: request.proposed_score,
      proposed_correct: request.proposed_correct,
      created_at: request.created_at,
      resolved_at: request.resolved_at,
      student_name: 'You',
      course_id: request.course_id,
      course_code: this.course()?.code ?? 'Review',
      term: '',
      exam_name: `Question ${request.question_number}`,
      max_score: request.current_score ?? request.proposed_score ?? 0,
    };
  }

  loadCourse(): void {
    const request = ++this.courseLoadRequest;
    this.isLoadingCourse.set(true);
    this.courseLoadError.set('');
    forkJoin({
      course: this.courseService.getCourse(this.courseId()),
      exams: this.examService.listExamsByCourse(this.courseId()),
    }).subscribe({
      next: ({ course, exams }) => {
        if (request !== this.courseLoadRequest) return;

        this.courseOwnerId.set(course.created_by);
        const newCourse = { ...apiCourseToCourse(course), exams: exams.map(apiExamToExam) };
        this.course.set(newCourse);
        // Keep the wizard's exam reference in sync with the reload, since it's
        // held separately from `course.exams` -- otherwise the exit-confirmation
        // check below would keep judging progress (answer key set? scans
        // uploaded?) against stale pre-refresh data.
        const wizardExam = this.examWizardExam();
        if (wizardExam) {
          this.examWizardExam.set(newCourse.exams.find(e => e.id === wizardExam.id) ?? wizardExam);
        }

        this.isLoadingCourse.set(false);
        this.loadStudents();
        this.loadRegradeRequests();
        this.loadGradeDistribution();
        this.openExamFromQueryParams(this.route.snapshot.queryParamMap);
        // These elements are created by the course view, so wait for its render.
        afterNextRender(() => {
          this.initCharts();
          this.scrollToFragment();
        }, { injector: this.injector });
      },
      error: () => {
        if (request !== this.courseLoadRequest) return;
        this.courseLoadError.set('Unable to load this course.');
        this.isLoadingCourse.set(false);
      },
    });
  }

  private scrollToFragment(): void {
    const fragment = this.route.snapshot.fragment;
    if (fragment) this.scrollToSection(fragment);
  }

  // Used by the fragment deep-link above and by the section-jump nav chips.
  scrollToSection(id: string): void {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  private loadStudents(): void {
    const course = this.course();
    if (!course) return;
    this.courseService.getCourseStudents(course.id).subscribe({
      next: (students) => {
        const current = this.course();
        if (!current) return;
        this.course.set({
          ...current,
          studentList: students,
          students: students.filter(student => student.active).length,
        });
      },
      error: () => {},
    });
  }

  onCanvasRosterChanged(result: CanvasRosterSync | null): void {
    const course = this.course();
    if (result && course) {
      this.course.set({
        ...course,
        students: result.active,
        canvasLink: course.canvasLink
          ? { ...course.canvasLink, last_synced_at: result.last_synced_at, connection_status: 'connected' }
          : null,
      });
    }
    this.loadStudents();
  }

  refreshCourse(): void {
    this.loadCourse();
  }

  goBack(): void {
    this.router.navigate(['/courses']);
  }

  // Course header actions
  confirmDelete(): void {
    this.deletingCourse.set(this.course());
    this.courseActionError.set('');
    this.deleteRequiresArchive.set(false);
  }

  courseHasHistory(course: Course): boolean {
    return course.students > 0 || course.exams.length > 0;
  }

  shouldArchiveCourse(course: Course): boolean {
    return this.courseHasHistory(course) || this.deleteRequiresArchive();
  }

  cancelDelete(): void {
    this.deletingCourse.set(null);
    this.isDeleting.set(false);
    this.courseActionError.set('');
    this.deleteRequiresArchive.set(false);
  }

  executeDelete(): void {
    const deletingCourse = this.deletingCourse();
    if (!deletingCourse || this.shouldArchiveCourse(deletingCourse)) return;
    this.isDeleting.set(true);
    this.courseActionError.set('');
    this.courseService.deleteCourse(deletingCourse.id).subscribe({
      next: () => {
        this.router.navigate(['/courses']);
      },
      error: (error) => {
        this.isDeleting.set(false);
        const code = error?.error?.error?.code;
        if (error?.status === 409 && code === 'course_has_history') {
          this.deleteRequiresArchive.set(true);
          this.courseActionError.set('This course contains historical records and cannot be permanently deleted. You can archive it instead.');
        } else {
          this.courseActionError.set(error?.error?.error?.message || 'Unable to update this course. Please try again.');
        }
      },
    });
  }

  onCourseArchived(): void {
    this.cancelDelete();
    void this.router.navigate(['/courses']);
  }

  promptRestore(): void {
    if (this.isRestoringCourse()) return;
    this.courseActionError.set('');
    this.confirmingRestore.set(true);
  }

  cancelRestore(): void {
    this.confirmingRestore.set(false);
  }

  restoreCourse(): void {
    const course = this.course();
    if (!course || this.isRestoringCourse()) return;
    this.isRestoringCourse.set(true);
    this.courseActionError.set('');
    this.courseService.restoreCourse(course.id).subscribe({
      next: () => {
        this.isRestoringCourse.set(false);
        this.confirmingRestore.set(false);
        this.refreshCourse();
      },
      error: (error) => {
        this.isRestoringCourse.set(false);
        this.confirmingRestore.set(false);
        this.courseActionError.set(error?.error?.error?.message || 'Unable to restore this course. Please try again.');
      },
    });
  }

  closeCourseModal(): void {
    this.editingCourse.set(null);
  }

  onCourseUpdated(apiCourse: ApiCourse): void {
    const course = this.course();
    if (course) {
      const updated = apiCourseToCourse(apiCourse);
      this.course.set({ ...course, ...updated, exams: course.exams, studentList: course.studentList, students: course.students });
    }
    this.closeCourseModal();
  }

  // Exam CRUD
  openExamWizard(mode: 'omr' | 'canvas' = 'omr'): void {
    this.examWizardStep.set(1);
    this.examWizardExam.set(null);
    this.examWizardMode.set(mode);
  }

  startCreatingExam(mode: 'omr' | 'canvas'): void {
    this.showAddExamMenu.set(false);
    this.openExamWizard(mode);
  }

  closeExamWizard(): void {
    this.examWizardStep.set(0);
    this.examWizardExam.set(null);
    this.examWizardMode.set('omr');
    this.confirmingExamWizardExit.set(false);
    this.refreshCourse();
  }

  // examWizardExam is a snapshot taken when the exam was created and doesn't
  // get updated as the wizard's own steps make progress (a saved answer key,
  // an uploaded scan) -- only `course.exams` does, via loadCourse(). Read
  // through to that live copy so exit checks reflect what's actually true,
  // not what was true when the wizard opened.
  readonly examWizardExamLive = computed(() => {
    const wizardExam = this.examWizardExam();
    if (!wizardExam) return null;
    return this.course()?.exams.find(e => e.id === wizardExam.id) ?? wizardExam;
  });

  // The exam already exists by step 2, so leaving early would silently strand
  // an ungraded exam -- warn with what's left instead of just closing, unless
  // the user already finished the step they're on. Reads the live exam (not
  // the step-1 creation snapshot) so this reflects progress made since, e.g.
  // an answer key saved or scans uploaded in this same session.
  requestCloseExamWizard(): void {
    const exam = this.examWizardExamLive();
    if (this.examWizardStep() === 2 && !exam?.hasAnswerKey) {
      this.confirmingExamWizardExit.set(true);
      return;
    }
    if (this.examWizardStep() === 3 && !exam?.total) {
      this.confirmingExamWizardExit.set(true);
      return;
    }
    this.closeExamWizard();
  }

  cancelExamWizardExit(): void {
    this.confirmingExamWizardExit.set(false);
  }

  onWizardExamCreated(apiExam: ApiExam): void {
    const course = this.course();
    if (!course) return;
    const exam = apiExamToExam(apiExam);
    this.course.set({ ...course, exams: [...course.exams, exam] });
    this.examWizardExam.set(exam);
    this.examWizardStep.set(2);
  }

  onCanvasAssignmentChanged(status: CanvasGradeReleaseStatus): void {
    const course = this.course();
    if (!course) return;
    this.course.set({
      ...course,
      exams: course.exams.map(exam => exam.id === status.exam_id ? {
        ...exam,
        canvasAssignmentId: status.assignment_id,
        canvasAssignmentName: status.assignment_name,
      } : exam),
    });
  }

  formatExamSchedule(exam: Exam): string {
    const start = this.parseExamWallClock(exam.start_time);
    const end = this.parseExamWallClock(exam.end_time);
    if (!start || !end) return 'Unscheduled';

    const date = new Intl.DateTimeFormat(undefined, {
      month: 'short', day: 'numeric', year: 'numeric',
    });
    const time = new Intl.DateTimeFormat(undefined, {
      hour: 'numeric', minute: '2-digit',
    });
    if (start.toDateString() === end.toDateString()) {
      return `${date.format(start)} · ${time.format(start)}–${time.format(end)}`;
    }
    return `${date.format(start)} at ${time.format(start)}–${date.format(end)} at ${time.format(end)}`;
  }

  openEditSchedule(exam: Exam): void {
    const start = this.parseExamWallClock(exam.start_time);
    const end = this.parseExamWallClock(exam.end_time);
    this.editingScheduleExam.set(exam);
    this.scheduleDate = start ? this.dateInputValue(start) : '';
    this.scheduleStartClock = start ? this.timeInputValue(start) : '';
    this.scheduleDurationMinutes = start && end
      ? Math.round((end.getTime() - start.getTime()) / 60000)
      : DEFAULT_EXAM_DURATION_MINUTES;
    this.scheduleError.set('');
  }

  closeEditSchedule(): void {
    if (this.isSavingSchedule()) return;
    this.editingScheduleExam.set(null);
    this.scheduleError.set('');
  }

  setScheduleDate(date: string): void {
    this.scheduleDate = date;
    if (!date) this.scheduleStartClock = '';
  }

  get scheduleIsValid(): boolean {
    if (!this.scheduleDate) return true;
    return this.scheduleStart !== null && this.scheduleEnd !== null;
  }

  get scheduleEndsAt(): string {
    const end = this.scheduleEnd;
    return end
      ? end.toLocaleString(undefined, {
          weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
        })
      : '';
  }

  saveExamSchedule(): void {
    const exam = this.editingScheduleExam();
    if (!exam || !this.scheduleIsValid || this.isSavingSchedule()) return;
    const start = this.scheduleStart;
    const end = this.scheduleEnd;
    this.isSavingSchedule.set(true);
    this.scheduleError.set('');

    this.examService.updateExamSchedule(
      exam.id,
      start ? this.localDateTimeValue(start) : null,
      end ? this.localDateTimeValue(end) : null,
    ).subscribe({
      next: (updated) => {
        this.replaceExam(updated);
        if (!exam.generatedPdfPath) {
          this.finishScheduleSave();
          return;
        }
        this.examService.generateExamPdf(exam.id).subscribe({
          next: (regenerated) => {
            this.replaceExam(regenerated);
            this.finishScheduleSave();
          },
          error: () => {
            this.isSavingSchedule.set(false);
            this.scheduleError.set('Schedule saved, but the existing exam PDF could not be refreshed. Try saving again.');
          },
        });
      },
      error: () => {
        this.isSavingSchedule.set(false);
        this.scheduleError.set('Unable to save the exam schedule.');
      },
    });
  }

  private get scheduleStart(): Date | null {
    if (!this.scheduleDate || !this.scheduleStartClock) return null;
    return this.parseExamWallClock(`${this.scheduleDate}T${this.scheduleStartClock}`);
  }

  private get scheduleEnd(): Date | null {
    const start = this.scheduleStart;
    if (!start || !this.scheduleDurationMinutes || this.scheduleDurationMinutes <= 0) return null;
    return new Date(start.getTime() + this.scheduleDurationMinutes * 60000);
  }

  private parseExamWallClock(value: string | null): Date | null {
    // Physical exam schedules are entered and printed as campus-local wall
    // time, so preserve the stored clock value instead of applying the
    // viewer's browser timezone offset.
    const match = value?.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
    if (!match) return null;
    const [, year, month, day, hour, minute] = match;
    const date = new Date(+year, +month - 1, +day, +hour, +minute);
    return Number.isNaN(date.getTime()) ? null : date;
  }

  private dateInputValue(date: Date): string {
    return `${date.getFullYear()}-${this.padDatePart(date.getMonth() + 1)}-${this.padDatePart(date.getDate())}`;
  }

  private timeInputValue(date: Date): string {
    return `${this.padDatePart(date.getHours())}:${this.padDatePart(date.getMinutes())}`;
  }

  private localDateTimeValue(date: Date): string {
    return `${this.dateInputValue(date)}T${this.timeInputValue(date)}`;
  }

  private padDatePart(value: number): string {
    return String(value).padStart(2, '0');
  }

  private replaceExam(apiExam: ApiExam): void {
    const course = this.course();
    if (!course) return;
    const updated = apiExamToExam(apiExam);
    this.course.set({
      ...course,
      exams: course.exams.map((exam) => exam.id === updated.id ? updated : exam),
    });
  }

  private finishScheduleSave(): void {
    this.isSavingSchedule.set(false);
    this.editingScheduleExam.set(null);
  }

  confirmExamDelete(exam: Exam): void {
    this.deletingExam.set(exam);
  }

  cancelExamDelete(): void {
    this.deletingExam.set(null);
    this.isDeletingExam.set(false);
  }

  executeExamDelete(): void {
    const exam = this.deletingExam();
    if (!exam || !this.course()) return;
    this.isDeletingExam.set(true);

    this.examService.deleteExam(exam.id).subscribe({
      next: () => {
        const course = this.course();
        if (course) {
          this.course.set({ ...course, exams: course.exams.filter((e) => e.id !== exam.id) });
        }
        this.cancelExamDelete();
      },
      error: () => {
        this.isDeletingExam.set(false);
      },
    });
  }

  // Students
  onStudentsAdded(count: number): void {
    const course = this.course();
    if (!course) return;
    this.course.set({ ...course, students: course.students + count });
    this.loadStudents();
    this.addingStudents.set(false);
  }

  onStudentRemoved(student: Student): void {
    const course = this.course();
    if (!course) return;
    this.course.set({
      ...course,
      students: Math.max(0, course.students - 1),
      studentList: course.studentList.filter((s) => s.id !== student.id),
    });
  }

  onStudentPromoted(student: Student): void {
    this.onStudentRemoved(student);
  }

  // Only the exam's creator can define its answer key (the backend enforces
  // this and returns 403 otherwise), so only surface the action on owned exams.
  canDefineAnswerKey(exam: Exam): boolean {
    const uid = this.userService.currentUser()?.id;
    return !!uid && exam.created_by === uid && !exam.templateMissing;
  }

  defineAnswerKey(exam: Exam): void {
    this.viewingAnswerKeyExam.set(exam);
  }

  // Same ownership rule the backend enforces (require_admin_or_prof + the
  // owning professor's course) -- see services/exam.py's _authorize_release.
  canReleaseExam(exam: Exam): boolean {
    const uid = this.userService.currentUser()?.id;
    return this.userService.isAdmin() || (!!uid && exam.created_by === uid);
  }

  releaseStatus(exam: Exam): ReleaseStatus {
    return exam.released ? ReleaseStatus.Released : ReleaseStatus.Unreleased;
  }

  // A whole class's grades become visible to students the moment this
  // fires, so it deserves a confirmation step, unlike closeExam which just
  // hides them again and is easy to undo.
  confirmExamRelease(exam: Exam): void {
    this.releaseNotice.set('');
    this.confirmingReleaseExam.set(exam);
  }

  cancelExamRelease(): void {
    this.confirmingReleaseExam.set(null);
  }

  executeExamRelease(): void {
    const exam = this.confirmingReleaseExam();
    if (!exam) return;
    this.confirmingReleaseExam.set(null);
    this.releaseExam(exam);
  }

  private releaseExam(exam: Exam): void {
    if (this.isReleasingExam()) return;
    this.isReleasingExam.set(true);
    this.releaseError.set('');
    this.releaseBlockers.set([]);
    this.examService.releaseExam(exam.id).subscribe({
      next: () => {
        this.patchExamReleased(exam, true);
        this.isReleasingExam.set(false);
        this.releaseNotice.set(`${exam.name} results are now visible to students.`);
      },
      error: (err) => {
        this.isReleasingExam.set(false);
        if (err.status === 409) {
          this.releaseBlockers.set(err.error?.error?.details ?? []);
          this.releaseError.set('Resolve the flagged grades and scans below before releasing results.');
          this.openExamStats(exam);
        } else {
          this.releaseError.set('Unable to release results.');
        }
      },
    });
  }

  closeExam(exam: Exam): void {
    if (this.isReleasingExam()) return;
    this.isReleasingExam.set(true);
    this.releaseError.set('');
    this.examService.closeExam(exam.id).subscribe({
      next: () => {
        this.patchExamReleased(exam, false);
        this.isReleasingExam.set(false);
        this.releaseNotice.set(`${exam.name} results are now hidden from students.`);
      },
      error: () => {
        this.isReleasingExam.set(false);
        this.releaseError.set('Unable to unrelease results.');
      },
    });
  }

  private patchExamReleased(exam: Exam, released: boolean): void {
    const course = this.course();
    if (course) {
      this.course.set({ ...course, exams: course.exams.map((e) => (e.id === exam.id ? { ...e, released } : e)) });
    }
  }

  canViewResults(exam: Exam): boolean {
    return this.userService.isStudent()
      ? exam.status === ExamStatus.Graded
      : exam.status === ExamStatus.Graded || exam.scanned > 0;
  }

  // Once results are released, new scans shouldn't be able to change grades
  // students may already be looking at -- unreleasing results re-opens uploads.
  canUploadScans(exam: Exam): boolean {
    return (
      !exam.released &&
      !exam.templateMissing &&
      exam.templateRegistered &&
      exam.answerKeysComplete
    );
  }

  scanUploadTitle(exam: Exam): string {
    if (exam.released) return 'Unrelease results before uploading more scans';
    if (exam.templateMissing) return 'Assign a template before uploading scans';
    if (!exam.hasAnswerKey) return 'Define the answer key before uploading scans';
    if (!exam.answerKeysComplete) return 'Complete every answer key version before uploading scans';
    if (!exam.templateRegistered) return 'Prepare the template for scanning';
    return 'Upload student scans for grading';
  }

  canChangeTemplate(exam: Exam): boolean {
    return exam.total === 0 || exam.templateMissing;
  }

  // Generation happens in the Answer Key modal once every version is
  // complete (see AnswerKey.generateExamPdf); this just offers the download
  // once that's produced a file to fetch.
  canDownloadExamPdf(exam: Exam): boolean {
    return !!exam.generatedPdfPath;
  }

  downloadExamPdf(exam: Exam): void {
    if (this.isDownloadingExamPdf()) return;
    this.isDownloadingExamPdf.set(true);
    this.examService.downloadExamPdf(exam.id).subscribe({
      next: (blob) => {
        this.isDownloadingExamPdf.set(false);
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `${exam.name}.pdf`;
        link.click();
        URL.revokeObjectURL(url);
      },
      error: () => {
        this.isDownloadingExamPdf.set(false);
      },
    });
  }

  downloadResults(exam: Exam): void {
    if (this.exportingExamId() === exam.id) return;
    this.exportingExamId.set(exam.id);
    this.exportErrorExamId.set(null);
    this.examService.exportExamResults(exam.id).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = this.resultsFileName(exam);
        link.click();
        URL.revokeObjectURL(url);
        if (this.exportingExamId() === exam.id) this.exportingExamId.set(null);
      },
      error: () => {
        if (this.exportingExamId() === exam.id) this.exportingExamId.set(null);
        this.exportErrorExamId.set(exam.id);
      },
    });
  }

  // Matches the backend's Content-Disposition filename (services/exam.py's
  // _export_filename) so the saved file is named the same either way.
  private resultsFileName(exam: Exam): string {
    const slug = exam.name.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-+|-+$/g, '').toLowerCase() || 'exam';
    return `${slug}-results.csv`;
  }

  goToTemplates(): void {
    this.viewingTemplates.set(true);
  }

  openAssignTemplate(exam: Exam): void {
    this.assigningTemplateExam.set(exam);
    this.templateOptions.set([]);
    this.selectedTemplateId.set('');
    this.templateAssignError.set('');
    this.confirmingTemplateChange.set(false);
    this.isLoadingTemplateOptions.set(true);

    this.templateService.listMyTemplates().subscribe({
      next: (templates) => {
        this.templateOptions.set(templates);
        this.selectedTemplateId.set(templates.find(template => template.id === exam.exam_template_id)?.id
          ?? templates[0]?.id
          ?? '');
        this.isLoadingTemplateOptions.set(false);
      },
      error: () => {
        this.templateAssignError.set('Unable to load templates.');
        this.isLoadingTemplateOptions.set(false);
      },
    });
  }

  closeAssignTemplate(): void {
    if (this.isAssigningTemplate()) return;
    this.assigningTemplateExam.set(null);
    this.templateOptions.set([]);
    this.selectedTemplateId.set('');
    this.templateAssignError.set('');
    this.confirmingTemplateChange.set(false);
    this.isLoadingTemplateOptions.set(false);
  }

  createTemplateForAssignment(): void {
    this.closeAssignTemplate();
    this.goToTemplates();
  }

  assignTemplate(deleteAnswerKeys = false): void {
    const exam = this.assigningTemplateExam();
    const selectedTemplateId = this.selectedTemplateId();
    if (
      !exam ||
      !selectedTemplateId ||
      selectedTemplateId === exam.exam_template_id ||
      this.isAssigningTemplate()
    ) return;

    if (exam.hasAnswerKey && !deleteAnswerKeys) {
      this.confirmingTemplateChange.set(true);
      return;
    }

    this.templateAssignError.set('');
    this.isAssigningTemplate.set(true);
    this.examService.updateExamTemplate(exam.id, selectedTemplateId, deleteAnswerKeys).subscribe({
      next: () => {
        this.isAssigningTemplate.set(false);
        this.closeAssignTemplate();
        this.refreshCourse();
      },
      error: (error) => {
        if (error?.error?.error?.code === 'answer_keys_require_reset') {
          this.confirmingTemplateChange.set(true);
          this.templateAssignError.set('');
        } else if (error?.error?.error?.code === 'exam_has_scans') {
          this.templateAssignError.set('This exam now has scans, so its template cannot be changed.');
        } else {
          this.templateAssignError.set('Unable to change the template.');
        }
        this.isAssigningTemplate.set(false);
      },
    });
  }

  // Overflow ("...") menu on an exam row
  toggleExamMenu(examId: string, trigger?: HTMLElement): void {
    if (this.openMenuExamId() === examId) {
      this.closeExamMenu();
      return;
    }

    this.examMenuTrigger = trigger ?? null;
    this.openMenuExamId.set(examId);
    this.repositionExamMenu();
  }

  repositionExamMenu(): void {
    if (!this.openMenuExamId() || !this.examMenuTrigger) return;

    const triggerBounds = this.examMenuTrigger.getBoundingClientRect();
    this.examMenuPosition.set({
      top: triggerBounds.bottom + 4,
      right: window.innerWidth - triggerBounds.right,
    });
  }

  closeExamMenu(): void {
    this.openMenuExamId.set(null);
    this.examMenuPosition.set(null);
    this.examMenuTrigger = null;
  }

  @HostListener('window:resize')
  repositionExamMenuOnResize(): void {
    this.repositionExamMenu();
  }

  @HostListener('document:click')
  closeExamMenuOnOutsideClick(): void {
    this.closeExamMenu();
  }

  // Deep-links from a notification ("/courses?courseId=X&examId=Y", redirected
  // here as "/courses/X?examId=Y") into the matching exam's results, once the
  // course+exams have finished loading. A scan_failed notification instead
  // links with "&action=upload", since the scan never finished processing and
  // there's nothing to show but a re-upload.
  private openExamFromQueryParams(params: ParamMap): void {
    if (params.get('action') === 'comparison') {
      this.openCourseComparison();
      this.clearDeepLinkQueryParams();
      return;
    }

    const examId = params.get('examId');
    const course = this.course();
    if (!examId || !course) return;

    const exam = course.exams.find((e) => e.id === examId);
    if (!exam) return;

    if (params.get('action') === 'upload') {
      this.uploadScan(exam);
    } else if (this.userService.isStudent()) {
      // Same destination as the Results button, for both roles, so a
      // notification link lands wherever that button would.
      this.openStudentResults(exam);
    } else {
      this.openAnnotatedResults(exam);
    }
  }

  private clearDeepLinkQueryParams(): void {
    const params = this.route.snapshot.queryParamMap;
    if (!params.has('examId') && !params.has('action')) return;

    this.router.navigate([], {
      relativeTo: this.route,
      queryParams: {},
      replaceUrl: true,
    });
  }

  closeResults(): void {
    this.viewingStatsExam.set(null);
    this.releaseError.set('');
    this.releaseBlockers.set([]);
    this.clearDeepLinkQueryParams();
  }

  // The student entry point for the new results view. A student only ever
  // has one grade per exam, so unlike openAnnotatedResults below there's no
  // roster or triage step, just a direct jump once the grade is found.
  openStudentResults(exam: Exam): void {
    this.examService.listExamGrades(exam.id).subscribe({
      next: (grades) => {
        if (!grades.length) return;
        this.router.navigate(['/grades', grades[0].id, 'results']);
      },
    });
  }

  // The staff entry point for the annotated exam view: jumps straight to
  // whichever grade needs review first, same order the view's own roster
  // panel uses, so triage starts immediately instead of at an arbitrary grade.
  openAnnotatedResults(exam: Exam): void {
    this.examService.listExamGrades(exam.id).subscribe({
      next: (grades) => {
        if (!grades.length) return;
        const first = [...grades].sort((a, b) => Number(this.isNeedsReview(b)) - Number(this.isNeedsReview(a)))[0];
        this.router.navigate(['/grades', first.id, 'annotations']);
      },
    });
  }

  openExamStats(exam: Exam): void {
    this.viewingStatsExam.set(exam);
  }

  // A grade also reads as "needs review" when any question has an ambiguous
  // (e.g. multi-marked single-choice) answer, even if identity matching
  // succeeded and the backend status is still "graded". That flag/assign
  // flow is unrelated to per-question answer ambiguity, so it stays keyed off
  // the raw backend status instead.
  isNeedsReview(grade: ExamGrade): boolean {
    return grade.status === 'needs_review' || this.hasAmbiguousAnswers(grade);
  }

  hasAmbiguousAnswers(grade: ExamGrade): boolean {
    return Object.values(grade.question_results).some((result) => result.ambiguous);
  }

  uploadScan(exam: Exam): void {
    if (!this.canUploadScans(exam)) return;
    this.uploadingScansForExam.set(exam);
  }

  // The modal's own status poll stops as soon as it's unmounted, so a scan
  // still `pending` at close time won't get picked up until the separate
  // notification poll happens to fire -- refresh here so the exam list
  // reflects the latest status immediately on close, not just on next load.
  closeUploadModal(): void {
    this.uploadingScansForExam.set(null);
    this.clearDeepLinkQueryParams();
    this.refreshCourse();
  }

  // Scans are counted (exam.total / total_scans) as soon as they're uploaded,
  // well before grading finishes, so the course needs refreshing regardless
  // of processing status -- otherwise the exam-wizard's exit check keeps
  // judging a just-completed upload step against stale pre-upload data.
  onScanUploaded(scans: Scan[]): void {
    if (scans.length > 0) {
      this.refreshCourse();
    }
    // The seed scan is still 'pending' at this point (OMR hasn't preprocessed
    // it yet), so its id is what the job-status endpoint is keyed off of.
    const pendingScan = scans.find((scan) => scan.status === 'pending');
    if (pendingScan) {
      this.activeJobExamId.set(pendingScan.exam_id);
      this.pollJobStatus(pendingScan.id);
    }
  }

  // Polls the job-status endpoint at a tight interval so the Grading Progress
  // card can animate live while OMR preprocesses this scan. Runs
  // independently of the upload modal's own lifecycle (see activeJobStatus
  // above), and keeps polling until the job finishes, at which point the
  // terminal Completed/Failed status is cleared a few seconds later once
  // pollExamStatuses/refreshCourse has had a chance to catch up.
  private pollJobStatus(scanId: string): void {
    this.jobStatusSub?.unsubscribe();
    this.jobStatusSub = interval(1000)
      .pipe(
        startWith(0),
        switchMap(() =>
          this.scanService.getJobStatus(scanId).pipe(
            // A 404 (job id not stored yet, or already materialized) is
            // treated as "still waiting" rather than a hard error, so a
            // brief race right after upload doesn't kill the poll.
            catchError(() => of<ScanJobStatus>({ progress: 0, finished: false, success: null, notes: '' })),
          ),
        ),
        takeWhile((jobStatus) => !jobStatus.finished, true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((jobStatus) => {
        this.activeJobStatus.set(jobStatus);
        if (jobStatus.finished) {
          setTimeout(() => {
            this.activeJobStatus.set(null);
            this.activeJobExamId.set(null);
          }, 3000);
        }
      });
  }
}
