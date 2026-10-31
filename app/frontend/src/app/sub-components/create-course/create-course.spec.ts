import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';

import { AcademicTerm } from '../../models/academic-term.model';
import { ApiCourse, Course } from '../../models/course.model';
import { AcademicTermService } from '../../services/academic-term.service';
import { CourseService } from '../../services/course.service';
import { CreateCourse } from './create-course';

const mockTerm: AcademicTerm = {
  id: 'term-summer-1',
  institution: 'ubc',
  code: 'summer-session-1',
  name: 'Summer Session 1',
  term_type: 'preset',
  year_format: 'following_year',
  is_active: true,
  created_by: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const winterTerm: AcademicTerm = {
  ...mockTerm,
  id: 'term-winter-1',
  code: 'winter-session-1',
  name: 'Winter Session 1',
  year_format: 'academic_year_range',
};

const genericTerm: AcademicTerm = {
  ...mockTerm,
  id: 'term-general',
  institution: 'generic',
  code: 'general',
  name: 'General',
  year_format: 'start_year',
};

const customTerm: AcademicTerm = {
  ...mockTerm,
  id: 'term-custom',
  code: null,
  name: 'Fall Intensive',
  term_type: 'custom',
  year_format: 'none',
  created_by: 'professor-1',
};

const archivedTerm: AcademicTerm = {
  ...customTerm,
  id: 'term-archived',
  name: 'Archived Block',
  is_active: false,
};

const mockApiCourse: ApiCourse = {
  id: 'course-abc',
  name: 'COSC 499 - Software Engineering Capstone',
  academic_term_id: mockTerm.id,
  academic_term: mockTerm,
  academic_year_start: 2026,
  archived_at: null,
  created_by: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  invite_link: 'link-abc',
  student_count: 0,
  can_manage_canvas: false,
};

const editCourse: Course = {
  id: 'course-1',
  code: 'COSC 310',
  name: 'Software Engineering',
  students: 0,
  studentList: [],
  academicTerm: winterTerm,
  academicYearStart: 2026,
  archivedAt: null,
  source: 'omr',
  canvasLink: null,
  canManageCanvas: false,
  exams: [],
  inviteLink: 'link-1',
};

describe('CreateCourse', () => {
  let component: CreateCourse;
  let fixture: ComponentFixture<CreateCourse>;
  const mockCourseService = {
    createCourse: vi.fn(() => of(mockApiCourse)),
    updateCourse: vi.fn(() => of(mockApiCourse)),
  };
  const mockAcademicTermService = {
    listTerms: vi.fn(() => of([mockTerm, winterTerm])),
    createTerm: vi.fn(() => of(customTerm)),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    mockCourseService.createCourse.mockReturnValue(of(mockApiCourse));
    mockCourseService.updateCourse.mockReturnValue(of(mockApiCourse));
    mockAcademicTermService.listTerms.mockReturnValue(of([mockTerm, winterTerm]));
    mockAcademicTermService.createTerm.mockReturnValue(of(customTerm));

    await TestBed.configureTestingModule({
      imports: [CreateCourse],
      providers: [
        { provide: CourseService, useValue: mockCourseService },
        { provide: AcademicTermService, useValue: mockAcademicTermService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CreateCourse);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('loads available academic terms', () => {
    expect(mockAcademicTermService.listTerms).toHaveBeenCalledWith({
      institution: 'ubc',
      includeArchived: true,
    });
    expect(component.academicTerms).toEqual([mockTerm, winterTerm]);
  });

  it('associates each visible field label with its form control', () => {
    const fieldLabels = fixture.nativeElement.querySelectorAll(
      '.field-label',
    ) as NodeListOf<HTMLLabelElement>;
    const labels = Array.from(fieldLabels, (label) => label.htmlFor);

    expect(labels).toEqual(['course-code', 'course-name', 'course-year', 'course-term']);
    labels.forEach((id) => expect(fixture.nativeElement.querySelector(`#${id}`)).not.toBeNull());
  });

  it('loads the built-in General term for the None institution', () => {
    mockAcademicTermService.listTerms.mockReturnValueOnce(of([genericTerm]));
    const genericFixture = TestBed.createComponent(CreateCourse);
    genericFixture.componentRef.setInput('institution', 'generic');
    genericFixture.detectChanges();

    expect(mockAcademicTermService.listTerms).toHaveBeenLastCalledWith({
      institution: 'generic',
      includeArchived: true,
    });
    expect(genericFixture.componentInstance.academicTerms).toEqual([genericTerm]);
    expect(genericFixture.componentInstance.termLabel(genericTerm)).toBe(
      `General ${new Date().getFullYear()}`,
    );
    genericFixture.destroy();
  });

  it('requires a valid code, name, year, and academic term', () => {
    component.code = 'COSC 499';
    component.name = 'Capstone';
    expect(component.canSubmit).toBe(false);

    component.academicTermId = mockTerm.id;
    expect(component.canSubmit).toBe(true);
  });

  it('creates a course with academic_term_id', () => {
    component.code = ' COSC 499 ';
    component.name = ' Capstone ';
    component.academicTermId = mockTerm.id;
    component.submit();

    expect(mockCourseService.createCourse).toHaveBeenCalledWith(
      'COSC 499',
      'Capstone',
      mockTerm.id,
      new Date().getFullYear(),
    );
  });

  it('loads the associated term while editing', () => {
    component.editCourse = editCourse;
    component.ngOnChanges();

    expect(component.code).toBe('COSC 310');
    expect(component.academicTermId).toBe(winterTerm.id);
    expect(component.academicYearStart).toBe(2026);
  });

  it('keeps an existing UBC term while loading None terms after institution switching', () => {
    mockAcademicTermService.listTerms.mockReturnValueOnce(of([genericTerm]));
    const switchedFixture = TestBed.createComponent(CreateCourse);
    switchedFixture.componentRef.setInput('institution', 'generic');
    switchedFixture.componentRef.setInput('editCourse', editCourse);
    switchedFixture.detectChanges();

    const switched = switchedFixture.componentInstance;
    expect(mockAcademicTermService.listTerms).toHaveBeenLastCalledWith({
      institution: 'generic',
      includeArchived: true,
    });
    expect(switched.academicTerms).toEqual([winterTerm, genericTerm]);
    expect(switched.academicTermId).toBe(winterTerm.id);
    expect(switched.termsError).toBe('');
    expect(switchedFixture.nativeElement.textContent).toContain('Current course term');
    switchedFixture.destroy();
  });

  it('does not resend an unchanged term while editing', () => {
    component.editCourse = editCourse;
    component.ngOnChanges();
    component.name = 'Updated Name';
    component.submit();

    expect(mockCourseService.updateCourse).toHaveBeenCalledWith(
      'course-1',
      'COSC 310',
      'Updated Name',
      2026,
      undefined,
    );
  });

  it('sends a newly selected term while editing', () => {
    component.editCourse = editCourse;
    component.ngOnChanges();
    component.academicTermId = mockTerm.id;
    component.submit();

    expect(mockCourseService.updateCourse).toHaveBeenCalledWith(
      'course-1',
      'COSC 310',
      'Software Engineering',
      2026,
      mockTerm.id,
    );
  });

  it('opens custom-term creation inline without closing course creation', () => {
    const close = vi.fn();
    component.close.subscribe(close);
    component.onTermSelection('__manage_terms__');
    fixture.detectChanges();

    expect(component.showCustomTermDialog).toBe(true);
    expect(close).not.toHaveBeenCalled();
    expect(fixture.nativeElement.textContent).toContain('Create custom term');
  });

  it('creates and automatically selects a custom term', () => {
    component.openCustomTermDialog();
    component.customTermName = ' Fall Intensive ';
    component.customTermYearFormat = 'none';

    component.createCustomTerm();

    expect(mockAcademicTermService.createTerm).toHaveBeenCalledWith({
      name: 'Fall Intensive',
      term_type: 'custom',
      institution: 'ubc',
      year_format: 'none',
    });
    expect(component.academicTermId).toBe(customTerm.id);
    expect(component.academicTerms).toContain(customTerm);
    expect(component.showCustomTermDialog).toBe(false);
  });

  it('keeps custom-term creation open when the API rejects it', () => {
    mockAcademicTermService.createTerm.mockReturnValueOnce(
      throwError(() => ({
        error: { error: { message: 'An academic term with this name already exists' } },
      })),
    );
    component.openCustomTermDialog();
    component.customTermName = 'Duplicate';

    component.createCustomTerm();

    expect(component.showCustomTermDialog).toBe(true);
    expect(component.customTermError).toBe('An academic term with this name already exists');
  });

  it('hides archived terms unless the archived term is assigned while editing', () => {
    component.academicTerms = [mockTerm, archivedTerm];
    component.academicTermId = '';
    expect(component.selectableTerms).toEqual([mockTerm]);

    component.editCourse = { ...editCourse, academicTerm: archivedTerm };
    component.ngOnChanges();

    expect(component.selectableTerms).toEqual([mockTerm, archivedTerm]);
  });

  it('formats UBC term years from the selected academic year', () => {
    component.academicYearStart = 2026;

    expect(component.termLabel(winterTerm)).toBe('Winter Session 1 2026/27');
    expect(component.termLabel(mockTerm)).toBe('Summer Session 1 2027');
    expect(component.yearFormatLabel('academic_year_range')).toBe('Academic year (2026/27)');
  });

  it('shows an error when course creation fails', () => {
    mockCourseService.createCourse.mockReturnValueOnce(throwError(() => new Error()));
    component.code = 'COSC 499';
    component.name = 'Capstone';
    component.academicTermId = mockTerm.id;
    component.submit();

    expect(component.error).toBe('Failed to create course. Please try again.');
    expect(component.isLoading).toBe(false);
  });
});
