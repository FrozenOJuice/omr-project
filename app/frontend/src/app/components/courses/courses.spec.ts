import { ComponentFixture, TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { ActivatedRoute, Router } from '@angular/router';
import { vi } from 'vitest';
import { of } from 'rxjs';
import { Courses } from './courses';
import { CourseService } from '../../services/course.service';
import { ExamService } from '../../services/exam.service';
import { CanvasService } from '../../services/canvas.service';
import { UserService } from '../../services/user.service';
import { ExamStatus } from '../../enums/tags.enum';
import { ApiCourse, Course } from '../../models/course.model';
import { Exam } from '../../models/exam.model';
import { AcademicTerm } from '../../models/academic-term.model';

const summerTerm: AcademicTerm = {
  id: 'summer-1', institution: 'ubc', code: 'summer-session-1',
  name: 'Summer Session 1', term_type: 'preset', year_format: 'following_year',
  is_active: true, created_by: null, created_at: '', updated_at: '',
};

const winterTerm: AcademicTerm = {
  ...summerTerm, id: 'winter-1', code: 'winter-session-1',
  name: 'Winter Session 1', year_format: 'academic_year_range',
};

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

const MOCK_COURSES: Course[] = [
  {
    id: 'c1',
    code: 'COSC 304',
    name: 'Database Systems',
    students: 5,
    studentList: [],
    academicTerm: summerTerm,
    academicYearStart: 2026,
    archivedAt: null,
    source: 'omr',
    canvasLink: null,
    canManageCanvas: false,
    exams: [
      mkExam('e1', 'Midterm', ExamStatus.Graded, 'c1'),
      mkExam('e2', 'Final', ExamStatus.UnGraded, 'c1'),
    ],
    inviteLink: 'link-c1',
  },
  {
    id: 'c2',
    code: 'COSC 499',
    name: 'Software Engineering Capstone',
    students: 5,
    studentList: [],
    academicTerm: winterTerm,
    academicYearStart: 2026,
    archivedAt: null,
    source: 'omr',
    canvasLink: null,
    canManageCanvas: false,
    exams: [
      mkExam('e3', 'Project', ExamStatus.UnGraded, 'c2'),
    ],
    inviteLink: 'link-c2',
  },
];

describe('Courses', () => {
  let component: Courses;
  let fixture: ComponentFixture<Courses>;
  let routerMock: { navigate: ReturnType<typeof vi.fn> };

  const mockCourseService = {
    listCourses: vi.fn(() => of([])),
    restoreCourse: vi.fn(() => of({})),
    cleanupArchivedCourses: vi.fn(() => of({ scanned_images: 0, exam_records: 0 })),
  };
  const mockExamService = {
    listExamsByCourse: vi.fn(() => of([])),
  };
  const mockCanvasService = {
    getCapabilities: vi.fn(() => of({ configured: true, instructor_only: true })),
    getConnection: vi.fn(() => of({ connected: false })),
  };
  const mockUserService = {
    isProfessorOrAbove: vi.fn(() => true),
    isStudent: vi.fn(() => false),
    isAdmin: vi.fn(() => false),
    currentUser: vi.fn(() => null),
    role: vi.fn(() => null),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockCourseService.listCourses.mockReturnValue(of([]));
    mockCourseService.restoreCourse.mockReturnValue(of({}));
    mockCourseService.cleanupArchivedCourses.mockReturnValue(of({ scanned_images: 0, exam_records: 0 }));
    mockExamService.listExamsByCourse.mockReturnValue(of([]));
    mockUserService.isProfessorOrAbove.mockReturnValue(true);
    mockUserService.isStudent.mockReturnValue(false);
    mockUserService.isAdmin.mockReturnValue(false);
    mockUserService.currentUser.mockReturnValue(null);
    mockUserService.role.mockReturnValue(null);
    mockCanvasService.getCapabilities.mockReturnValue(of({ configured: true, instructor_only: true }));
    mockCanvasService.getConnection.mockReturnValue(of({ connected: false }));

    routerMock = { navigate: vi.fn() };

    await TestBed.configureTestingModule({
      imports: [Courses],
      providers: [
        { provide: CourseService, useValue: mockCourseService },
        { provide: ExamService, useValue: mockExamService },
        { provide: CanvasService, useValue: mockCanvasService },
        { provide: UserService, useValue: mockUserService },
        {
          provide: ActivatedRoute,
          useValue: { snapshot: { queryParamMap: { get: () => null, has: () => false } } },
        },
        { provide: Router, useValue: routerMock },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Courses);
    component = fixture.componentInstance;
    // Pre-populate courses so data-driven tests work without a real HTTP backend.
    component.courses = MOCK_COURSES.map(c => ({ ...c, exams: [...c.exams] }));
    vi.spyOn(component, 'loadCourses').mockImplementation(() => {});
  });

  const render = () => fixture.detectChanges();

  it('should create', () => {
    render();
    expect(component).toBeTruthy();
  });

  it('should initialise with an empty searchQuery', () => {
    expect(component.searchQuery).toBe('');
  });

  it('should initialise with an empty selectedTerm', () => {
    expect(component.selectedTerm).toBe('');
  });

  it('keeps the imported Canvas roster count', () => {
    component.courses = [];
    component.onCoursesImported({
      complete: true,
      courses: [{
        id: 'canvas-course',
        name: 'COSC 499 - Capstone',
        academic_term_id: winterTerm.id,
        academic_term: winterTerm,
        academic_year_start: 2026,
        archived_at: null,
        created_by: 'professor',
        created_at: '2026-07-20T00:00:00Z',
        updated_at: '2026-07-20T00:00:00Z',
        invite_link: 'invite',
        student_count: 37,
        source: 'canvas',
        canvas_link: null,
        can_manage_canvas: true,
      } satisfies ApiCourse],
    });

    expect(component.courses[0].students).toBe(37);
  });

  // terms getter

  it('should return unique terms', () => {
    const terms = component.terms;
    expect(terms.length).toBe(new Set(terms).size);
  });

  it('should return terms in sorted order', () => {
    const terms = component.terms;
    expect(terms).toEqual([...terms].sort());
  });

  // filteredCourses getter

  it('should return all courses when search and term filter are empty', () => {
    expect(component.filteredCourses.length).toBe(component.courses.length);
  });

  it('should filter by course code (case-insensitive)', () => {
    component.searchQuery = 'cosc 304';
    const results = component.filteredCourses;
    expect(results.length).toBe(1);
    expect(results[0].code).toBe('COSC 304');
  });

  it('should filter by course name (case-insensitive)', () => {
    component.searchQuery = 'database';
    const results = component.filteredCourses;
    expect(results.length).toBe(1);
    expect(results[0].name).toContain('Database');
  });

  it('should return empty array when search matches nothing', () => {
    component.searchQuery = 'zzznomatch';
    expect(component.filteredCourses.length).toBe(0);
  });

  it('should filter by selectedTerm', () => {
    const term = component.courses[0].academicTerm.name;
    component.selectedTerm = term;
    component.filteredCourses.forEach(c => expect(c.academicTerm.name).toBe(term));
  });

  it('should trim whitespace from searchQuery before filtering', () => {
    component.searchQuery = '  cosc 304  ';
    expect(component.filteredCourses.length).toBe(1);
  });

  // navigation

  it('openCourse navigates to the course detail route', () => {
    component.openCourse(component.courses[0]);
    expect(routerMock.navigate).toHaveBeenCalledWith(['/courses', 'c1']);
  });

  it('shows an explanation instead of restoring a course whose retention has been processed', () => {
    const processedCourse = {
      ...component.courses[0],
      archivedAt: '2025-01-01T00:00:00Z',
      retentionProcessedAt: '2026-01-01T00:00:00Z',
    };

    component.promptRestore(processedCourse);

    expect(component.restoreUnavailableCourse).toBe(processedCourse);
    expect(component.confirmingRestoreCourse).toBeNull();
    expect(mockCourseService.restoreCourse).not.toHaveBeenCalled();
  });

  it('renders the non-restorable course explanation modal', () => {
    component.restoreUnavailableCourse = {
      ...component.courses[0],
      archivedAt: '2025-01-01T00:00:00Z',
      retentionProcessedAt: '2026-01-01T00:00:00Z',
    };
    render();

    expect(fixture.nativeElement.textContent).toContain('Course can no longer be restored');
  });

  it('shows archive cleanup controls to admins', () => {
    mockUserService.isAdmin.mockReturnValue(true);
    render();
    expect(fixture.nativeElement.textContent).toContain('Clean up archives');
  });

  it('hides archive cleanup controls from non-admin staff', () => {
    render();
    expect(fixture.nativeElement.textContent).not.toContain('Clean up archives');
  });

  it('runs archive cleanup after confirmation and reports the result', () => {
    mockUserService.isAdmin.mockReturnValue(true);
    mockCourseService.cleanupArchivedCourses.mockReturnValue(of({
      scanned_images: 2,
      exam_records: 1,
    }));

    component.showArchiveCleanupConfirmation = true;
    component.cleanupArchives();

    expect(mockCourseService.cleanupArchivedCourses).toHaveBeenCalledOnce();
    expect(component.showArchiveCleanupConfirmation).toBe(false);
    expect(component.archiveCleanupNotice).toContain('2 scan-image set(s)');
    expect(component.archiveCleanupNotice).toContain('1 student-record set(s)');
  });

  it('marks processed archives and does not render an unarchive button', () => {
    component.archiveFilter = 'archived';
    component.courses = [{
      ...component.courses[0],
      archivedAt: '2025-01-01T00:00:00Z',
      retentionProcessedAt: '2026-01-01T00:00:00Z',
    }];
    render();

    expect(fixture.nativeElement.textContent).toContain('Retention processed');
    const tooltip = fixture.debugElement.query(By.css('.app-tooltip__content'));
    expect(tooltip.nativeElement.textContent).toContain('permanently condensed');
    expect(tooltip.nativeElement.textContent).toContain('can no longer be restored');
    expect(fixture.debugElement.query(By.css('.course-actions'))).toBeNull();
  });

  it('clicking a course header navigates to its detail page', () => {
    render();
    const header = fixture.debugElement.query(By.css('.course-header'));
    header.nativeElement.click();
    expect(routerMock.navigate).toHaveBeenCalledWith(['/courses', component.courses[0].id]);
  });

  // Deep-link redirect shim

  it('redirects to the course detail route when a legacy courseId query param is present', async () => {
    const route = { snapshot: { queryParamMap: {
      get: (key: string) => ({ courseId: 'c1', examId: 'e1', action: 'upload' } as Record<string, string>)[key] ?? null,
    } } };
    await TestBed.resetTestingModule();
    const nav = { navigate: vi.fn() };
    await TestBed.configureTestingModule({
      imports: [Courses],
      providers: [
        { provide: CourseService, useValue: mockCourseService },
        { provide: ExamService, useValue: mockExamService },
        { provide: CanvasService, useValue: mockCanvasService },
        { provide: UserService, useValue: mockUserService },
        { provide: ActivatedRoute, useValue: route },
        { provide: Router, useValue: nav },
      ],
    }).compileComponents();
    const f = TestBed.createComponent(Courses);
    const c = f.componentInstance;
    const loadSpy = vi.spyOn(c, 'loadCourses').mockImplementation(() => {});

    c.ngOnInit();

    expect(nav.navigate).toHaveBeenCalledWith(['/courses', 'c1'], {
      queryParams: { examId: 'e1', action: 'upload' },
      replaceUrl: true,
    });
    expect(loadSpy).not.toHaveBeenCalled();
  });

  // DOM: page structure

  it('should render a search input', () => {
    render();
    const input = fixture.debugElement.query(By.css('.search-input'));
    expect(input).toBeTruthy();
  });

  it('should render a term filter dropdown', () => {
    render();
    const select = fixture.debugElement.query(By.css('.filter-dropdown'));
    expect(select).toBeTruthy();
  });

  it('should render an Add Course button', () => {
    render();
    const btn = fixture.debugElement.queryAll(By.css('.action-btn'))
      .find(el => el.nativeElement.textContent.includes('Add Course'));
    expect(btn).toBeTruthy();
  });

  it('hides course import while Canvas is disconnected', () => {
    render();
    expect(fixture.nativeElement.textContent).not.toContain('Import course');
  });

  it('shows course import while Canvas is connected', () => {
    mockCanvasService.getConnection.mockReturnValue(of({ connected: true }));
    render();
    const trigger = fixture.debugElement.query(By.css('.add-course-trigger'));
    expect(trigger.nativeElement.textContent).toContain('Add course');

    trigger.nativeElement.click();
    render();
    expect(fixture.nativeElement.textContent).toContain('Create OMR course');
    expect(fixture.nativeElement.textContent).toContain('Import from Canvas');
  });

  // DOM: course cards

  it('should render one card per course', () => {
    render();
    const cards = fixture.debugElement.queryAll(By.css('.course-card'));
    expect(cards.length).toBe(component.courses.length);
  });

  it('should render course codes in card headers', () => {
    render();
    const codes = fixture.debugElement
      .queryAll(By.css('.course-code'))
      .map(el => el.nativeElement.textContent);
    component.courses.forEach(c => {
      expect(codes.some(t => t.includes(c.code))).toBe(true);
    });
  });

  it('formats and labels an imported Canvas course using its academic term', () => {
    component.courses = [{
      ...component.courses[0],
      source: 'canvas',
      academicTerm: summerTerm,
      academicYearStart: 2026,
    }];
    render();

    expect(fixture.nativeElement.textContent).toContain('Canvas');
    expect(fixture.nativeElement.textContent).toContain('Summer Session 1 2027');
  });

  it('should reduce rendered cards when searchQuery is set', async () => {
    render();
    const input: HTMLInputElement = fixture.debugElement.query(By.css('.search-input')).nativeElement;
    input.value = 'COSC 304';
    input.dispatchEvent(new Event('input'));
    render();
    await fixture.whenStable();
    const cards = fixture.debugElement.queryAll(By.css('.course-card'));
    expect(cards.length).toBe(1);
  });

  it('goToTemplates opens the template builder modal', () => {
    expect(component.viewingTemplates).toBe(false);
    component.goToTemplates();
    expect(component.viewingTemplates).toBe(true);
  });
});
