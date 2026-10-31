import { ComponentFixture, TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { CreateExam } from './create-exam';
import { ExamService } from '../../services/exam.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ApiExam } from '../../models/exam.model';
import { ExamTemplateResponse } from '../../models/exam-template.model';
import { CanvasService } from '../../services/canvas.service';

const mockApiExam: ApiExam = {
  id: 'exam-abc',
  name: 'Midterm',
  description: 'First midterm',
  start_time: '2026-07-30T09:00',
  end_time: '2026-07-30T10:30',
  role: 'student',
  course_id: 'course-123',
  exam_template_id: 'tmpl-1',
  created_by: 'user-1',
  created_at: '2026-01-01T00:00:00Z',
  released: false,
  is_graded: false,
  has_any_grade: false,
  has_scans: false,
  total_scans: 0,
  graded_scans: 0,
  failed_scans: 0,
  has_answer_key: false,
  answer_keys_complete: false,
  template_registered: false,
};

const mockTemplate: ExamTemplateResponse = {
  id: 'tmpl-1',
  name: '100 question A-E',
  created_by: 'user-1',
  question_config: { '1': { choices: ['A', 'B'] } },
  sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1'] }],
  total_questions: 1,
  version: 1,
  n_versions: 4,
  blueprint: null,
  version_from_q1: false,
  omr_template_id: null,
  generated_pdf_path: null,
  archived_at: null,
};

const mockExamService = {
  createExam: vi.fn(() => of(mockApiExam)),
};

const mockTemplateService = {
  listMyTemplates: vi.fn(() => of([mockTemplate])),
};
const mockCanvasService = {
  getAssignments: vi.fn(() => of([])),
};

describe('CreateExam', () => {
  let component: CreateExam;
  let fixture: ComponentFixture<CreateExam>;

  beforeEach(async () => {
    vi.clearAllMocks();
    await TestBed.configureTestingModule({
      imports: [CreateExam],
      providers: [
        { provide: ExamService, useValue: mockExamService },
        { provide: ExamTemplateService, useValue: mockTemplateService },
        { provide: CanvasService, useValue: mockCanvasService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(CreateExam);
    component = fixture.componentInstance;
    component.courseId = 'course-123';
    fixture.detectChanges();
  });

  const fillValid = () => {
    component.name = 'Midterm';
    component.date = '2026-07-30';
    component.startClock = '09:00';
    component.durationMinutes = 90;
    component.templateId = 'tmpl-1';
  };

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('loads my templates on init', () => {
    expect(mockTemplateService.listMyTemplates).toHaveBeenCalled();
    expect(component.templates()).toEqual([mockTemplate]);
  });

  // canSubmit

  it('canSubmit is false when all fields are empty', () => {
    expect(component.canSubmit).toBe(false);
  });

  it('canSubmit is false without a template selected', () => {
    fillValid();
    component.templateId = '';
    expect(component.canSubmit).toBe(false);
  });

  it('canSubmit is true when the optional schedule is empty', () => {
    fillValid();
    component.date = '';
    component.startClock = '';
    expect(component.canSubmit).toBe(true);
  });

  it('keeps schedule-only fields out of the way for an unscheduled exam', async () => {
    component.name = 'Practice Exam';
    component.templateId = 'tmpl-1';
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('#exam-start-time')).toBeNull();
    expect(fixture.nativeElement.querySelector('#exam-duration')).toBeNull();
    expect(fixture.nativeElement.querySelector('.schedule-heading').textContent).toContain('create an unscheduled exam');
    expect(fixture.nativeElement.querySelector('.modal-footer button').disabled).toBe(false);

    await fixture.whenStable();
    component.setDate('2026-07-30');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('#exam-start-time')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('#exam-duration')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.modal-footer button').disabled).toBe(true);
  });

  it('canSubmit is false when a date is selected without a start time', () => {
    fillValid();
    component.startClock = '';
    expect(component.canSubmit).toBe(false);
  });

  it('canSubmit is false when duration is not positive', () => {
    fillValid();
    component.durationMinutes = 0;
    expect(component.canSubmit).toBe(false);
  });

  it('canSubmit is true with name, template, date, start time, and duration', () => {
    fillValid();
    expect(component.canSubmit).toBe(true);
  });

  // ngOnChanges

  it('resets all fields on change', () => {
    fillValid();
    component.error = 'some error';
    component.ngOnChanges();
    expect(component.name).toBe('');
    expect(component.date).toBe('');
    expect(component.startClock).toBe('');
    expect(component.durationMinutes).toBe(90);
    expect(component.templateId).toBe('');
    expect(component.error).toBe('');
  });

  // submit

  it('does nothing when canSubmit is false', () => {
    component.submit();
    expect(mockExamService.createExam).not.toHaveBeenCalled();
  });

  it('derives start_time and end_time and passes the template id', () => {
    fillValid();
    component.name = ' Midterm ';
    component.description = ' First midterm ';
    component.submit();
    expect(mockExamService.createExam).toHaveBeenCalledWith(
      'Midterm', 'First midterm', '2026-07-30T09:00', '2026-07-30T10:30', 'student', 'course-123', 'tmpl-1', null,
    );
  });

  it('creates an unscheduled exam when date and time are omitted', () => {
    component.name = ' Practice Exam ';
    component.templateId = 'tmpl-1';

    component.submit();

    expect(mockExamService.createExam).toHaveBeenCalledWith(
      'Practice Exam', null, null, null, 'student', 'course-123', 'tmpl-1', null,
    );
  });

  it('clears the start time when the optional date is cleared', () => {
    component.date = '2026-07-30';
    component.startClock = '09:00';

    component.setDate('');

    expect(component.date).toBe('');
    expect(component.startClock).toBe('');
  });

  it('rolls the end time past midnight for long durations', () => {
    fillValid();
    component.name = 'Night Exam';
    component.startClock = '23:00';
    component.durationMinutes = 120;
    component.submit();
    expect(mockExamService.createExam).toHaveBeenCalledWith(
      'Night Exam', null, '2026-07-30T23:00', '2026-07-31T01:00', 'student', 'course-123', 'tmpl-1', null,
    );
  });

  it('creates an exam from a Canvas assignment', () => {
    component.canvasAssignmentMode = true;
    component.canvasAssignments.set([{
      id: '9007199254740993', name: 'Canvas Midterm', due_at: null, points_possible: 100,
      published: true, html_url: null, linked_exam_id: null, available: true,
    }]);
    fillValid();
    component.selectCanvasAssignment('9007199254740993');
    component.submit();

    expect(mockExamService.createExam).toHaveBeenCalledWith(
      'Canvas Midterm', null, '2026-07-30T09:00', '2026-07-30T10:30',
      'student', 'course-123', 'tmpl-1', '9007199254740993',
    );
  });

  it('requires an assignment when creating from Canvas', () => {
    fillValid();
    component.canvasAssignmentMode = true;
    expect(component.canSubmit).toBe(false);
  });

  it('always submits role as student', () => {
    fillValid();
    component.submit();
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((mockExamService.createExam.mock.calls as any)[0][4]).toBe('student');
  });

  it('emits created event on success', () => {
    const spy = vi.fn();
    component.created.subscribe(spy);
    fillValid();
    component.submit();
    expect(spy).toHaveBeenCalledWith(mockApiExam);
  });

  it('sets error message on failure', () => {
    mockExamService.createExam.mockReturnValueOnce(throwError(() => new Error()));
    fillValid();
    component.submit();
    expect(component.error).toBe('Failed to create exam. Please try again.');
  });

  it('resets isLoading to false on failure', () => {
    mockExamService.createExam.mockReturnValueOnce(throwError(() => new Error()));
    fillValid();
    component.submit();
    expect(component.isLoading).toBe(false);
  });

  // goToTemplates

  it('goToTemplates closes this modal and asks the parent to open the templates modal', () => {
    const closeSpy = vi.fn();
    const manageTemplatesSpy = vi.fn();
    component.close.subscribe(closeSpy);
    component.manageTemplates.subscribe(manageTemplatesSpy);
    component.goToTemplates();
    expect(closeSpy).toHaveBeenCalled();
    expect(manageTemplatesSpy).toHaveBeenCalled();
  });

  // wizardStep (embedded as step 1 of the exam-creation wizard)

  it('does not show the step indicator outside the wizard', () => {
    expect(component.wizardStep).toBeNull();
    expect(fixture.nativeElement.querySelector('app-wizard-steps')).toBeNull();
  });

  it('shows the step indicator once wizardStep is set', () => {
    component.wizardStep = 1;
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-wizard-steps')).not.toBeNull();
  });

  it('labels the submit button "Next" while in the wizard', () => {
    component.wizardStep = 1;
    fixture.detectChanges();
    const submitBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.modal-footer button');
    expect(submitBtn.textContent.trim()).toBe('Next');
  });

  it('labels the submit button "Create Exam" outside the wizard', () => {
    fixture.detectChanges();
    const submitBtn: HTMLButtonElement = fixture.nativeElement.querySelector('.modal-footer button');
    expect(submitBtn.textContent.trim()).toBe('Create Exam');
  });
});
