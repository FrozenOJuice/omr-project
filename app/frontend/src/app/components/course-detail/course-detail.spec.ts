import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import { vi } from 'vitest';
import { BehaviorSubject, of, Subject, throwError } from 'rxjs';
import { CourseDetail } from './course-detail';
import { CourseService } from '../../services/course.service';
import { ExamService } from '../../services/exam.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ExamAnswerKeyService } from '../../services/exam-answer-key.service';
import { ScanService } from '../../services/scan.service';
import { UserService } from '../../services/user.service';
import { ReviewRequestService } from '../../services/review-request.service';
import { CanvasService } from '../../services/canvas.service';
import { NotificationService } from '../../services/notification.service';
import { ExamStatus } from '../../enums/tags.enum';
import { ApiCourse, CourseStats, Student } from '../../models/course.model';
import { ApiExam, Exam, ExamGrade, ExamReleaseAuditEntry, ExamStats, apiExamToExam } from '../../models/exam.model';
import { ExamTemplateResponse } from '../../models/exam-template.model';
import { ApiReviewRequest } from '../../models/regrade-requests.model';
import { AcademicTerm } from '../../models/academic-term.model';
import { Notification } from '../../models/notification';

vi.mock('chart.js', () => {
  const Chart = class {
    static defaults = { font: { family: '' } };
    static register() {}
    constructor() {}
    destroy() {}
    data = { datasets: [{ data: [] }], labels: [] };
    update() {}
  };
  return { Chart, registerables: [] };
});

const mkApiExam = (id: string, name: string, courseId: string, isGraded: boolean): ApiExam => ({
  id,
  name,
  description: null,
  start_time: '2026-06-01T09:00:00Z',
  end_time: '2026-06-01T11:00:00Z',
  role: 'student',
  course_id: courseId,
  exam_template_id: null,
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  released: false,
  is_graded: isGraded,
  has_any_grade: isGraded,
  has_scans: false,
  total_scans: 0,
  graded_scans: 0,
  failed_scans: 0,
  has_answer_key: true,
  answer_keys_complete: true,
  template_registered: true,
  template_missing: false,
  template_warning: null,
});

const mkExam = (id: string, name: string, status: ExamStatus, courseId: string): Exam => ({
  id,
  name,
  description: null,
  start_time: '2026-06-01T09:00:00Z',
  end_time: '2026-06-01T11:00:00Z',
  role: 'student',
  course_id: courseId,
  exam_template_id: null,
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  released: false,
  status,
  scanned: 0,
  total: 0,
  completedAt: '',
  regradeCount: 0,
  ambiguousCount: 0,
  hasAnswerKey: true,
  answerKeysComplete: true,
  templateRegistered: true,
  templateMissing: false,
  templateWarning: null,
  generatedPdfPath: null,
});

const MOCK_TERM: AcademicTerm = {
  id: 'summer-1', institution: 'ubc', code: 'summer-session-1',
  name: 'Summer Session 1', term_type: 'preset', year_format: 'following_year',
  is_active: true, created_by: null, created_at: '', updated_at: '',
};

const MOCK_API_COURSE: ApiCourse = {
  id: 'c1',
  name: 'COSC 304 - Database Systems',
  academic_term_id: MOCK_TERM.id,
  academic_term: MOCK_TERM,
  academic_year_start: 2026,
  archived_at: null,
  created_by: 'prof-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  invite_link: 'link-c1',
  student_count: 5,
  can_manage_canvas: false,
};

const MOCK_RETENTION_POLICY = {
  id: 'policy-1',
  owner_user_id: 'prof-1',
  scanned_image_retention_months: 12,
  exam_record_retention_months: 12,
  retain_anonymized_analytics: true,
  source: 'ubc_default' as const,
  created_at: '2026-07-19T00:00:00Z',
  updated_at: '2026-07-19T00:00:00Z',
};

const MOCK_RETENTION_STATUS = {
  configured: true,
  policy: MOCK_RETENTION_POLICY,
  recommended: {
    scanned_image_retention_months: 12,
    exam_record_retention_months: 12,
    retain_anonymized_analytics: true,
    maximum_retention_months: 72,
    basis: 'UBC Records Schedules TL7300-15 and TL7100-25',
    source_urls: [],
  },
};

const MOCK_COURSE_STATS: CourseStats = {
  course_id: 'c1',
  exam_count: 2,
  graded_count: 4,
  mean_percentage: 76.25,
  standard_deviation_percentage: 16.4,
  median_percentage: 77.5,
  mode_percentages: [80],
  highest_percentage: 95,
  lowest_percentage: 45,
  distribution: { '<50': 1, '50-60': 0, '60-70': 1, '70-80': 0, '80-90': 1, '90-100': 1 },
  exams: [{
    exam_id: 'e1', exam_name: 'Midterm', graded_count: 4,
    mean_percentage: 76.25, standard_deviation_percentage: 16.4, median_percentage: 77.5, mode_percentages: [80],
    highest_percentage: 95, lowest_percentage: 45,
    distribution: { '<50': 1, '50-60': 0, '60-70': 1, '70-80': 0, '80-90': 1, '90-100': 1 },
  }],
};

const MOCK_STUDENTS: Student[] = [
  { id: 's1', userId: 'student-1', firstName: 'Alice', lastName: 'Example', email: 'alice@example.com', studentNumber: '12345678', accountStatus: 'linked' as const, source: 'manual', active: true },
  { id: 's2', userId: 'student-2', firstName: 'Bob', lastName: 'Example', email: 'bob@example.com', studentNumber: '87654321', accountStatus: 'linked' as const, source: 'manual', active: true },
];

const MOCK_TEMPLATE: ExamTemplateResponse = {
  id: 'tmpl-1',
  name: 'Replacement Template',
  created_by: 'u1',
  question_config: { '1': { choices: ['A', 'B', 'C', 'D', 'E'] } },
  total_questions: 1,
  version: 1,
  n_versions: 4,
  blueprint: null,
  version_from_q1: false,
  omr_template_id: null,
  generated_pdf_path: null,
  archived_at: null,
  sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1'] }],
};

const MOCK_EXAM_STATS: ExamStats = {
  exam_id: 'e1',
  graded_count: 2,
  mean_score: 7.5,
  standard_deviation_score: 0.5,
  median_score: 7.5,
  mode_scores: [7, 8],
  highest_score: 8,
  lowest_score: 7,
  mean_percentage: 75,
  standard_deviation_percentage: 5,
  min_percentage: 70,
  q1_percentage: 72.5,
  median_percentage: 75,
  q3_percentage: 77.5,
  max_percentage: 80,
  score_distribution: [],
  question_stats: [
    {
      question_number: '1',
      graded_count: 2,
      correct_count: 1,
      correct_percentage: 50,
      incorrect_count: 1,
      incorrect_percentage: 50,
      average_score: 0.5,
      max_score: 1,
      selected_distribution: { A: 1, B: 1 },
      answer_choices: [
        {
          answer: 'A',
          selected_count: 1,
          selected_percentage: 50,
          is_correct: true,
          high_group_percentage: null,
          low_group_percentage: null,
          effectiveness: 'correct',
        },
        {
          answer: 'B',
          selected_count: 1,
          selected_percentage: 50,
          is_correct: false,
          high_group_percentage: null,
          low_group_percentage: null,
          effectiveness: 'effective',
        },
      ],
      item_difficulty: 0.5,
      discrimination_index: 0.4,
      distractor_efficiency: 1,
    },
  ],
  version_stats: [],
};

MOCK_EXAM_STATS.version_stats = [
  {
    exam_version: 'A',
    graded_count: 2,
    mean_percentage: 75,
    average_item_difficulty: 0.5,
    average_discrimination_index: 0.4,
    average_distractor_efficiency: 1,
    difficult_question_count: 0,
    low_discrimination_question_count: 0,
    weak_distractor_question_count: 0,
    question_stats: MOCK_EXAM_STATS.question_stats,
  },
  {
    exam_version: 'B',
    graded_count: 4,
    mean_percentage: 61,
    average_item_difficulty: 0.25,
    average_discrimination_index: 0.1,
    average_distractor_efficiency: 0.33,
    difficult_question_count: 1,
    low_discrimination_question_count: 1,
    weak_distractor_question_count: 1,
    question_stats: [
      {
        ...MOCK_EXAM_STATS.question_stats[0],
        graded_count: 4,
        correct_count: 1,
        correct_percentage: 25,
        incorrect_count: 3,
        incorrect_percentage: 75,
        item_difficulty: 0.25,
        discrimination_index: 0.1,
        distractor_efficiency: 0.33,
        answer_choices: [
          {
            answer: 'B',
            selected_count: 3,
            selected_percentage: 75,
            is_correct: false,
            high_group_percentage: 50,
            low_group_percentage: 100,
            effectiveness: 'effective',
          },
          {
            answer: 'C',
            selected_count: 1,
            selected_percentage: 25,
            is_correct: true,
            high_group_percentage: 50,
            low_group_percentage: 0,
            effectiveness: 'correct',
          },
        ],
      },
    ],
  },
];

const MOCK_EXAM_GRADES: ExamGrade[] = [
  {
    id: 'grade-1',
    omr_marking_id: 'marking-1',
    exam_answer_key_id: 'key-1',
    question_results: {
      '1': {
        grading_type: 'single',
        student_answers: ['A'],
        correct_answers: ['A'],
        correct: true,
        score: 1,
        max_score: 1,
        ambiguous: false,
      },
      '2': {
        grading_type: 'single',
        student_answers: [],
        correct_answers: ['B'],
        correct: false,
        score: 0,
        max_score: 1,
        ambiguous: false,
      },
    },
    total_score: 8,
    max_score: 10,
    template_version: 1,
    exam_version: 'A',
    student_id: 'student-1',
    status: 'graded',
    flag_reason: null,
    graded_at: '2026-07-05T00:00:00Z',
    page_count: 2,
    exam_id: 'e1',
    section_results: [
      {
        id: 'multiple-choice',
        name: 'Multiple Choice',
        type: 'multiple_choice',
        question_ids: ['1'],
        score: 1,
        max_score: 1,
      },
      {
        id: 'true-false',
        name: 'True / False',
        type: 'true_false',
        question_ids: ['2'],
        score: 0,
        max_score: 1,
      },
    ],
  },
];

const MOCK_REGRADE_REQUESTS: ApiReviewRequest[] = [
  {
    id: 'rr-1',
    exam_grade_id: 'grade-1',
    student_id: 'student-1',
    batch_id: null,
    question_number: '1',
    student_comment: 'Please recheck.',
    status: 'pending',
    instructor_response: null,
    current_score: 8,
    proposed_score: null,
    proposed_correct: null,
    created_at: '2026-07-06T00:00:00Z',
    resolved_at: null,
    student_name: 'Alice Example',
    // Must match the mock course under test (id "c1").
    course_id: 'c1',
    course_code: 'COSC 304 - Database Systems',
    term: 'Summer Session 1',
    exam_name: 'Midterm',
    max_score: 10,
  },
  {
    id: 'rr-2',
    exam_grade_id: 'grade-2',
    student_id: 'student-2',
    batch_id: null,
    question_number: '2',
    student_comment: 'Different course.',
    status: 'pending',
    instructor_response: null,
    current_score: 5,
    proposed_score: null,
    proposed_correct: null,
    created_at: '2026-07-05T00:00:00Z',
    resolved_at: null,
    student_name: 'Bob Example',
    // A different course (even one that happens to share a name/code with
    // another offering) -- must be excluded from course "c1"'s dashboard.
    course_id: 'course-other',
    course_code: 'COSC 499 - Capstone Project',
    term: 'Winter Session 1',
    exam_name: 'Project',
    max_score: 10,
  },
];

describe('CourseDetail', () => {
  let component: CourseDetail;
  let fixture: ComponentFixture<CourseDetail>;

  const mockCourseService = {
    getCourse: vi.fn(() => of(MOCK_API_COURSE)),
    getCourseStats: vi.fn(() => of(MOCK_COURSE_STATS)),
    listCourses: vi.fn(() => of([MOCK_API_COURSE])),
    listCourseComparisons: vi.fn(() => of([])),
    createCourseComparison: vi.fn(),
    updateCourseComparison: vi.fn(),
    deleteCourseComparison: vi.fn(() => of(void 0)),
    deleteCourse: vi.fn(() => of(null)),
    archiveCourse: vi.fn(() => of(null)),
    getRetentionPolicy: vi.fn(() => of(MOCK_RETENTION_STATUS)),
    upsertRetentionPolicy: vi.fn(() => of(MOCK_RETENTION_POLICY)),
    getCourseStudents: vi.fn(() => of(MOCK_STUDENTS)),
    unenrollStudent: vi.fn(() => of(null)),
  };
  const mockExamService = {
    listExamsByCourse: vi.fn(() => of([] as ApiExam[])),
    getExamStats: vi.fn(() => of(MOCK_EXAM_STATS)),
    listExamGrades: vi.fn(() => of(MOCK_EXAM_GRADES)),
    getReleaseHistory: vi.fn(() => of([] as ExamReleaseAuditEntry[])),
    getGradeQuestionSnippet: vi.fn(() => of(new Blob(['snippet'], { type: 'image/jpeg' }))),
    updateGrade: vi.fn(() => of(MOCK_EXAM_GRADES[0])),
    releaseExam: vi.fn(() => of({} as never)),
    closeExam: vi.fn(() => of({} as never)),
    updateExamTemplate: vi.fn(() => of({} as ApiExam)),
    updateExamSchedule: vi.fn(() => of(mkApiExam('e1', 'Midterm', 'c1', true))),
    generateExamPdf: vi.fn(() => of(mkApiExam('e1', 'Midterm', 'c1', true))),
    deleteExam: vi.fn(() => of(void 0)),
    downloadExamPdf: vi.fn(() => of(new Blob(['pdf'], { type: 'application/pdf' }))),
    exportExamResults: vi.fn(() => of(new Blob(['csv'], { type: 'text/csv' }))),
    // Consumed by the real app-answer-key child rendered during the exam-creation wizard
    getExam: vi.fn(() => of({ id: 'e3', name: 'Quiz', course_id: 'c1', exam_template_id: 'tmpl-1' } as never)),
  };
  const mockTemplateService = {
    listMyTemplates: vi.fn(() => of([MOCK_TEMPLATE])),
    // Consumed by the real app-answer-key child rendered during the exam-creation wizard
    getTemplate: vi.fn(() => of(MOCK_TEMPLATE)),
    finalizeTemplate: vi.fn(() => of(MOCK_TEMPLATE)),
  };
  // Consumed by the real app-answer-key child rendered during the exam-creation wizard
  const mockAnswerKeyService = {
    listAnswerKeysByExam: vi.fn(() => of([])),
  };
  // Consumed by the real app-scan-upload-modal child rendered during the exam-creation wizard
  const mockScanService = {
    listScansByExam: vi.fn(() => of([])),
    getJobStatus: vi.fn(() => of({ progress: 0, finished: false, success: null, notes: '' })),
  };
  const mockReviewRequestService = {
    listReviewRequests: vi.fn(() => of(MOCK_REGRADE_REQUESTS)),
    listMyReviewRequests: vi.fn(() => of([])),
    createReviewRequest: vi.fn(() => of({
      id: 'rr-3',
      exam_grade_id: 'grade-1',
      student_id: 'student-1',
      question_number: '1',
      student_comment: 'Please recheck question 1.',
      status: 'pending',
      instructor_response: null,
      current_score: 8,
      proposed_score: null,
      created_at: '2026-07-06T00:00:00Z',
      resolved_at: null,
    })),
  };
  const mockUserService = {
    isProfessorOrAbove: vi.fn(() => true),
    isStudent: vi.fn(() => false),
    isAdmin: vi.fn(() => false),
    currentUser: vi.fn(() => null),
    role: vi.fn(() => null),
  };

  const routerMock = { navigate: vi.fn() };
  const notificationsSubject = new Subject<Notification>();
  const mockNotificationService = { newNotifications$: notificationsSubject.asObservable() };
  const mkParamMap = (params: Record<string, string>) => ({
    get: (key: string) => params[key] ?? null,
    has: (key: string) => key in params,
  });
  const paramMapSubject = new BehaviorSubject<ReturnType<typeof mkParamMap>>(mkParamMap({ id: 'c1' }));
  const queryParamMapSubject = new BehaviorSubject<ReturnType<typeof mkParamMap>>(mkParamMap({}));
  const mockCanvasService = {
    syncRoster: vi.fn(),
    inviteStudent: vi.fn(),
    invitePendingStudents: vi.fn(),
    getAssignments: vi.fn(() => of([])),
    getGradeRelease: vi.fn(),
    linkExamAssignment: vi.fn(),
    unlinkExamAssignment: vi.fn(),
    releaseGrades: vi.fn(),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockCourseService.getCourse.mockReturnValue(of(MOCK_API_COURSE));
    mockCourseService.getCourseStats.mockReturnValue(of(MOCK_COURSE_STATS));
    mockCourseService.listCourses.mockReturnValue(of([MOCK_API_COURSE]));
    mockCourseService.listCourseComparisons.mockReturnValue(of([]));
    mockCourseService.deleteCourse.mockReturnValue(of(null));
    mockCourseService.archiveCourse.mockReturnValue(of(null));
    mockCourseService.getRetentionPolicy.mockReturnValue(of(MOCK_RETENTION_STATUS));
    mockCourseService.upsertRetentionPolicy.mockReturnValue(of(MOCK_RETENTION_POLICY));
    mockCourseService.getCourseStudents.mockReturnValue(of(MOCK_STUDENTS));
    mockExamService.listExamsByCourse.mockReturnValue(of([
      mkApiExam('e1', 'Midterm', 'c1', true),
      mkApiExam('e2', 'Final', 'c1', false),
    ]));
    mockExamService.getExamStats.mockReturnValue(of(MOCK_EXAM_STATS));
    mockExamService.listExamGrades.mockReturnValue(of(MOCK_EXAM_GRADES));
    mockExamService.getReleaseHistory.mockReturnValue(of([] as ExamReleaseAuditEntry[]));
    mockExamService.getGradeQuestionSnippet.mockReturnValue(of(new Blob(['snippet'], { type: 'image/jpeg' })));
    mockExamService.updateExamTemplate.mockReturnValue(of({} as ApiExam));
    mockExamService.updateExamSchedule.mockReturnValue(of(mkApiExam('e1', 'Midterm', 'c1', true)));
    mockExamService.generateExamPdf.mockReturnValue(of(mkApiExam('e1', 'Midterm', 'c1', true)));
    mockExamService.deleteExam.mockReturnValue(of(void 0));
    mockExamService.downloadExamPdf.mockReturnValue(of(new Blob(['pdf'], { type: 'application/pdf' })));
    mockExamService.exportExamResults.mockReturnValue(of(new Blob(['csv'], { type: 'text/csv' })));
    mockTemplateService.listMyTemplates.mockReturnValue(of([MOCK_TEMPLATE]));
    mockReviewRequestService.listReviewRequests.mockReturnValue(of(MOCK_REGRADE_REQUESTS));
    mockUserService.isProfessorOrAbove.mockReturnValue(true);
    mockUserService.isStudent.mockReturnValue(false);
    mockUserService.isAdmin.mockReturnValue(false);
    mockUserService.currentUser.mockReturnValue(null);
    mockUserService.role.mockReturnValue(null);
    routerMock.navigate.mockClear();
    paramMapSubject.next(mkParamMap({ id: 'c1' }));
    queryParamMapSubject.next(mkParamMap({}));

    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:snippet'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });

    await TestBed.configureTestingModule({
      imports: [CourseDetail],
      providers: [
        { provide: CourseService, useValue: mockCourseService },
        { provide: ExamService, useValue: mockExamService },
        { provide: ExamTemplateService, useValue: mockTemplateService },
        { provide: ExamAnswerKeyService, useValue: mockAnswerKeyService },
        { provide: ScanService, useValue: mockScanService },
        { provide: ReviewRequestService, useValue: mockReviewRequestService },
        { provide: UserService, useValue: mockUserService },
        { provide: CanvasService, useValue: mockCanvasService },
        { provide: NotificationService, useValue: mockNotificationService },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              paramMap: { get: (key: string) => (key === 'id' ? 'c1' : null) },
              queryParamMap: { get: () => null, has: () => false },
            },
            paramMap: paramMapSubject.asObservable(),
            queryParamMap: queryParamMapSubject.asObservable(),
          },
        },
        { provide: Router, useValue: routerMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CourseDetail);
    component = fixture.componentInstance;
  });

  const render = async () => {
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  };

  it('should create and load the course by route id', async () => {
    await render();
    expect(mockCourseService.getCourse).toHaveBeenCalledWith('c1');
    expect(component.course()?.code).toBe('COSC 304');
    expect(component.course()?.exams.length).toBe(2);
  });

  it('explains that a processed archived course cannot be restored', async () => {
    mockCourseService.getCourse.mockReturnValue(of({
      ...MOCK_API_COURSE,
      archived_at: '2025-01-01T00:00:00Z',
      retention_processed_at: '2026-01-01T00:00:00Z',
    }));

    await render();

    const banner = fixture.nativeElement.querySelector('.archived-read-only-banner');
    expect(banner.textContent).toContain('permanently condensed');
    expect(banner.textContent).toContain('can no longer be restored or changed');
    expect(banner.textContent).not.toContain('Restore this course');
  });

  it('still tells users how to restore an unprocessed archived course', async () => {
    mockCourseService.getCourse.mockReturnValue(of({
      ...MOCK_API_COURSE,
      archived_at: '2025-01-01T00:00:00Z',
      retention_processed_at: null,
    }));

    await render();

    const banner = fixture.nativeElement.querySelector('.archived-read-only-banner');
    expect(banner.textContent).toContain('Use Restore Course above to make changes again');
  });

  it('hides Canvas management actions from a non-owner administrator', async () => {
    mockCourseService.getCourse.mockReturnValue(of({
      ...MOCK_API_COURSE,
      source: 'canvas',
      can_manage_canvas: false,
    }));
    component.openMenuExamId.set('e1');
    await render();

    expect(fixture.nativeElement.querySelector('.add-exam-dropdown')).toBeNull();
    expect(fixture.nativeElement.textContent).not.toContain(
      'Manage Canvas grades and marked exam result links',
    );
  });

  it('ignores stale refreshes while answer-key setup is completing', () => {
    const staleCourse = new Subject<ApiCourse>();
    mockCourseService.getCourse
      .mockReturnValueOnce(staleCourse as never)
      .mockReturnValueOnce(of(MOCK_API_COURSE));

    fixture.detectChanges();
    component.refreshCourse();
    staleCourse.next({ ...MOCK_API_COURSE, name: 'COSC 499 - Stale' });

    expect(component.course()?.name).toBe('Database Systems');
  });

  it('should render charts for professor-or-above', async () => {
    await render();
    const cards = fixture.debugElement.queryAll(By.css('.graph-card'));
    expect(cards.length).toBe(3);
  });

  it('should not render charts for a student', async () => {
    mockUserService.isProfessorOrAbove.mockReturnValue(false);
    mockUserService.isStudent.mockReturnValue(true);
    await render();
    const cards = fixture.debugElement.queryAll(By.css('.graph-card'));
    expect(cards.length).toBe(0);
  });

  it('should filter latest re-grade requests to this course', async () => {
    await render();
    expect(component.regradeRequests().length).toBe(1);
    expect(component.regradeRequests()[0].course_code).toBe('COSC 304 - Database Systems');
  });

  it('should clear the loading flag once re-grade volume has loaded', async () => {
    await render();
    expect(component.isLoadingRegradeVolume()).toBe(false);
  });

  it('scrollToFragment scrolls to the element matching the route fragment', async () => {
    await render();
    const scrollSpy = vi.fn();
    const fakeEl = { scrollIntoView: scrollSpy } as unknown as HTMLElement;
    const getByIdSpy = vi.spyOn(document, 'getElementById').mockReturnValue(fakeEl);
    (component as any).route.snapshot.fragment = 'students';

    (component as any).scrollToFragment();

    expect(getByIdSpy).toHaveBeenCalledWith('students');
    expect(scrollSpy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    getByIdSpy.mockRestore();
  });

  it('scrollToSection is a no-op when the target element is not in the DOM', async () => {
    await render();
    expect(() => component.scrollToSection('does-not-exist')).not.toThrow();
  });

  it('gradingProgress sums scanned/total scans across the course exams', async () => {
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e1', 'Midterm', 'c1', true), graded_scans: 3, total_scans: 5 },
      { ...mkApiExam('e2', 'Final', 'c1', false), graded_scans: 1, total_scans: 5 },
    ]));
    await render();
    expect(component.gradingProgress()).toEqual({ scanned: 4, total: 10, percent: 40 });
  });

  it('displayProgress falls back to gradingProgress when no OMR job is active', async () => {
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e1', 'Midterm', 'c1', true), graded_scans: 3, total_scans: 5 },
    ]));
    await render();
    expect(component.activeJobStatus()).toBeNull();
    expect(component.displayProgress()).toEqual(component.gradingProgress());
  });

  it('displayProgress shows the live OMR job percentage while a job is active', async () => {
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e1', 'Midterm', 'c1', true), graded_scans: 3, total_scans: 5 },
    ]));
    await render();

    component.activeJobStatus.set({ progress: 0.5, finished: false, success: null, notes: 'rendering 4 pages' });

    expect(component.displayProgress()).toEqual({ scanned: 3, total: 5, percent: 50 });
  });

  it('jobStatusLabel is null when no OMR job is active', async () => {
    await render();
    expect(component.jobStatusLabel()).toBeNull();
  });

  it('jobStatusLabel surfaces the OMR job\'s live status note while running', async () => {
    await render();
    component.activeJobStatus.set({ progress: 0.5, finished: false, success: null, notes: 'rendering 4 pages' });
    expect(component.jobStatusLabel()).toBe('rendering 4 pages');
  });

  it('jobStatusLabel falls back to a generic label when the running job has no notes yet', async () => {
    await render();
    component.activeJobStatus.set({ progress: 0, finished: false, success: null, notes: '' });
    expect(component.jobStatusLabel()).toBe('Processing...');
  });

  it('jobStatusLabel shows Completed once a successful job finishes', async () => {
    await render();
    component.activeJobStatus.set({ progress: 1, finished: true, success: true, notes: '' });
    expect(component.jobStatusLabel()).toBe('Completed');
  });

  it('jobStatusLabel shows Failed once an unsuccessful job finishes', async () => {
    await render();
    component.activeJobStatus.set({ progress: 1, finished: true, success: false, notes: '' });
    expect(component.jobStatusLabel()).toBe('Failed');
  });

  it('loads the course grade distribution from the course stats endpoint', async () => {
    await render();
    expect(mockCourseService.getCourseStats).toHaveBeenCalledWith('c1');
    expect(component.gradedGradeCount()).toBe(4);
    expect(component.gradeDistributionCounts()).toEqual([1, 0, 1, 0, 1, 1]);
    expect(component.courseStats()).toEqual(MOCK_COURSE_STATS);
  });

  it('shows the complete course statistics when View all stats is selected', async () => {
    await render();
    const button = fixture.debugElement.queryAll(By.css('.section-nav button'))
      .find(item => item.nativeElement.textContent.includes('View all stats'))!;

    expect(button).toBeDefined();
    expect(fixture.debugElement.query(By.css('app-course-header .page-actions'))?.nativeElement.textContent)
      .not.toContain('View all stats');

    button.triggerEventHandler('click');
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.course-stats-card'))).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('76.25%');
    expect(fixture.nativeElement.textContent).toContain('Midterm');
  });

  it('keeps the course back action in the staff sticky section toolbar', async () => {
    await render();
    const stickyBack = fixture.debugElement.query(By.css('.section-nav-back'));

    expect(stickyBack).not.toBeNull();
    expect(fixture.debugElement.query(By.css('app-course-header [title="Back to courses"]'))).toBeNull();
    stickyBack.triggerEventHandler('click');
    expect(routerMock.navigate).toHaveBeenCalledWith(['/courses']);
  });

  it('keeps the header back action for students without the staff section toolbar', async () => {
    mockUserService.isProfessorOrAbove.mockReturnValue(false);
    mockUserService.isStudent.mockReturnValue(true);
    await render();

    expect(fixture.debugElement.query(By.css('.section-nav'))).toBeNull();
    expect(fixture.debugElement.query(By.css('app-course-header [title="Back to courses"]'))).not.toBeNull();
  });

  it('computes re-grade volume by weekday scoped to this course', async () => {
    await render();
    // rr-1 (COSC 304, 2026-07-06 -> a Monday) is the only request scoped to this course
    const total = component.regradeVolumeByDay().reduce((sum, n) => sum + n, 0);
    expect(total).toBe(1);
    expect(component.totalRegradeVolume()).toBe(1);
  });

  it('should render one exam row per exam in the course', async () => {
    await render();
    const rows = fixture.debugElement.queryAll(By.css('.exam-row'));
    expect(rows.length).toBe(2);
  });

  it('shows scheduled and unscheduled exam dates in the exam list', async () => {
    mockExamService.listExamsByCourse.mockReturnValue(of([
      mkApiExam('e1', 'Midterm', 'c1', true),
      { ...mkApiExam('e2', 'Final', 'c1', false), start_time: null, end_time: null },
    ]));

    await render();

    const schedules = fixture.nativeElement.querySelectorAll('.exam-schedule');
    expect(schedules[0].textContent).toContain('Jun 1, 2026');
    expect(schedules[0].textContent).toContain('9:00');
    expect(schedules[1].textContent).toContain('Unscheduled');
  });

  it('edits an exam schedule using date, start time, and duration', async () => {
    await render();
    const exam = component.course()!.exams[0];
    mockExamService.updateExamSchedule.mockReturnValueOnce(of({
      ...mkApiExam(exam.id, exam.name, 'c1', true),
      start_time: '2026-06-03T13:15:00Z',
      end_time: '2026-06-03T14:45:00Z',
    }));
    component.openEditSchedule(exam);
    component.scheduleDate = '2026-06-03';
    component.scheduleStartClock = '13:15';
    component.scheduleDurationMinutes = 90;

    component.saveExamSchedule();

    expect(mockExamService.updateExamSchedule).toHaveBeenCalledWith(
      exam.id,
      '2026-06-03T13:15',
      '2026-06-03T14:45',
    );
    expect(component.course()!.exams[0].start_time).toBe('2026-06-03T13:15:00Z');
    expect(component.editingScheduleExam()).toBeNull();
  });

  it('clears an exam schedule when its date is removed', async () => {
    await render();
    const exam = component.course()!.exams[0];
    mockExamService.updateExamSchedule.mockReturnValueOnce(of({
      ...mkApiExam(exam.id, exam.name, 'c1', true),
      start_time: null,
      end_time: null,
    }));
    component.openEditSchedule(exam);
    component.setScheduleDate('');

    component.saveExamSchedule();

    expect(mockExamService.updateExamSchedule).toHaveBeenCalledWith(exam.id, null, null);
    expect(component.course()!.exams[0].start_time).toBeNull();
  });

  it('refreshes an existing generated PDF after changing its schedule', async () => {
    await render();
    const exam = { ...component.course()!.exams[0], generatedPdfPath: 'generated/exam/e1/exam_sheet.pdf' };
    const updated = {
      ...mkApiExam(exam.id, exam.name, 'c1', true),
      generated_pdf_path: exam.generatedPdfPath,
    };
    mockExamService.updateExamSchedule.mockReturnValueOnce(of(updated));
    mockExamService.generateExamPdf.mockReturnValueOnce(of(updated));
    component.openEditSchedule(exam);

    component.saveExamSchedule();

    expect(mockExamService.generateExamPdf).toHaveBeenCalledWith(exam.id);
    expect(component.editingScheduleExam()).toBeNull();
  });

  // Download exam PDF

  it('canDownloadExamPdf is true only once a PDF has been generated', async () => {
    await render();
    const exam = component.course()!.exams[0];
    expect(component.canDownloadExamPdf({ ...exam, generatedPdfPath: null })).toBe(false);
    expect(component.canDownloadExamPdf({ ...exam, generatedPdfPath: 'exams/e1.pdf' })).toBe(true);
  });

  it('downloadExamPdf fetches the PDF and triggers a browser download', async () => {
    await render();
    const exam = { ...component.course()!.exams[0], generatedPdfPath: 'exams/e1.pdf' };
    const clickSpy = vi.fn();
    const anchor = { click: clickSpy, href: '', download: '' } as unknown as HTMLAnchorElement;
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement')
      .mockImplementation((tag: string) => (tag === 'a' ? anchor : realCreateElement(tag)));

    component.downloadExamPdf(exam);

    expect(mockExamService.downloadExamPdf).toHaveBeenCalledWith(exam.id);
    expect(anchor.download).toBe(`${exam.name}.pdf`);
    expect(clickSpy).toHaveBeenCalled();
    expect(component.isDownloadingExamPdf()).toBe(false);
    createElementSpy.mockRestore();
  });

  // downloadResults (results CSV export -- UR2.29; backend enforces the same
  // ownership gate as release via services/exam.py's _authorize_release)

  it('downloadResults fetches the CSV and triggers a browser download', async () => {
    await render();
    const exam = component.course()!.exams[0];
    const clickSpy = vi.fn();
    const anchor = { click: clickSpy, href: '', download: '' } as unknown as HTMLAnchorElement;
    const realCreateElement = document.createElement.bind(document);
    const createElementSpy = vi.spyOn(document, 'createElement')
      .mockImplementation((tag: string) => (tag === 'a' ? anchor : realCreateElement(tag)));

    component.downloadResults(exam);

    expect(mockExamService.exportExamResults).toHaveBeenCalledWith(exam.id);
    expect(anchor.download).toMatch(/-results\.csv$/);
    expect(clickSpy).toHaveBeenCalled();
    expect(component.exportingExamId()).toBeNull();
    expect(component.exportErrorExamId()).toBeNull();
    createElementSpy.mockRestore();
  });

  it('downloadResults tracks the exporting exam and surfaces an inline error per exam', async () => {
    await render();
    mockExamService.exportExamResults.mockReturnValueOnce(throwError(() => ({ status: 500 })));
    const exam = component.course()!.exams[0];

    component.downloadResults(exam);

    expect(component.exportErrorExamId()).toBe(exam.id);
    expect(component.exportingExamId()).toBeNull();
  });

  it('goBack navigates to the courses list', async () => {
    await render();
    component.goBack();
    expect(routerMock.navigate).toHaveBeenCalledWith(['/courses']);
  });

  // Delete course

  it('confirmDelete opens the delete confirmation for the loaded course', async () => {
    await render();
    component.confirmDelete();
    expect(component.deletingCourse()).toBe(component.course());
  });

  it('onCourseArchived closes the modal and navigates back to the course list', async () => {
    await render();
    component.confirmDelete();
    component.onCourseArchived();
    expect(component.deletingCourse()).toBeNull();
    expect(routerMock.navigate).toHaveBeenCalledWith(['/courses']);
  });

  // Exam delete

  it('confirmExamDelete opens the exam delete confirmation', async () => {
    await render();
    const exam = component.course()!.exams[0];

    component.confirmExamDelete(exam);

    expect(component.deletingExam()).toBe(exam);
  });

  it('executeExamDelete deletes the exam and removes it from the course', async () => {
    await render();
    const exam = component.course()!.exams[0];
    component.confirmExamDelete(exam);

    component.executeExamDelete();

    expect(mockExamService.deleteExam).toHaveBeenCalledWith(exam.id);
    expect(component.course()!.exams.some(e => e.id === exam.id)).toBe(false);
    expect(component.deletingExam()).toBeNull();
  });

  it('executeExamDelete keeps the confirmation open when deletion fails', async () => {
    mockExamService.deleteExam.mockReturnValueOnce(throwError(() => new Error('network')));
    await render();
    const exam = component.course()!.exams[0];
    component.confirmExamDelete(exam);

    component.executeExamDelete();

    expect(component.deletingExam()).toBe(exam);
    expect(component.isDeletingExam()).toBe(false);
  });

  // Answer key / template gating

  it('canDefineAnswerKey is true for the exam creator', async () => {
    await render();
    mockUserService.currentUser.mockReturnValueOnce({ id: 'u1' } as never);
    const exam = { ...mkExam('e9', 'Owned', ExamStatus.UnGraded, 'c1'), created_by: 'u1' };
    expect(component.canDefineAnswerKey(exam)).toBe(true);
  });

  it('canDefineAnswerKey is false for a non-creator', async () => {
    await render();
    mockUserService.currentUser.mockReturnValueOnce({ id: 'u2' } as never);
    const exam = { ...mkExam('e9', 'NotOwned', ExamStatus.UnGraded, 'c1'), created_by: 'u1' };
    expect(component.canDefineAnswerKey(exam)).toBe(false);
  });

  it('openAssignTemplate loads available templates and selects the first one', async () => {
    await render();
    const exam = { ...mkExam('e10', 'Detached', ExamStatus.UnGraded, 'c1'), templateMissing: true };

    component.openAssignTemplate(exam);

    expect(mockTemplateService.listMyTemplates).toHaveBeenCalled();
    expect(component.assigningTemplateExam()).toBe(exam);
    expect(component.templateOptions()).toEqual([MOCK_TEMPLATE]);
    expect(component.selectedTemplateId()).toBe(MOCK_TEMPLATE.id);
  });

  it('assignTemplate patches the exam template and refreshes the course', async () => {
    await render();
    const exam = {
      ...mkExam('e10', 'Detached', ExamStatus.UnGraded, 'c1'),
      hasAnswerKey: false,
      templateMissing: true,
    };
    component.assigningTemplateExam.set(exam);
    component.selectedTemplateId.set(MOCK_TEMPLATE.id);

    component.assignTemplate();

    expect(mockExamService.updateExamTemplate).toHaveBeenCalledWith('e10', MOCK_TEMPLATE.id, false);
    expect(component.assigningTemplateExam()).toBeNull();
  });

  it('opens exam-wide statistics as a page instead of a modal', async () => {
    await render();
    const exam = component.course()!.exams[0];

    component.openExamStats(exam);

    expect(component.viewingStatsExam()).toBe(exam);
  });

  it('closeResults clears the viewed exam', async () => {
    await render();
    component.openExamStats(component.course()!.exams[0]);

    component.closeResults();

    expect(component.viewingStatsExam()).toBeNull();
  });

  // Exam row overflow menu

  it('toggleExamMenu opens and closes the menu for a given exam', async () => {
    await render();
    expect(component.openMenuExamId()).toBeNull();
    component.toggleExamMenu('e1');
    expect(component.openMenuExamId()).toBe('e1');
    component.toggleExamMenu('e1');
    expect(component.openMenuExamId()).toBeNull();
  });

  it('toggleExamMenu switches to a different exam\'s menu', async () => {
    await render();
    component.toggleExamMenu('e1');
    component.toggleExamMenu('e2');
    expect(component.openMenuExamId()).toBe('e2');
  });

  it('closeExamMenu clears the open exam id', async () => {
    await render();
    component.toggleExamMenu('e1');

    component.closeExamMenu();

    expect(component.openMenuExamId()).toBeNull();
  });

  it('renders the overflow menu outside the list clipping boundary without a backdrop', async () => {
    await render();
    const trigger = fixture.debugElement.query(By.css('[title="More actions"]')).nativeElement;
    vi.spyOn(trigger, 'getBoundingClientRect').mockReturnValue({
      top: 60,
      right: 900,
      bottom: 100,
      left: 860,
      width: 40,
      height: 40,
      x: 860,
      y: 60,
      toJSON: () => ({}),
    });
    trigger.click();
    await fixture.whenStable();
    fixture.detectChanges();

    expect(fixture.debugElement.query(By.css('.exam-menu-wrapper .menu-backdrop'))).toBeNull();
    const menu = fixture.debugElement.query(By.css('.exam-menu-wrapper > .exam-menu')).nativeElement;
    const examList = fixture.debugElement.query(By.css('.exams-list')).nativeElement;
    expect(getComputedStyle(menu).position).toBe('fixed');
    expect(menu.style.top).toBe('104px');
    expect(menu.style.right).toBe(`${window.innerWidth - 900}px`);
    expect(getComputedStyle(examList).overflowY).toBe('auto');
  });

  it('keeps the overflow menu attached to its exam row while an ancestor scrolls', async () => {
    await render();
    const trigger = fixture.debugElement.query(By.css('[title="More actions"]')).nativeElement;
    let bottom = 180;
    vi.spyOn(trigger, 'getBoundingClientRect').mockImplementation(() => ({
      top: bottom - 40,
      right: 900,
      bottom,
      left: 860,
      width: 40,
      height: 40,
      x: 860,
      y: bottom - 40,
      toJSON: () => ({}),
    }));
    trigger.click();
    await fixture.whenStable();
    fixture.detectChanges();

    bottom = 80;
    fixture.debugElement.query(By.css('.exams-list')).nativeElement.dispatchEvent(new Event('scroll'));
    await fixture.whenStable();

    const menu = fixture.debugElement.query(By.css('.exam-menu-wrapper > .exam-menu')).nativeElement;
    expect(component.openMenuExamId()).toBe('e1');
    expect(menu.style.top).toBe('84px');
  });

  // Upload Scans (hidden once results are released)

  it('canUploadScans is false once the exam is released', async () => {
    await render();
    const exam = component.course()!.exams[0];
    expect(component.canUploadScans({ ...exam, released: false })).toBe(true);
    expect(component.canUploadScans({ ...exam, released: true })).toBe(false);
    expect(component.canUploadScans({ ...exam, answerKeysComplete: false })).toBe(false);
  });

  it('disables the Upload button once released and enables it again once unreleased', async () => {
    mockUserService.isAdmin.mockReturnValue(true);
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e1', 'Midterm', 'c1', true), released: true },
    ]));
    await render();

    let uploadAction = fixture.debugElement.query(By.css('[title="Unrelease results before uploading more scans"]'));
    expect(uploadAction).toBeTruthy();
    expect(uploadAction.query(By.css('button')).nativeElement.disabled).toBe(true);

    const exam = component.course()!.exams[0];
    component.closeExam(exam);
    fixture.detectChanges();

    uploadAction = fixture.debugElement.query(By.css('[title="Upload student scans for grading"]'));
    expect(uploadAction).toBeTruthy();
    expect(uploadAction.query(By.css('button')).nativeElement.disabled).toBe(false);
  });

  it('explains why scan upload is unavailable', () => {
    const exam = mkExam('e1', 'Midterm', ExamStatus.UnGraded, 'c1');

    expect(component.scanUploadTitle({ ...exam, templateMissing: true })).toBe('Assign a template before uploading scans');
    expect(component.scanUploadTitle({ ...exam, hasAnswerKey: false })).toBe('Define the answer key before uploading scans');
    expect(component.scanUploadTitle({ ...exam, answerKeysComplete: false })).toBe('Complete every answer key version before uploading scans');
    expect(component.scanUploadTitle({ ...exam, templateRegistered: false })).toBe('Prepare the template for scanning');
  });

  // Release / unrelease

  it('shows the Release button only once an exam is graded', async () => {
    mockUserService.isAdmin.mockReturnValue(true);
    mockExamService.listExamsByCourse.mockReturnValue(of([
      mkApiExam('e1', 'Midterm', 'c1', true),
      mkApiExam('e2', 'Final', 'c1', false),
    ]));
    await render();

    const releaseButtons = fixture.debugElement.queryAll(By.css('[title="Publish grades so students can see them"]'));
    expect(releaseButtons.length).toBe(1);
  });

  it('labels an exam with no scans as Not Graded', async () => {
    mockUserService.isAdmin.mockReturnValue(true);
    mockExamService.listExamsByCourse.mockReturnValue(of([
      mkApiExam('e1', 'Midterm', 'c1', false),
    ]));
    await render();

    expect(fixture.debugElement.query(By.css('.exam-title-row .status-badge')).nativeElement.textContent)
      .toContain('Not Graded');
  });

  it('shows the Unrelease button on a released exam regardless of the Release gate', async () => {
    mockUserService.isAdmin.mockReturnValue(true);
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e1', 'Midterm', 'c1', true), released: true },
    ]));
    await render();

    const button = fixture.debugElement.query(By.css('[title="Unrelease results and hide grades from students"]'));
    expect(button).toBeTruthy();
    expect(button.nativeElement.textContent).toContain('Unrelease');
    expect(fixture.debugElement.query(By.css('[title="Publish grades so students can see them"]'))).toBeNull();
  });

  it('clicking Release only asks for confirmation, without releasing yet', async () => {
    await render();
    const exam = component.course()!.exams[0];
    component.confirmExamRelease(exam);
    expect(component.confirmingReleaseExam()).toBe(exam);
    expect(mockExamService.releaseExam).not.toHaveBeenCalled();
  });

  it('cancelling the release confirmation does not release the exam', async () => {
    await render();
    const exam = component.course()!.exams[0];
    component.confirmExamRelease(exam);
    component.cancelExamRelease();
    expect(component.confirmingReleaseExam()).toBeNull();
    expect(mockExamService.releaseExam).not.toHaveBeenCalled();
  });

  it('confirming release marks the exam released on success', async () => {
    await render();
    const exam = component.course()!.exams[0];
    expect(exam.released).toBe(false);
    component.confirmExamRelease(exam);
    component.executeExamRelease();
    expect(mockExamService.releaseExam).toHaveBeenCalledWith(exam.id);
    expect(component.course()!.exams.find(e => e.id === exam.id)!.released).toBe(true);
    expect(component.releaseNotice()).toContain('visible to students');
  });

  it('closeExam marks the exam not released on success', async () => {
    await render();
    const exam = { ...component.course()!.exams[0], released: true };
    component.course.set({ ...component.course()!, exams: component.course()!.exams.map(e => e.id === exam.id ? exam : e) });
    component.closeExam(exam);
    expect(mockExamService.closeExam).toHaveBeenCalledWith(exam.id);
    expect(component.course()!.exams.find(e => e.id === exam.id)!.released).toBe(false);
  });

  // Deep-linking from a notification (redirected here as "/courses/c1?examId=e1&action=upload")

  it('navigates staff to the annotated results view when deep-linked without an action param', async () => {
    await render();
    (component as any).route.snapshot.queryParamMap.get = (key: string) => (key === 'examId' ? 'e1' : null);
    (component as any).openExamFromQueryParams((component as any).route.snapshot.queryParamMap);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/grades', 'grade-1', 'annotations']);
  });

  it('sends a student to their own results view when deep-linked without an action param', async () => {
    mockUserService.isStudent.mockReturnValue(true);
    await render();
    (component as any).route.snapshot.queryParamMap.get = (key: string) => (key === 'examId' ? 'e1' : null);
    (component as any).openExamFromQueryParams((component as any).route.snapshot.queryParamMap);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/grades', 'grade-1', 'results']);
  });

  it('opens the upload modal instead of navigating when deep-linked with action=upload', async () => {
    await render();
    (component as any).route.snapshot.queryParamMap.get = (key: string) =>
      ({ examId: 'e1', action: 'upload' } as Record<string, string>)[key] ?? null;
    (component as any).openExamFromQueryParams((component as any).route.snapshot.queryParamMap);
    expect(component.uploadingScansForExam()).toBe(component.course()!.exams[0]);
    expect(routerMock.navigate).not.toHaveBeenCalled();
  });

  // Live reactivity: notifications and route changes

  it('refreshes the course when a processing notification arrives for the open course', async () => {
    await render();
    const callsBefore = mockCourseService.getCourse.mock.calls.length;

    notificationsSubject.next({
      id: 'n1',
      type: 'Processing',
      severity: 'info',
      title: 'Your exam has been graded',
      course: 'COSC 304',
      courseId: 'c1',
      subtitle: '',
      time: '',
      createdAt: '2026-07-26T00:00:00Z',
      isRead: false,
      linkPath: null,
      linkQuery: null,
    });

    expect(mockCourseService.getCourse.mock.calls.length).toBe(callsBefore + 1);
  });

  it('ignores a processing notification for a different course', async () => {
    await render();
    const callsBefore = mockCourseService.getCourse.mock.calls.length;

    notificationsSubject.next({
      id: 'n2',
      type: 'Processing',
      severity: 'info',
      title: 'Your exam has been graded',
      course: 'COSC 101',
      courseId: 'other-course',
      subtitle: '',
      time: '',
      createdAt: '2026-07-26T00:00:00Z',
      isRead: false,
      linkPath: null,
      linkQuery: null,
    });

    expect(mockCourseService.getCourse.mock.calls.length).toBe(callsBefore);
  });

  it('ignores a re-grade notification even for the open course', async () => {
    await render();
    const callsBefore = mockCourseService.getCourse.mock.calls.length;

    notificationsSubject.next({
      id: 'n3',
      type: 'Re-grade',
      severity: 'info',
      title: 'New re-grade request',
      course: 'COSC 304',
      courseId: 'c1',
      subtitle: '',
      time: '',
      createdAt: '2026-07-26T00:00:00Z',
      isRead: false,
      linkPath: null,
      linkQuery: null,
    });

    expect(mockCourseService.getCourse.mock.calls.length).toBe(callsBefore);
  });

  it('reloads when the route id changes, even while this component instance is reused', async () => {
    await render();
    expect(mockCourseService.getCourse).toHaveBeenCalledWith('c1');

    paramMapSubject.next(mkParamMap({ id: 'c2' }));

    expect(component.courseId()).toBe('c2');
    expect(mockCourseService.getCourse).toHaveBeenCalledWith('c2');
  });

  // Students section

  it('renders the student list inline, embedded (no close button)', async () => {
    await render();
    expect(fixture.debugElement.query(By.css('app-student-list'))).toBeTruthy();
  });

  it('onStudentRemoved decrements the student count', async () => {
    await render();
    component.course.set({ ...component.course()!, students: 2, studentList: [...MOCK_STUDENTS] });

    component.onStudentRemoved(MOCK_STUDENTS[0]);

    expect(component.course()!.students).toBe(1);
    expect(component.course()!.studentList.map(s => s.id)).toEqual(['s2']);
  });

  it('onStudentPromoted removes the promoted student from the roster like onStudentRemoved', async () => {
    await render();
    component.course.set({ ...component.course()!, students: 2, studentList: [...MOCK_STUDENTS] });

    component.onStudentPromoted(MOCK_STUDENTS[0]);

    expect(component.course()!.students).toBe(1);
    expect(component.course()!.studentList.map(s => s.id)).toEqual(['s2']);
  });

  it('isCourseOwner is true when the current user created the course', async () => {
    await render();
    component.courseOwnerId.set('u1');
    mockUserService.currentUser.mockReturnValueOnce({ id: 'u1' } as never);
    expect(component.isCourseOwner).toBe(true);
  });

  it('isCourseOwner is false for a signed-in professor who is not the course owner', async () => {
    await render();
    component.courseOwnerId.set('u1');
    mockUserService.currentUser.mockReturnValueOnce({ id: 'u2' } as never);
    expect(component.isCourseOwner).toBe(false);
  });

  it('isCourseOwner is true for an admin regardless of who created the course', async () => {
    await render();
    component.courseOwnerId.set('u1');
    mockUserService.currentUser.mockReturnValueOnce({ id: 'u2' } as never);
    mockUserService.isAdmin.mockReturnValueOnce(true);
    expect(component.isCourseOwner).toBe(true);
  });

  // Exam creation wizard

  it('startCreatingExam opens the wizard at step 1 in the requested mode', async () => {
    await render();
    component.startCreatingExam('canvas');
    expect(component.examWizardStep()).toBe(1);
    expect(component.examWizardMode()).toBe('canvas');
    expect(component.examWizardExam()).toBeNull();
    expect(component.showAddExamMenu()).toBe(false);
  });

  it('renders the create-exam step with the wizardStep input set', async () => {
    component.startCreatingExam('omr');
    await render();

    const createExam = fixture.debugElement.query(By.css('app-create-exam'));
    expect(createExam).toBeTruthy();
    expect(createExam.componentInstance.wizardStep).toBe(1);
  });

  it('onWizardExamCreated adds the exam to the course and advances to step 2', async () => {
    await render();
    component.startCreatingExam('omr');
    const created = mkApiExam('e3', 'Quiz', 'c1', false);

    component.onWizardExamCreated(created);

    expect(component.course()!.exams.some(e => e.id === 'e3')).toBe(true);
    expect(component.examWizardExam()?.id).toBe('e3');
    expect(component.examWizardStep()).toBe(2);
  });

  it('renders the answer-key step with the wizardStep input once an exam exists', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));
    fixture.detectChanges();

    const answerKey = fixture.debugElement.query(By.css('app-answer-key'));
    expect(answerKey).toBeTruthy();
    expect(answerKey.componentInstance.wizardStep).toBe(2);
    expect(answerKey.componentInstance.examId).toBe('e3');
  });

  it('advancing past the answer-key step moves to the scan-upload step', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));

    component.examWizardStep.set(3);
    fixture.detectChanges();

    const scanUpload = fixture.debugElement.query(By.css('app-scan-upload-modal'));
    expect(scanUpload).toBeTruthy();
    expect(scanUpload.componentInstance.wizardStep).toBe(3);
    expect(scanUpload.componentInstance.exam.id).toBe('e3');
  });

  it('requestCloseExamWizard closes immediately from step 1', async () => {
    await render();
    component.startCreatingExam('omr');

    component.requestCloseExamWizard();

    expect(component.examWizardStep()).toBe(0);
    expect(component.confirmingExamWizardExit()).toBe(false);
  });

  it('requestCloseExamWizard warns before exiting step 2 without an answer key', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated({ ...mkApiExam('e3', 'Quiz', 'c1', false), has_answer_key: false });

    component.requestCloseExamWizard();

    expect(component.confirmingExamWizardExit()).toBe(true);
    expect(component.examWizardStep()).toBe(2);
  });

  it('requestCloseExamWizard closes step 2 straight away once the answer key is set', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated({ ...mkApiExam('e3', 'Quiz', 'c1', false), has_answer_key: true });

    component.requestCloseExamWizard();

    expect(component.confirmingExamWizardExit()).toBe(false);
    expect(component.examWizardStep()).toBe(0);
  });

  it('requestCloseExamWizard warns before exiting step 3 without any scans', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));
    component.examWizardStep.set(3);

    component.requestCloseExamWizard();

    expect(component.confirmingExamWizardExit()).toBe(true);
    expect(component.examWizardStep()).toBe(3);
  });

  it('requestCloseExamWizard closes step 3 straight away once scans have been uploaded', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));
    component.examWizardStep.set(3);
    // The live course.exams copy is what gating reads, not examWizardExam
    // itself, since only the former gets refreshed as the wizard progresses.
    component.course.set({
      ...component.course()!,
      exams: component.course()!.exams.map(e => e.id === 'e3' ? { ...e, total: 5 } : e),
    });

    component.requestCloseExamWizard();

    expect(component.confirmingExamWizardExit()).toBe(false);
    expect(component.examWizardStep()).toBe(0);
  });

  it('requestCloseExamWizard reads the live exam from course.exams, not the stale wizard snapshot', async () => {
    // Regression test: examWizardExam is a snapshot taken at creation time
    // and is never mutated directly by the answer-key/scan-upload steps --
    // only course.exams gets refreshed (via onWizardExamCreated's reload or
    // onScanUploaded). Exiting right after finishing a step must judge
    // progress against that live copy, not the stale snapshot.
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated({ ...mkApiExam('e3', 'Quiz', 'c1', false), has_answer_key: false });
    component.examWizardStep.set(3);
    component.course.set({
      ...component.course()!,
      exams: component.course()!.exams.map(e => e.id === 'e3' ? { ...e, hasAnswerKey: true, total: 5 } : e),
    });
    // examWizardExam itself was never updated -- still reflects the stale snapshot.
    expect(component.examWizardExam()?.hasAnswerKey).toBe(false);
    expect(component.examWizardExam()?.total).toBe(0);

    component.requestCloseExamWizard();

    expect(component.confirmingExamWizardExit()).toBe(false);
    expect(component.examWizardStep()).toBe(0);
  });

  it('onScanUploaded refreshes the course even when the upload is still pending processing', async () => {
    // Regression test: total_scans (exam.total) is incremented as soon as a
    // scan is uploaded, well before it's graded. Gating the refresh on
    // scan.status === 'completed' left the wizard's exit check judging a
    // just-finished upload step against stale pre-upload data.
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));
    component.examWizardStep.set(3);
    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e3', 'Quiz', 'c1', false), total_scans: 1 },
    ]));

    component.onScanUploaded([{ id: 'scan-1', status: 'pending' } as never]);

    expect(component.examWizardExamLive()?.total).toBe(1);
  });

  it('onScanUploaded starts polling job status for the still-pending seed scan', async () => {
    await render();

    component.onScanUploaded([{ id: 'scan-1', status: 'pending' } as never]);

    expect(mockScanService.getJobStatus).toHaveBeenCalledWith('scan-1');
  });

  it('onScanUploaded does not poll job status once every scan in the batch has already materialized', async () => {
    await render();

    component.onScanUploaded([{ id: 'scan-1', status: 'completed' } as never]);

    expect(mockScanService.getJobStatus).not.toHaveBeenCalled();
  });

  it('onScanUploaded updates activeJobStatus from the polled job status', async () => {
    mockScanService.getJobStatus.mockReturnValue(
      of({ progress: 0.25, finished: false, success: null, notes: 'rendering 8 pages' }),
    );
    await render();

    component.onScanUploaded([{ id: 'scan-1', status: 'pending' } as never]);

    expect(component.activeJobStatus()).toEqual({
      progress: 0.25,
      finished: false,
      success: null,
      notes: 'rendering 8 pages',
    });
  });

  it('onScanUploaded restarts the job-status poll for a newly-uploaded batch', async () => {
    await render();

    component.onScanUploaded([{ id: 'scan-1', status: 'pending' } as never]);
    mockScanService.getJobStatus.mockClear();
    component.onScanUploaded([{ id: 'scan-2', status: 'pending' } as never]);

    // The previous poll is torn down rather than left running alongside the
    // new one -- only the latest upload's scan id should be queried.
    expect(mockScanService.getJobStatus).toHaveBeenCalledTimes(1);
    expect(mockScanService.getJobStatus).toHaveBeenCalledWith('scan-2');
  });

  it('cancelExamWizardExit keeps the wizard open and only hides the confirmation', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated({ ...mkApiExam('e3', 'Quiz', 'c1', false), has_answer_key: false });
    component.requestCloseExamWizard();

    component.cancelExamWizardExit();

    expect(component.confirmingExamWizardExit()).toBe(false);
    expect(component.examWizardStep()).toBe(2);
    expect(component.examWizardExam()?.id).toBe('e3');
  });

  it('closeExamWizard resets the wizard to its initial state', async () => {
    await render();
    component.startCreatingExam('canvas');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));
    component.confirmingExamWizardExit.set(true);

    component.closeExamWizard();

    expect(component.examWizardStep()).toBe(0);
    expect(component.examWizardExam()).toBeNull();
    expect(component.examWizardMode()).toBe('omr');
    expect(component.confirmingExamWizardExit()).toBe(false);
  });

  it('keeps the wizard exam reference in sync when the course reloads', async () => {
    await render();
    component.startCreatingExam('omr');
    component.onWizardExamCreated(mkApiExam('e3', 'Quiz', 'c1', false));

    mockExamService.listExamsByCourse.mockReturnValue(of([
      { ...mkApiExam('e3', 'Quiz', 'c1', false), has_answer_key: true },
    ]));
    component.refreshCourse();

    expect(component.examWizardExam()?.hasAnswerKey).toBe(true);
  });
});

describe('apiExamToExam ambiguous grade handling', () => {
  const baseApiExam = mkApiExam('e1', 'Midterm', 'c1', true);

  it('maps ambiguous_grade_count to ambiguousCount', () => {
    const exam = apiExamToExam({ ...baseApiExam, ambiguous_grade_count: 3 });
    expect(exam.ambiguousCount).toBe(3);
  });

  it('defaults ambiguousCount to 0 when the field is absent', () => {
    const exam = apiExamToExam(baseApiExam);
    expect(exam.ambiguousCount).toBe(0);
  });

  it('reports ReviewRequired instead of Graded once a fully-graded exam has ambiguous grades', () => {
    const exam = apiExamToExam({ ...baseApiExam, ambiguous_grade_count: 1 });
    expect(exam.status).toBe(ExamStatus.ReviewRequired);
  });

  it('still reports Graded when a fully-graded exam has no ambiguous grades', () => {
    const exam = apiExamToExam(baseApiExam);
    expect(exam.status).toBe(ExamStatus.Graded);
  });
});
