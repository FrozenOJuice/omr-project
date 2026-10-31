import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { CourseService } from '../../services/course.service';
import { ExamService } from '../../services/exam.service';
import { UserService } from '../../services/user.service';
import { AnnotatedExamView } from './annotated-exam-view';

describe('AnnotatedExamView', () => {
  let fixture: ComponentFixture<AnnotatedExamView>;
  let component: AnnotatedExamView;

  const grade = {
    id: 'grade-1',
    exam_id: 'exam-1',
    omr_marking_id: 'marking-1',
    exam_answer_key_id: 'key-1',
    question_results: {},
    total_score: 8,
    max_score: 10,
    template_version: 1,
    exam_version: 'A',
    student_id: 'student-1',
    status: 'graded',
    flag_reason: null,
    graded_at: '2026-07-24T00:00:00Z',
    section_results: [],
    page_count: 1,
  };
  const stats = {
    exam_id: 'exam-1',
    graded_count: 1,
    mean_score: 8,
    standard_deviation_score: 0,
    median_score: 8,
    mode_scores: [8],
    highest_score: 8,
    lowest_score: 8,
    mean_percentage: 80,
    standard_deviation_percentage: 0,
    min_percentage: 80,
    q1_percentage: 80,
    median_percentage: 80,
    q3_percentage: 80,
    max_percentage: 80,
    score_distribution: [],
    question_stats: [],
    version_stats: [],
  };
  const examService = {
    getGrade: vi.fn(() => of(grade)),
    getExamStats: vi.fn(() => of(stats)),
    getExam: vi.fn(() => of({ id: 'exam-1', course_id: 'course-1' })),
    listExamGrades: vi.fn(() => of([grade])),
    updateGrade: vi.fn(() => of(grade)),
    getGradeIdentity: vi.fn(() => of(null)),
    getGradePageAnnotations: vi.fn(() => of([])),
    getGradePageIdentity: vi.fn(() => of(null)),
    getGradePageVersion: vi.fn(() => of({ field: null, detected_version: 'A' })),
    getGradePageImage: vi.fn(() => of(new Blob(['page'], { type: 'image/png' }))),
  };
  const courseService = {
    getCourseStudents: vi.fn(() => of([])),
  };
  const userService = {
    isProfessorOrAbove: vi.fn(() => true),
  };
  const router = {
    navigate: vi.fn(),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:page'),
    });
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    });

    await TestBed.configureTestingModule({
      imports: [AnnotatedExamView],
      providers: [
        { provide: ExamService, useValue: examService },
        { provide: CourseService, useValue: courseService },
        { provide: UserService, useValue: userService },
        { provide: Router, useValue: router },
        {
          provide: ActivatedRoute,
          useValue: {
            paramMap: of(convertToParamMap({ gradeId: 'grade-1' })),
            snapshot: { queryParamMap: convertToParamMap({ student: 'Alice Example' }) },
          },
        },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(AnnotatedExamView);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('opens the exam-wide statistics modal from the top-right Stats button', () => {
    const button: HTMLButtonElement = fixture.nativeElement.querySelector(
      'button[title="View exam statistics"]',
    );

    expect(button).not.toBeNull();
    expect(button.disabled).toBe(false);
    button.click();
    fixture.detectChanges();

    expect(component.showExamStats()).toBe(true);
    expect(fixture.nativeElement.querySelector('app-exam-stats-view')).not.toBeNull();
  });

  it('requires confirmation before assigning a second result to one student', () => {
    component.examGrades.set([
      { ...grade, id: 'grade-1', student_id: null, status: 'needs_review' },
      { ...grade, id: 'grade-2', student_id: 'student-2' },
    ]);
    component.assigningStudentId = 'student-2';

    component.assignStudent();

    expect(component.confirmingDuplicateAssignment()).toBe(true);
    expect(examService.updateGrade).not.toHaveBeenCalled();
  });

  it('includes explicit duplicate acknowledgement after confirmation', () => {
    component.examGrades.set([
      { ...grade, id: 'grade-1', student_id: null, status: 'needs_review' },
      { ...grade, id: 'grade-2', student_id: 'student-2' },
    ]);
    component.assigningStudentId = 'student-2';
    component.assignStudent();

    component.confirmDuplicateAssignment();

    expect(examService.updateGrade).toHaveBeenCalledWith('grade-1', {
      student_id: 'student-2',
      resolve_flag: true,
      confirm_duplicate_assignment: true,
    });
    expect(component.assignSuccess()).toBe('Student assigned and review flag resolved.');
  });

  it('uses the server-reported conflict count when the local grade list is stale', () => {
    // Local list knows of no conflict for student-2, so the pre-check passes...
    component.examGrades.set([
      { ...grade, id: 'grade-1', student_id: null, status: 'needs_review' },
    ]);
    component.assigningStudentId = 'student-2';
    // ...but the backend rejects the assignment as a duplicate.
    examService.updateGrade.mockReturnValueOnce(
      throwError(() => ({
        status: 409,
        error: {
          error: {
            code: 'duplicate_student_assignment',
            details: { grade_ids: ['grade-9'] },
          },
        },
      })),
    );

    component.assignStudent();

    expect(component.confirmingDuplicateAssignment()).toBe(true);
    expect(component.duplicateConflictCount).toBe(1);
  });
});
