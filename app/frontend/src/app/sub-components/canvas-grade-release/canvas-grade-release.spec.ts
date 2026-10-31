import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { ExamStatus } from '../../enums/tags.enum';
import { Exam } from '../../models/exam.model';
import { CanvasGradeRelease as CanvasGradeReleaseStatus } from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';
import { CanvasGradeRelease } from './canvas-grade-release';

describe('CanvasGradeRelease', () => {
  let fixture: ComponentFixture<CanvasGradeRelease>;
  let component: CanvasGradeRelease;
  const status: CanvasGradeReleaseStatus = {
    exam_id: 'exam-1',
    assignment_id: '9007199254740993',
    assignment_name: 'Midterm',
    eligible_count: 2,
    skipped_count: 1,
    skipped_reasons: { not_linked_to_canvas: 1 },
    target_locked: false,
    last_sent_count: 0,
    last_skipped_count: 0,
    last_failed_count: 0,
    last_attempted_at: null,
    last_attempt_status: null,
  };
  const canvasService = {
    getAssignments: vi.fn(() =>
      of([
        {
          id: '9007199254740993',
          name: 'Midterm',
          due_at: null,
          points_possible: 100,
          published: true,
          html_url: null,
          linked_exam_id: 'exam-1',
          available: true,
        },
      ]),
    ),
    getGradeRelease: vi.fn(() => of(status)),
    linkExamAssignment: vi.fn(() => of(status)),
    unlinkExamAssignment: vi.fn(),
    releaseGrades: vi.fn(() =>
      of<CanvasGradeReleaseStatus>({
        ...status,
        target_locked: true,
        last_sent_count: 2,
        last_skipped_count: 1,
        last_attempted_at: '2026-07-19T12:00:00Z',
        last_attempt_status: 'completed',
      }),
    ),
  };

  beforeEach(async () => {
    vi.clearAllMocks();
    await TestBed.configureTestingModule({
      imports: [CanvasGradeRelease],
      providers: [{ provide: CanvasService, useValue: canvasService }],
    }).compileComponents();
    fixture = TestBed.createComponent(CanvasGradeRelease);
    component = fixture.componentInstance;
    component.courseId = 'course-1';
    component.exam = {
      id: 'exam-1',
      name: 'Midterm',
      description: null,
      start_time: '',
      end_time: '',
      role: 'student',
      course_id: 'course-1',
      exam_template_id: null,
      created_by: 'prof-1',
      created_at: '',
      released: true,
      status: ExamStatus.Graded,
      scanned: 2,
      total: 2,
      completedAt: '',
      regradeCount: 0,
      ambiguousCount: 0,
      hasAnswerKey: true,
      answerKeysComplete: true,
      templateRegistered: true,
      templateMissing: false,
      templateWarning: null,
      generatedPdfPath: null,
      canvasAssignmentId: '9007199254740993',
      canvasAssignmentName: 'Midterm',
    } satisfies Exam;
    fixture.detectChanges();
  });

  it('uses the linked assignment when releasing grades', () => {
    expect(component.selectedAssignmentId()).toBe('9007199254740993');
    component.review();
    expect(component.confirming()).toBe(true);
    component.send();
    expect(canvasService.releaseGrades).toHaveBeenCalledWith('exam-1');
    expect(component.status()?.last_sent_count).toBe(2);
    expect(component.success()).toContain('2 student results sent to Canvas');
  });

  it('reports a release where every Canvas update failed as an error', () => {
    canvasService.releaseGrades.mockReturnValueOnce(
      of({
        ...status,
        last_sent_count: 0,
        last_failed_count: 2,
        last_attempted_at: '2026-07-19T12:00:00Z',
        last_attempt_status: 'failed',
      }),
    );

    component.review();
    component.send();

    expect(component.error()).toContain('2 failed');
    expect(component.success()).toBe('');
  });

  it('shows a release that is already running', () => {
    const exam = component.exam;
    fixture.destroy();
    canvasService.getGradeRelease.mockReturnValueOnce(
      of({
        ...status,
        last_attempted_at: '2026-07-19T12:00:00Z',
        last_attempt_status: 'running',
      }),
    );
    fixture = TestBed.createComponent(CanvasGradeRelease);
    component = fixture.componentInstance;
    component.courseId = 'course-1';
    component.exam = exam;
    fixture.detectChanges();

    expect(fixture.nativeElement.textContent).toContain('still in progress');
  });
});
