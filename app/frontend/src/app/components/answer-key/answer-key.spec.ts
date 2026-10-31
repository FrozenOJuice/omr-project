import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { of, Subject, throwError } from 'rxjs';
import { AnswerKey } from './answer-key';
import { ExamAnswerKeyService } from '../../services/exam-answer-key.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ExamService } from '../../services/exam.service';
import { CourseService } from '../../services/course.service';
import { ExamTemplateResponse } from '../../models/exam-template.model';
import {
  ExamAnswerKeyResponse,
  ExtractAnswerKeyScanBatchResponse,
} from '../../models/exam-answer-key.model';

const template: ExamTemplateResponse = {
  id: 'tmpl-1',
  name: 'Standard 2Q',
  created_by: 'user-1',
  question_config: { '1': { choices: ['A', 'B', 'C', 'D'] }, '2': { choices: ['A', 'B', 'C', 'D'] } },
  sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1', '2'] }],
  total_questions: 2,
  version: 1,
  n_versions: 4,
  blueprint: null,
  version_from_q1: false,
  omr_template_id: null,
  generated_pdf_path: null,
  archived_at: null,
};

const existingKey: ExamAnswerKeyResponse = {
  id: 'key-1',
  exam_id: 'exam-1',
  exam_template_id: 'tmpl-1',
  exam_version: 'A',
  answer_key: {
    '1': { grading_type: 'single', correct_choices: ['C'], points: null, partial_weights: null },
    '2': { grading_type: 'multiple', correct_choices: ['A', 'B'], points: 2, partial_weights: null },
  },
  scoring_rules: { points_per_question: 1 },
  answer_key_path: null,
  created_at: '2026-07-01T00:00:00Z',
};

const existingKeyB: ExamAnswerKeyResponse = {
  ...existingKey,
  id: 'key-2',
  exam_version: 'B',
};

const defaultKey: ExamAnswerKeyResponse = {
  ...existingKey,
  id: 'key-default',
  exam_version: null,
};

const scanExtraction: ExtractAnswerKeyScanBatchResponse = {
  pages_per_sheet: 1,
  sheets: [
    {
      sheet_index: 0,
      source_filename: 'keys.pdf',
      page_start: 1,
      page_end: 1,
      answers: {
        '1': { selected_choices: ['B'], confidence: 0.95, flagged: false },
      },
      version: {
        status: 'detected',
        selected_choices: ['A'],
        detected_version: 'A',
        confidence: 0.92,
      },
      minimum_confidence: 0.92,
      warnings: [],
    },
  ],
};

const multiVersionDraftExtraction: ExtractAnswerKeyScanBatchResponse = {
  pages_per_sheet: 1,
  sheets: [
    {
      sheet_index: 0,
      source_filename: 'keys.pdf',
      page_start: 1,
      page_end: 1,
      answers: {
        '1': { selected_choices: ['B', 'C'], confidence: 0.96, flagged: false },
        '2': { selected_choices: ['C', 'D'], confidence: 0.94, flagged: false },
      },
      version: {
        status: 'detected',
        selected_choices: ['A'],
        detected_version: 'A',
        confidence: 0.97,
      },
      minimum_confidence: 0.94,
      warnings: [],
    },
    {
      sheet_index: 1,
      source_filename: 'keys.pdf',
      page_start: 2,
      page_end: 2,
      answers: {
        '1': { selected_choices: ['D'], confidence: 0.93, flagged: false },
        '2': { selected_choices: ['A'], confidence: 0.91, flagged: false },
      },
      version: {
        status: 'detected',
        selected_choices: ['B'],
        detected_version: 'B',
        confidence: 0.95,
      },
      minimum_confidence: 0.91,
      warnings: [],
    },
  ],
};

const matchingExtraction: ExtractAnswerKeyScanBatchResponse = {
  pages_per_sheet: 2,
  sheets: [
    {
      sheet_index: 0,
      source_filename: 'keys.pdf',
      page_start: 1,
      page_end: 2,
      answers: {},
      version: { status: 'detected', selected_choices: ['A'], detected_version: 'A', confidence: 0.94 },
      minimum_confidence: 0.88,
      warnings: [{
        code: 'low_confidence',
        message: 'Question 2 should be reviewed',
        question_id: '2',
        selected_choices: ['C'],
        confidence: 0.88,
      }],
    },
    {
      sheet_index: 1,
      source_filename: 'keys.pdf',
      page_start: 3,
      page_end: 4,
      answers: {},
      version: { status: 'detected', selected_choices: ['B'], detected_version: 'B', confidence: 0.91 },
      minimum_confidence: 0.89,
      warnings: [{
        code: 'version_duplicate',
        message: 'Version B was detected on more than one sheet',
        question_id: null,
        selected_choices: ['B'],
        confidence: 0.91,
      }],
    },
    {
      sheet_index: 2,
      source_filename: 'keys.pdf',
      page_start: 5,
      page_end: 6,
      answers: {},
      version: { status: 'detected', selected_choices: ['B'], detected_version: 'B', confidence: 0.87 },
      minimum_confidence: 0.83,
      warnings: [{
        code: 'version_duplicate',
        message: 'Version B was detected on more than one sheet',
        question_id: null,
        selected_choices: ['B'],
        confidence: 0.87,
      }],
    },
    {
      sheet_index: 3,
      source_filename: 'keys.pdf',
      page_start: 7,
      page_end: 8,
      answers: {},
      version: { status: 'missing', selected_choices: [], detected_version: null, confidence: 0.22 },
      minimum_confidence: 0.22,
      warnings: [{
        code: 'version_not_detected',
        message: 'No exam version was selected',
        question_id: null,
        selected_choices: [],
        confidence: 0.22,
      }],
    },
    {
      sheet_index: 4,
      source_filename: 'keys.pdf',
      page_start: 9,
      page_end: 10,
      answers: {},
      version: { status: 'ambiguous', selected_choices: ['A', 'C'], detected_version: null, confidence: 0.61 },
      minimum_confidence: 0.61,
      warnings: [{
        code: 'version_ambiguous',
        message: 'More than one exam version was selected',
        question_id: null,
        selected_choices: ['A', 'C'],
        confidence: 0.61,
      }],
    },
    {
      sheet_index: 5,
      source_filename: 'keys.pdf',
      page_start: 11,
      page_end: 12,
      answers: {},
      version: { status: 'detected', selected_choices: ['Z'], detected_version: 'Z', confidence: 0.9 },
      minimum_confidence: 0.86,
      warnings: [{
        code: 'version_invalid',
        message: 'Version Z is not used by this exam',
        question_id: null,
        selected_choices: ['Z'],
        confidence: 0.9,
      }],
    },
  ],
};

function setup(
  keysReturn = of([] as ExamAnswerKeyResponse[]),
  templateReturn: ExamTemplateResponse = template,
  graded = false,
) {
  const answerKeyService = {
    listAnswerKeysByExam: vi.fn(() => keysReturn),
    createAnswerKey: vi.fn(() => of(existingKey)),
    updateAnswerKey: vi.fn(() => of(existingKey)),
    getAnswerKey: vi.fn(() => of(existingKey)),
    deleteAnswerKey: vi.fn(() => of(void 0)),
    extractAnswerKeyScan: vi.fn(() => of(scanExtraction)),
  };
  const templateService = {
    getTemplate: vi.fn(() => of(templateReturn)),
    finalizeTemplate: vi.fn(() =>
      of({ ...templateReturn, generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf', omr_template_id: 'omr-1' }),
    ),
  };
  const examService = {
    getExam: vi.fn(() =>
      of({
        id: 'exam-1', name: 'Midterm', course_id: 'course-1', exam_template_id: 'tmpl-1',
        has_any_grade: graded,
      } as never),
    ),
    generateExamPdf: vi.fn(() =>
      of({ generated_pdf_path: 'generated/exam/exam-1/exam_sheet.pdf' } as never),
    ),
  };
  const courseService = {
    getCourse: vi.fn(() => of({ id: 'course-1', name: 'COSC 499 - Capstone' } as never)),
  };

  TestBed.configureTestingModule({
    imports: [AnswerKey],
    providers: [
      { provide: ExamAnswerKeyService, useValue: answerKeyService },
      { provide: ExamTemplateService, useValue: templateService },
      { provide: ExamService, useValue: examService },
      { provide: CourseService, useValue: courseService },
    ],
  });

  const fixture = TestBed.createComponent(AnswerKey);
  const component = fixture.componentInstance;
  component.examId = 'exam-1';
  fixture.detectChanges(); // ngOnInit
  return { fixture, component, answerKeyService, templateService, examService };
}

describe('AnswerKey', () => {
  beforeEach(() => vi.clearAllMocks());

  it('creates and loads the exam, its template shape, and header names', () => {
    const { component, templateService } = setup();
    expect(templateService.getTemplate).toHaveBeenCalledWith('tmpl-1');
    expect(component.examName()).toBe('Midterm');
    expect(component.courseName()).toBe('COSC 499 - Capstone');
    expect(component.questions().length).toBe(2);
    expect(component.questions()[0].choices).toEqual(['A', 'B', 'C', 'D']);
  });

  it('groups answer-key questions by template section in template order', () => {
    const sectionedTemplate: ExamTemplateResponse = {
      ...template,
      name: 'Sectioned 4Q',
      question_config: {
        '1': { choices: ['A', 'B', 'C', 'D'] },
        '2': { choices: ['A', 'B', 'C', 'D'] },
        '3': { choices: ['T', 'F'] },
        '4': { choices: ['T', 'F'] },
      },
      sections: [
        { id: 'mc', name: 'Multiple Choice', type: 'multiple_choice', question_ids: ['1', '2'] },
        { id: 'tf', name: 'True or False', type: 'true_false', question_ids: ['3', '4'] },
      ],
      total_questions: 4,
    };
    const { fixture, component } = setup(of([]), sectionedTemplate);
    fixture.detectChanges();

    expect(component.answerSections().map((section) => section.name)).toEqual([
      'Multiple Choice',
      'True or False',
    ]);
    expect(component.answerSections()[1].questions.map(({ question }) => question.id)).toEqual(['3', '4']);
    expect(fixture.nativeElement.querySelectorAll('.answer-section-group')).toHaveLength(2);
    expect(fixture.nativeElement.textContent).toContain('True / False');
  });

  it('applies grading and points to one section without changing another', () => {
    const sectionedTemplate: ExamTemplateResponse = {
      ...template,
      question_config: {
        ...template.question_config,
        '3': { choices: ['T', 'F'] },
      },
      sections: [
        { id: 'mc', name: 'Multiple Choice', type: 'multiple_choice', question_ids: ['1', '2'] },
        { id: 'tf', name: 'True or False', type: 'true_false', question_ids: ['3'] },
      ],
      total_questions: 3,
    };
    const { component } = setup(of([]), sectionedTemplate);
    const firstSection = component.answerSections()[0];

    component.applySectionGradingType(firstSection, 'multiple');
    component.setSectionPointDraft(firstSection.id, 2.5);
    component.applySectionPoints(firstSection);

    expect(component.questions().slice(0, 2).every((question) =>
      question.gradingType === 'multiple' && question.points === 2.5,
    )).toBe(true);
    expect(component.questions()[2].gradingType).toBe('single');
    expect(component.questions()[2].points).toBe(1);
  });

  it('loads an existing key into the form', () => {
    const { component } = setup(of([existingKey]));
    expect(component.selectedKeyId()).toBe('key-1');
    expect(component.selectedVersion()).toBe('A');
    expect(component.questions()[0].correctChoices).toEqual(['C']);
    expect(component.questions()[1].gradingType).toBe('multiple');
    expect(component.questions()[1].points).toBe(2);
  });

  it('create path posts exam_template_id, version letter, answers, and scoring', () => {
    const { component, answerKeyService } = setup();
    component.selectVersion('B');
    component.toggleCorrect(0, 'B');
    component.toggleCorrect(1, 'D');
    component.save();
    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: 'B',
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['B'], points: 1, partial_weights: null },
        '2': { grading_type: 'single', correct_choices: ['D'], points: 1, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });
  });

  it('update path PATCHes the selected key instead of creating', () => {
    const { component, answerKeyService } = setup(of([existingKey]));
    const refresh = vi.spyOn(component.refreshRequested, 'emit');
    component.save();
    expect(answerKeyService.updateAnswerKey).toHaveBeenCalledWith('key-1', expect.anything());
    expect(answerKeyService.createAnswerKey).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalled();
  });

  it('schedules and fires an autosave after an edit settles', () => {
    vi.useFakeTimers();
    try {
      const { fixture, component, answerKeyService } = setup(of([existingKey]));
      expect(component.saveStatus()).toBeNull(); // loaded, unchanged since, nothing to report yet

      component.toggleCorrect(0, 'A');
      fixture.detectChanges();
      expect(vi.getTimerCount()).toBeGreaterThan(0);
      expect(component.saveStatus()).toEqual({ label: 'Unsaved changes', tagClass: 'tag-amber' });

      vi.runAllTimers();

      expect(answerKeyService.updateAnswerKey).toHaveBeenCalledWith('key-1', expect.anything());
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not schedule an autosave for an already-saved, unchanged key', () => {
    vi.useFakeTimers();
    try {
      const { fixture, answerKeyService } = setup(of([existingKey]));
      fixture.detectChanges();
      vi.runAllTimers();
      expect(answerKeyService.updateAnswerKey).not.toHaveBeenCalled();
    } finally {
      vi.useRealTimers();
    }
  });

  it('saves incomplete work as an in-progress answer key', () => {
    const { component, answerKeyService } = setup();
    const partialKey = {
      ...existingKey,
      answer_key: {
        '1': { ...existingKey.answer_key['1'], correct_choices: [] },
        '2': { ...existingKey.answer_key['2'], correct_choices: [] },
      },
    };
    answerKeyService.createAnswerKey.mockReturnValueOnce(of(partialKey));

    component.save();

    expect(answerKeyService.createAnswerKey).toHaveBeenCalled();
    expect(component.versionSlots()[0].status).toBe('partial');
    expect(component.unansweredQuestionCount()).toBe(2);
  });

  it('visually flags question cards with no correct answer selected yet', () => {
    const { fixture, component } = setup();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.question-card--missing')).toHaveLength(2);

    component.toggleCorrect(0, 'A');
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelectorAll('.question-card--missing')).toHaveLength(1);
  });

  it('shows an incomplete-versions warning banner until every version is complete', () => {
    const { fixture } = setup(of([existingKey])); // 1 of 4 versions (A) is complete
    fixture.detectChanges();
    const banner = fixture.nativeElement.querySelector('.banner--warning');
    expect(banner?.textContent).toContain('1 of 4 versions complete');
  });

  it('locks editing once the exam has any graded submission', () => {
    const { fixture, component } = setup(of([existingKey]), template, true);
    fixture.detectChanges();

    expect(component.examGraded()).toBe(true);
    expect(component.canSave()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('already has graded submissions');

    const saveBtn = fixture.nativeElement.querySelector('.save-key-btn') as HTMLButtonElement;
    expect(saveBtn.disabled).toBe(true);
    const choiceChip = fixture.nativeElement.querySelector('.choice-chip') as HTMLButtonElement;
    expect(choiceChip.disabled).toBe(true);
  });

  it('ignores keyboard answer-entry shortcuts once the exam is graded', () => {
    const { component } = setup(of([existingKey]), template, true);
    const before = component.questions()[1].correctChoices;

    component.handleKeydown(new KeyboardEvent('keydown', { key: 'D' }));

    expect(component.questions()[1].correctChoices).toBe(before); // untouched
  });

  it('builds one fixed answer-key slot for every template version', () => {
    const { component } = setup(of([existingKey]));
    expect(component.versionSlots().map((slot) => slot.label)).toEqual([
      'Version A',
      'Version B',
      'Version C',
      'Version D',
    ]);
    expect(component.completedVersionCount()).toBe(1);

    component.selectVersion('B');

    expect(component.selectedVersion()).toBe('B');
    expect(component.selectedKeyId()).toBeNull();
  });

  it('renders one question workspace without the old steps or free-form key controls', () => {
    const { fixture } = setup(of([existingKey]));
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent as string;

    expect(fixture.nativeElement.querySelector('.stepper')).toBeNull();
    expect(text).not.toContain('+ New key');
    expect(text).not.toContain('Version letter');
    expect(fixture.nativeElement.querySelector('.question-card select')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.question-card .choice-chip')).not.toBeNull();
  });

  it('single grading keeps exactly one correct choice', () => {
    const { component } = setup();
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    expect(component.questions()[0].correctChoices).toEqual(['B']);
  });

  it('setGradingType to single trims correct choices and clears weights', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.setGradingType(0, 'single');
    const q = component.questions()[0];
    expect(q.correctChoices.length).toBe(1);
    expect(q.partialWeights).toEqual({});
  });

  it('partial credit starts equally and allows custom weights', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    expect(component.questions()[0].partialWeights).toEqual({ A: 0.5, B: 0.5 });
    component.setWeight(0, 'A', 0.7);
    component.setWeight(0, 'B', 0.3);
    expect(component.questions()[0].partialWeights).toEqual({ A: 0.7, B: 0.3 });
  });

  it('renders a full three-digit partial-credit percentage in the weight badge', async () => {
    const { fixture, component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.setWeight(0, 'A', 1);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();

    const badge = fixture.nativeElement.querySelector('.choice-weight-badge') as HTMLElement;
    const input = badge.querySelector('.choice-weight-input') as HTMLInputElement;
    expect(input.value).toBe('100');
    expect(badge.textContent).toContain('%');
    expect(input.getAttribute('aria-label')).toBe('Credit percentage for option A');
  });

  it('clamps a partial-credit weight above 100% down to 1 when it is the only correct choice', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    // Simulates a typed/pasted value bypassing the input's min/max attrs
    // (which only constrain the spinner arrows), e.g. 500%.
    component.setWeight(0, 'A', 5);
    expect(component.questions()[0].partialWeights['A']).toBe(1);
  });

  it('clamps a negative partial-credit weight up to 0', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.setWeight(0, 'A', -0.2);
    expect(component.questions()[0].partialWeights['A']).toBe(0);
  });

  it('allows setting individually-valid weights that happen to sum over 100% while editing (regression: A=50%+C=60% used to silently clamp A back down before C was even touched)', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'C');
    component.setWeight(0, 'A', 0.7);
    component.setWeight(0, 'C', 0.6);
    const weights = component.questions()[0].partialWeights;
    expect(weights['A']).toBe(0.7);
    expect(weights['C']).toBe(0.6);
  });

  it('flags a question in validationError once partial weights sum over 100%, and blocks save', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.setWeight(0, 'A', 0.6);
    component.setWeight(0, 'B', 0.6);
    expect(component.validationError()).toContain('must add up to exactly 100%');
    expect(component.canSave()).toBe(false);
  });

  it('flags a question in validationError when partial weights sum under 100%, and blocks save', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.setWeight(0, 'A', 0.3);
    component.setWeight(0, 'B', 0.3);
    expect(component.validationError()).toContain('must add up to exactly 100%');
    expect(component.canSave()).toBe(false);
  });

  it('allows partial weights that sum to exactly 100%', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.setWeight(0, 'A', 0.5);
    component.setWeight(0, 'B', 0.5);
    expect(component.validationError()).toBeNull();
  });

  it('disables save until an untouched draft is actually edited', () => {
    const { component } = setup();
    expect(component.isDirty()).toBe(false);
    expect(component.canSave()).toBe(false);

    component.toggleCorrect(0, 'A');

    expect(component.isDirty()).toBe(true);
    expect(component.canSave()).toBe(true);
  });

  it('disables save again immediately after saving, until the next edit', () => {
    const { component, answerKeyService } = setup();
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(1, 'B');
    expect(component.canSave()).toBe(true);

    component.save();

    expect(answerKeyService.createAnswerKey).toHaveBeenCalled();
    expect(component.isDirty()).toBe(false);
    expect(component.canSave()).toBe(false);

    component.toggleCorrect(1, 'C');
    expect(component.canSave()).toBe(true);
  });

  it('disables save for a freshly loaded existing key, and re-enables it once edited', () => {
    const { component } = setup(of([existingKey]));
    expect(component.selectedKeyId()).toBe('key-1');
    expect(component.isDirty()).toBe(false);
    expect(component.canSave()).toBe(false);

    component.toggleCorrect(0, 'A');

    expect(component.isDirty()).toBe(true);
    expect(component.canSave()).toBe(true);
  });

  it('restores the correct dirty state when switching versions and back', () => {
    const { component } = setup(of([existingKey, existingKeyB]));
    expect(component.selectedVersion()).toBe('A');
    component.toggleCorrect(0, 'A'); // dirty A
    expect(component.canSave()).toBe(true);

    component.selectVersion('B');
    expect(component.isDirty()).toBe(false); // untouched B
    expect(component.canSave()).toBe(false);

    component.selectVersion('A');
    expect(component.isDirty()).toBe(true); // A's edit survived the round trip
    expect(component.canSave()).toBe(true);
  });

  it('rounds partial-credit percentages down for display without changing their weights', () => {
    const { component } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(0, 'B');
    component.toggleCorrect(0, 'C');
    const question = component.questions()[0];
    expect(component.weightPercent(question, 'A')).toBe(33);
    expect(question.partialWeights['A']).toBeCloseTo(1 / 3);
  });

  it('partial sends weights while single/multiple send null', () => {
    const { component, answerKeyService } = setup();
    component.setGradingType(0, 'partial');
    component.toggleCorrect(0, 'C');
    component.setWeight(0, 'C', 1);
    component.toggleCorrect(1, 'A');
    component.save();
    const body = (answerKeyService.createAnswerKey.mock.calls[0] as any)[1];
    expect(body.answer_key['1'].partial_weights).toEqual({ C: 1 });
    expect(body.answer_key['2'].partial_weights).toBeNull();
  });

  it('keys answer-key entries by the template question id, not array position (regression: non-contiguous config, e.g. UBC Q1-as-version)', () => {
    const versionedTemplate: ExamTemplateResponse = {
      ...template,
      question_config: { '2': { choices: ['A', 'B', 'C', 'D'] }, '3': { choices: ['A', 'B', 'C', 'D'] } },
    };
    const answerKeyService = {
      listAnswerKeysByExam: vi.fn(() => of([])),
      createAnswerKey: vi.fn(() => of(existingKey)),
      updateAnswerKey: vi.fn(() => of(existingKey)),
      getAnswerKey: vi.fn(() => of(existingKey)),
      deleteAnswerKey: vi.fn(() => of(void 0)),
    };
    const templateService = { getTemplate: vi.fn(() => of(versionedTemplate)), finalizeTemplate: vi.fn() };
    const examService = {
      getExam: vi.fn(() =>
        of({ id: 'exam-1', name: 'Midterm', course_id: 'course-1', exam_template_id: 'tmpl-1' } as never),
      ),
    };
    const courseService = { getCourse: vi.fn(() => of({ id: 'course-1', name: 'COSC 499' } as never)) };

    TestBed.configureTestingModule({
      imports: [AnswerKey],
      providers: [
        { provide: ExamAnswerKeyService, useValue: answerKeyService },
        { provide: ExamTemplateService, useValue: templateService },
        { provide: ExamService, useValue: examService },
        { provide: CourseService, useValue: courseService },
      ],
    });
    const fixture = TestBed.createComponent(AnswerKey);
    const component = fixture.componentInstance;
    component.examId = 'exam-1';
    fixture.detectChanges();

    expect(component.questions().map((q) => q.id)).toEqual(['2', '3']);
    component.toggleCorrect(0, 'B');
    component.toggleCorrect(1, 'D');
    component.save();

    const body = (answerKeyService.createAnswerKey.mock.calls[0] as any)[1];
    expect(body.answer_key).toEqual({
      '2': { grading_type: 'single', correct_choices: ['B'], points: 1, partial_weights: null },
      '3': { grading_type: 'single', correct_choices: ['D'], points: 1, partial_weights: null },
    });
  });

  it('shows a greyed-out reserved Q1 row noting it defines the exam version, when the template uses version_from_q1', () => {
    const versionedTemplate: ExamTemplateResponse = {
      ...template,
      version_from_q1: true,
      question_config: { '2': { choices: ['A', 'B', 'C', 'D'] } },
    };
    const answerKeyService = {
      listAnswerKeysByExam: vi.fn(() => of([])),
      createAnswerKey: vi.fn(() => of(existingKey)),
      updateAnswerKey: vi.fn(() => of(existingKey)),
      getAnswerKey: vi.fn(() => of(existingKey)),
      deleteAnswerKey: vi.fn(() => of(void 0)),
    };
    const templateService = { getTemplate: vi.fn(() => of(versionedTemplate)), finalizeTemplate: vi.fn() };
    const examService = {
      getExam: vi.fn(() =>
        of({ id: 'exam-1', name: 'Midterm', course_id: 'course-1', exam_template_id: 'tmpl-1' } as never),
      ),
    };
    const courseService = { getCourse: vi.fn(() => of({ id: 'course-1', name: 'COSC 499' } as never)) };

    TestBed.configureTestingModule({
      imports: [AnswerKey],
      providers: [
        { provide: ExamAnswerKeyService, useValue: answerKeyService },
        { provide: ExamTemplateService, useValue: templateService },
        { provide: ExamService, useValue: examService },
        { provide: CourseService, useValue: courseService },
      ],
    });
    const fixture = TestBed.createComponent(AnswerKey);
    const component = fixture.componentInstance;
    component.examId = 'exam-1';
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.reserved-question')).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('selects the version');
  });

  it('edits the correct question when a choice is clicked in the rendered template (regression: @for $index scoping)', () => {
    const { fixture, component } = setup();
    fixture.detectChanges();
    const rows = fixture.nativeElement.querySelectorAll('.question-card:not(.reserved-question)');
    expect(rows.length).toBe(2);
    (rows[0].querySelectorAll('.choice-chip')[2] as HTMLButtonElement).click(); // Q1 -> 'C'
    (rows[1].querySelectorAll('.choice-chip')[1] as HTMLButtonElement).click(); // Q2 -> 'B'
    expect(component.questions()[0].correctChoices).toEqual(['C']);
    expect(component.questions()[1].correctChoices).toEqual(['B']);
  });

  it('shows a 403-specific message when the backend forbids the save', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.createAnswerKey.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(1, 'A');
    component.save();
    expect(component.error()).toContain('created');
  });

  it('shows the backend validation message when the save is rejected as invalid (400)', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.createAnswerKey.mockReturnValueOnce(
      throwError(() => ({ status: 400, error: { error: { message: "Choice 'F' for question '1' is not a valid option" } } })),
    );
    component.toggleCorrect(0, 'A');
    component.toggleCorrect(1, 'A');
    component.save();
    expect(component.error()).toBe("Choice 'F' for question '1' is not a valid option");
  });

  it('shows an error when the exam has no template attached', () => {
    const { component, examService } = setup();
    examService.getExam.mockReturnValueOnce(
      of({ id: 'exam-1', name: 'Midterm', course_id: 'course-1', exam_template_id: null } as never),
    );
    component.ngOnInit();
    expect(component.error()).toContain('no bubble-sheet template');
  });

  // --- QOL: points default to 1 (#306) ---

  it('defaults per-question points to 1 on a new key', () => {
    const { component } = setup();
    expect(component.questions().every((q) => q.points === 1)).toBe(true);
  });

  it('uses the saved default when a question has no point override', () => {
    const keyWithDefault = {
      ...existingKey,
      answer_key: {
        ...existingKey.answer_key,
        '1': { ...existingKey.answer_key['1'], points: null },
      },
      scoring_rules: { default_points_per_question: 2 },
    };
    const { component } = setup(of([keyWithDefault]));
    expect(component.questions()[0].points).toBe(2);
  });

  // --- QOL: question cutoff / UBC fewer questions (#306) ---

  it('only sends answer-key entries for the questions in use', () => {
    const { component, answerKeyService } = setup();
    component.toggleCorrect(0, 'A');
    component.setQuestionsUsed(1);
    component.save();
    const body = (answerKeyService.createAnswerKey.mock.calls[0] as any)[1];
    expect(Object.keys(body.answer_key)).toEqual(['1']);
  });

  it('validation ignores questions beyond the cutoff', () => {
    const { component } = setup();
    component.toggleCorrect(0, 'A'); // Q2 has no answer
    component.setQuestionsUsed(1);
    expect(component.validationError()).toBeNull();
  });

  it('blocks reducing questions used on a saved key (backend PATCH cannot delete entries)', () => {
    const { component } = setup(of([existingKey])); // saved key covers 2 questions
    component.setQuestionsUsed(1);
    expect(component.questionsUsed()).toBe(2);
    expect(component.error()).toContain('Reducing');
  });

  // --- QOL: copy values from another version (#306) ---

  it('copyFromSelected copies answers, grading, points, and scoring from the chosen key', () => {
    const { component } = setup(of([existingKey]));
    component.startNewKey(); // build a fresh key alongside the existing one
    component.copySourceId = 'key-1';
    component.copyFromSelected();
    expect(component.questions()[0].correctChoices).toEqual(['C']);
    expect(component.questions()[1].gradingType).toBe('multiple');
    expect(component.questions()[1].points).toBe(2);
    expect(component.pointsPerQuestion()).toBe(1);
  });

  // --- import: each JSON or CSV file is created as its own answer key immediately ---

  function filesChosenEvent(files: File[]): Event {
    const input = document.createElement('input');
    Object.defineProperty(input, 'files', { value: files });
    return { target: input } as unknown as Event;
  }

  // Stages then submits, mirroring the two-step pick-then-upload/import flow.
  function stageAndImport(component: AnswerKey, ...contents: string[]): void {
    const files = contents.map((c, i) => new File([c], `key-${i}.json`, { type: 'application/json' }));
    component.onImportFilesChosen(filesChosenEvent(files));
    component.importStagedFiles();
  }

  function stageAndImportCsv(component: AnswerKey, content: string): void {
    component.onImportFilesChosen(filesChosenEvent([new File([content], 'key.csv', { type: 'text/csv' })]));
    component.importStagedFiles();
  }

  function stageAndUploadScan(component: AnswerKey, ...files: File[]): void {
    component.onScanFilesChosen(filesChosenEvent(files));
    component.uploadStagedScans();
  }

  const versionAPayload = {
    exam_version: 'A',
    default_points_per_question: 2,
    questions: {
      '1': { grading_type: 'single', correct_choices: ['C'], points: 2, partial_weights: null },
      '2': { grading_type: 'multiple', correct_choices: ['A', 'D'], points: 2, partial_weights: null },
    },
  };

  it('opens the upload modal on the scan tab from the toolbar button', () => {
    const { fixture, component } = setup();
    const uploadButton = Array.from(
      fixture.nativeElement.querySelectorAll('button') as NodeListOf<HTMLButtonElement>,
    ).find((button) => button.textContent?.includes('Upload Answer Key'));
    uploadButton?.click();
    fixture.detectChanges();

    expect(component.uploadModalOpen()).toBe(true);
    expect(component.uploadModalTab()).toBe('scan');
    expect(fixture.nativeElement.querySelector('.upload-modal-dialog')).not.toBeNull();
    expect(fixture.nativeElement.querySelector('.upload-file-drop')).not.toBeNull();
    expect(fixture.nativeElement.textContent).toContain('Choose or drop a PDF file');
    expect(fixture.nativeElement.textContent).toContain('maximum 10 MB each');
  });

  it('switches between the scan and import tabs', () => {
    const { fixture, component } = setup();
    component.openUploadModal();
    fixture.detectChanges();

    component.selectUploadModalTab('import');
    fixture.detectChanges();
    expect(component.uploadModalTab()).toBe('import');
    expect(fixture.nativeElement.textContent).toContain('Choose or drop JSON/CSV files');

    component.selectUploadModalTab('scan');
    fixture.detectChanges();
    expect(component.uploadModalTab()).toBe('scan');
    expect(fixture.nativeElement.textContent).toContain('Choose or drop a PDF file');
  });

  it('stages scan files before uploading, and can remove or clear them', () => {
    const { component, answerKeyService } = setup();
    const fileA = new File(['pdf'], 'a.pdf', { type: 'application/pdf' });
    const fileB = new File(['pdf'], 'b.pdf', { type: 'application/pdf' });

    component.onScanFilesChosen(filesChosenEvent([fileA, fileB]));
    expect(component.stagedScanFiles()).toEqual([fileA, fileB]);

    component.removeStagedScanFile(fileA);
    expect(component.stagedScanFiles()).toEqual([fileB]);

    component.clearStagedScanFiles();
    expect(component.stagedScanFiles()).toEqual([]);
    expect(answerKeyService.extractAnswerKeyScan).not.toHaveBeenCalled();
  });

  it('uploads staged PDFs using the current question count and retains the extraction', () => {
    const { fixture, component, answerKeyService } = setup();
    component.setQuestionsUsed(1);
    const file = new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' });

    stageAndUploadScan(component, file);
    fixture.detectChanges();

    expect(answerKeyService.extractAnswerKeyScan).toHaveBeenCalledWith('exam-1', [file], 1);
    expect(component.answerKeyScanExtraction()).toEqual(scanExtraction);
    expect(component.isUploadingAnswerKeyScan()).toBe(false);
    expect(component.uploadModalOpen()).toBe(false);
    expect(fixture.nativeElement.textContent).toContain('Scanned 1 answer-key sheet.');
    expect(component.questions().every((question) => question.correctChoices.length === 0)).toBe(true);
  });

  it('uploads multiple staged PDFs in one request', () => {
    const { component, answerKeyService } = setup();
    const fileA = new File(['pdf'], 'a.pdf', { type: 'application/pdf' });
    const fileB = new File(['pdf'], 'b.pdf', { type: 'application/pdf' });

    stageAndUploadScan(component, fileA, fileB);

    expect(answerKeyService.extractAnswerKeyScan).toHaveBeenCalledWith('exam-1', [fileA, fileB], 2);
  });

  it('shows a scanning state until extraction finishes', () => {
    const pending = new Subject<ExtractAnswerKeyScanBatchResponse>();
    const { fixture, component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(pending.asObservable());

    stageAndUploadScan(component, new File(['pdf'], 'key.pdf', { type: 'application/pdf' }));
    fixture.detectChanges();

    expect(component.isUploadingAnswerKeyScan()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Scanning…');

    pending.next(scanExtraction);
    pending.complete();
    expect(component.isUploadingAnswerKeyScan()).toBe(false);
  });

  it('rejects non-PDF and oversized answer-key files before calling the API', () => {
    const { component, answerKeyService } = setup();

    stageAndUploadScan(component, new File(['text'], 'key.txt', { type: 'text/plain' }));
    expect(component.error()).toContain('PDF');

    const oversized = new File(['pdf'], 'key.pdf', { type: 'application/pdf' });
    Object.defineProperty(oversized, 'size', { value: 10_000_001 });
    stageAndUploadScan(component, oversized);
    expect(component.error()).toContain('10 MB');
    expect(answerKeyService.extractAnswerKeyScan).not.toHaveBeenCalled();
  });

  it('surfaces backend answer-key scan errors and clears the loading state', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(
      throwError(() => ({
        status: 400,
        error: { error: { message: 'PDF pages must be a multiple of 2' } },
      })),
    );

    stageAndUploadScan(component, new File(['pdf'], 'key.pdf', { type: 'application/pdf' }));

    expect(component.isUploadingAnswerKeyScan()).toBe(false);
    expect(component.answerKeyScanExtraction()).toBeNull();
    expect(component.error()).toBe('PDF pages must be a multiple of 2');
  });

  it('displays every extracted sheet with pages, version, confidence, and warnings', () => {
    const { fixture, component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));

    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );
    fixture.detectChanges();

    expect(component.answerKeyScanReviewOpen()).toBe(true);
    expect(fixture.nativeElement.querySelectorAll('.scan-match-sheet')).toHaveLength(6);
    expect(fixture.nativeElement.textContent).toContain('Pages 1–2');
    expect(fixture.nativeElement.textContent).toContain('Version A');
    expect(fixture.nativeElement.textContent).toContain('Confidence 94%');
    expect(fixture.nativeElement.textContent).toContain('Minimum confidence');
    expect(fixture.nativeElement.textContent).toContain('Question 2 should be reviewed');
    expect(fixture.nativeElement.textContent).toContain('Version Z (invalid)');
  });

  it('labels each sheet with its source file only when more than one file was uploaded', () => {
    const { fixture, component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));
    stageAndUploadScan(component, new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }));
    fixture.detectChanges();

    // Fixture sheets all share one source_filename, so the label stays hidden.
    expect(component.answerKeyScanHasMultipleSourceFiles()).toBe(false);
    expect(fixture.nativeElement.querySelector('.scan-match-sheet-file')).toBeNull();

    const twoFileExtraction: ExtractAnswerKeyScanBatchResponse = {
      ...matchingExtraction,
      sheets: matchingExtraction.sheets.map((sheet, index) => ({
        ...sheet,
        source_filename: index === 0 ? 'a.pdf' : 'b.pdf',
      })),
    };
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(twoFileExtraction));
    stageAndUploadScan(
      component,
      new File(['pdf'], 'a.pdf', { type: 'application/pdf' }),
      new File(['pdf'], 'b.pdf', { type: 'application/pdf' }),
    );
    fixture.detectChanges();

    expect(component.answerKeyScanHasMultipleSourceFiles()).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('a.pdf');
    expect(fixture.nativeElement.textContent).toContain('b.pdf');
  });

  it('automatically matches only unique valid detected versions', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));

    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );

    const matches = component.answerKeyScanMatches();
    expect(matches[0].targetVersion).toBe('A');
    expect(matches.slice(1).every((match) => match.targetVersion === undefined)).toBe(true);
    expect(component.answerKeyScanMatchValidationError()).toContain('5 sheets');
  });

  it('supports PDF-order and fully manual matching', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));
    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );

    component.setAnswerKeyScanMatchingMode('ordered');
    expect(component.answerKeyScanMatches().map((match) => match.targetVersion)).toEqual([
      'A', 'B', 'C', 'D', undefined, undefined,
    ]);

    component.setAnswerKeyScanMatchingMode('manual');
    expect(component.answerKeyScanMatches().every((match) => match.targetVersion === undefined)).toBe(true);
    expect(component.answerKeyScanMatchingMode()).toBe('manual');
  });

  it('prevents duplicate targets and allows sheets to be skipped', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));
    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );
    component.setAnswerKeyScanMatchingMode('manual');

    component.setAnswerKeyScanSheetTarget(0, 'A');
    component.setAnswerKeyScanSheetTarget(1, 'A');
    expect(component.answerKeyScanMatchFor(1)?.targetVersion).toBeUndefined();
    expect(component.answerKeyScanMatchError()).toContain('already assigned');
    expect(component.isAnswerKeyScanVersionAssigned('A', 1)).toBe(true);

    component.setAnswerKeyScanSheetTarget(1, '__skip__');
    expect(component.answerKeyScanMatchFor(1)?.action).toBe('skip');
    expect(component.answerKeyScanTargetValue(component.answerKeyScanMatchFor(1)!)).toBe('__skip__');
  });

  it('confirms a valid mix of ordered targets and skipped sheets', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));
    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );
    component.setAnswerKeyScanMatchingMode('ordered');
    component.setAnswerKeyScanSheetTarget(4, '__skip__');
    component.setAnswerKeyScanSheetTarget(5, '__skip__');

    expect(component.answerKeyScanMatchValidationError()).toBeNull();
    component.confirmAnswerKeyScanMatches();

    expect(component.confirmedAnswerKeyScanMatches()).toEqual({
      matching_mode: 'ordered',
      matches: [
        { sheet_index: 0, action: 'apply', target_version: 'A' },
        { sheet_index: 1, action: 'apply', target_version: 'B' },
        { sheet_index: 2, action: 'apply', target_version: 'C' },
        { sheet_index: 3, action: 'apply', target_version: 'D' },
        { sheet_index: 4, action: 'skip', target_version: null },
        { sheet_index: 5, action: 'skip', target_version: null },
      ],
      overwrite_existing: false,
    });
    expect(component.answerKeyScanReviewOpen()).toBe(false);
    expect(component.confirmedAnswerKeyScanCount()).toBe(4);
  });

  it('applies scanned selections to multi-version drafts and auto-saves each applied version, preserving scoring settings', async () => {
    const configuredKey: ExamAnswerKeyResponse = {
      ...existingKey,
      answer_key: {
        '1': {
          grading_type: 'partial',
          correct_choices: ['B', 'C'],
          points: 3,
          partial_weights: { B: 0.4, C: 0.6 },
        },
        '2': {
          grading_type: 'multiple',
          correct_choices: ['A', 'B'],
          points: 2,
          partial_weights: null,
        },
      },
      scoring_rules: { default_points_per_question: 4 },
    };
    const { component, answerKeyService } = setup(of([configuredKey]));
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(multiVersionDraftExtraction));
    answerKeyService.createAnswerKey.mockReturnValueOnce(of(existingKeyB));

    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );
    component.confirmAnswerKeyScanMatches();

    expect(component.selectedVersion()).toBe('A');
    expect(component.questions()[0]).toMatchObject({
      gradingType: 'partial',
      correctChoices: ['B', 'C'],
      partialWeights: { B: 0.4, C: 0.6 },
      points: 3,
    });
    expect(component.questions()[1]).toMatchObject({
      gradingType: 'multiple',
      correctChoices: ['C', 'D'],
      points: 2,
    });
    expect(component.pointsPerQuestion()).toBe(4);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.updateAnswerKey).toHaveBeenCalledWith('key-1', {
      answer_key: {
        '1': { grading_type: 'partial', correct_choices: ['B', 'C'], points: 3, partial_weights: { B: 0.4, C: 0.6 } },
        '2': { grading_type: 'multiple', correct_choices: ['C', 'D'], points: 2, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 4 },
    });
    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: 'B',
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['D'], points: 1, partial_weights: null },
        '2': { grading_type: 'single', correct_choices: ['A'], points: 1, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });
    expect(component.scannedDraftVersions()).toEqual([]);
    expect(component.saved()).toBe(true);
    expect(component.scanAutoSaveResult()).toEqual({ saved: 2, total: 2, failures: [] });
  });

  it('keeps scanned drafts correct while switching versions, and does not mark a version saved if it was edited again before its auto-save resolved', async () => {
    const { component, answerKeyService } = setup(of([existingKey]));
    const switchingExtraction: ExtractAnswerKeyScanBatchResponse = {
      ...multiVersionDraftExtraction,
      sheets: [
        {
          ...multiVersionDraftExtraction.sheets[0],
          answers: {
            ...multiVersionDraftExtraction.sheets[0].answers,
            '1': { selected_choices: ['B'], confidence: 0.96, flagged: false },
          },
        },
        multiVersionDraftExtraction.sheets[1],
      ],
    };
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(switchingExtraction));
    answerKeyService.createAnswerKey.mockReturnValueOnce(of(existingKeyB));
    stageAndUploadScan(component,
      new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }),
    );
    component.confirmAnswerKeyScanMatches();

    // Switching versions (and editing B) happens synchronously, before the
    // auto-save requests fired by confirm above have resolved.
    component.selectVersion('B');
    expect(component.questions().map((question) => question.correctChoices)).toEqual([['D'], ['A']]);
    component.toggleCorrect(0, 'B');
    component.selectVersion('A');
    expect(component.questions().map((question) => question.correctChoices)).toEqual([
      ['B'], ['C', 'D'],
    ]);
    component.selectVersion('B');
    expect(component.questions().map((question) => question.correctChoices)).toEqual([['B'], ['A']]);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.updateAnswerKey).toHaveBeenCalledWith('key-1', {
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['B'], points: 1, partial_weights: null },
        '2': { grading_type: 'multiple', correct_choices: ['C', 'D'], points: 2, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });
    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: 'B',
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['D'], points: 1, partial_weights: null },
        '2': { grading_type: 'single', correct_choices: ['A'], points: 1, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });

    // B's own auto-save (issued with its pre-edit answers) resolved after
    // the toggleCorrect edit above. The edit must not be silently marked
    // saved, even though the version's key id is now known.
    expect(component.selectedVersion()).toBe('B');
    expect(component.selectedKeyId()).toBe('key-2');
    expect(component.saved()).toBe(false);
    expect(component.questions().map((question) => question.correctChoices)).toEqual([['B'], ['A']]);

    component.save();
    expect(answerKeyService.updateAnswerKey).toHaveBeenCalledWith('key-2', {
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['B'], points: 1, partial_weights: null },
        '2': { grading_type: 'single', correct_choices: ['A'], points: 1, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });
  });

  it('automatically targets the unversioned key when exactly one sheet is uploaded, and auto-saves it', async () => {
    const singleVersionTemplate = { ...template, n_versions: 1 };
    const { component, answerKeyService } = setup(of([]), singleVersionTemplate);
    answerKeyService.createAnswerKey.mockReturnValueOnce(of(defaultKey));

    stageAndUploadScan(component,
      new File(['pdf'], 'key.pdf', { type: 'application/pdf' }),
    );

    expect(component.answerKeyScanMatchFor(0)?.targetVersion).toBeNull();
    expect(component.answerKeyScanMatchValidationError()).toBeNull();
    component.confirmAnswerKeyScanMatches();
    expect(component.selectedVersion()).toBeNull();
    expect(component.questions()[0].correctChoices).toEqual(['B']);

    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: null,
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['B'], points: 1, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 1 },
    });
    expect(component.scannedDraftVersions()).toEqual([]);
    expect(component.selectedKeyId()).toBe('key-default');
    expect(component.saved()).toBe(true);
  });

  it('sorts a sheet\'s detected answers by question number and toggles them open and closed', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(multiVersionDraftExtraction));
    stageAndUploadScan(component, new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }));

    const sheet = component.answerKeyScanExtraction()!.sheets[0];
    const entries = component.sortedAnswerEntries(sheet);
    expect(entries.map((entry) => entry.id)).toEqual(['1', '2']);
    expect(component.answerKeyScanAnswerLabel(entries[0].question)).toBe('B, C');

    expect(component.isScanSheetExpanded(0)).toBe(false);
    component.toggleScanSheetExpanded(0);
    expect(component.isScanSheetExpanded(0)).toBe(true);
    component.toggleScanSheetExpanded(0);
    expect(component.isScanSheetExpanded(0)).toBe(false);
  });

  it('labels a blank detected answer, and reports no detected answers for a sheet with none extracted', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(matchingExtraction));
    stageAndUploadScan(component, new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }));

    expect(component.sortedAnswerEntries(component.answerKeyScanExtraction()!.sheets[0])).toEqual([]);
    expect(component.answerKeyScanAnswerLabel({ selected_choices: [], confidence: 0.9, flagged: false })).toBe('Blank');
  });

  it('resets expanded sheets on a new upload', () => {
    const { component, answerKeyService } = setup();
    answerKeyService.extractAnswerKeyScan.mockReturnValueOnce(of(multiVersionDraftExtraction));
    stageAndUploadScan(component, new File(['pdf'], 'all-keys.pdf', { type: 'application/pdf' }));
    component.toggleScanSheetExpanded(0);
    expect(component.isScanSheetExpanded(0)).toBe(true);

    stageAndUploadScan(component, new File(['pdf'], 'again.pdf', { type: 'application/pdf' }));
    expect(component.isScanSheetExpanded(0)).toBe(false);
  });

  it('stages import files before importing, and can remove or clear them', () => {
    const { component } = setup();
    const fileA = new File([JSON.stringify(versionAPayload)], 'a.json', { type: 'application/json' });
    const fileB = new File([JSON.stringify(versionAPayload)], 'b.json', { type: 'application/json' });

    component.onImportFilesChosen(filesChosenEvent([fileA, fileB]));
    expect(component.stagedImportFiles()).toEqual([fileA, fileB]);

    component.removeStagedImportFile(fileA);
    expect(component.stagedImportFiles()).toEqual([fileB]);

    component.clearStagedImportFiles();
    expect(component.stagedImportFiles()).toEqual([]);
  });

  it('creates an answer key directly from an imported JSON file, no manual save needed', async () => {
    const { component, answerKeyService } = setup();
    stageAndImport(component, JSON.stringify(versionAPayload));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: 'A',
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['C'], points: 2, partial_weights: null },
        '2': { grading_type: 'multiple', correct_choices: ['A', 'D'], points: 2, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 2 },
    });
    expect(component.isImporting()).toBe(false);
    expect(component.importResult()).toEqual({ imported: 1, total: 1, failures: [] });
    // the newly created key (mock returns `existingKey`) becomes selected
    expect(component.selectedKeyId()).toBe('key-1');
  });

  it('creates an answer key from the matching CSV export format', async () => {
    const { component, answerKeyService } = setup();
    stageAndImportCsv(component, [
      'question,correct_choices,grading_type,points,partial_weights,exam_version,default_points_per_question',
      '1,C,single,2,{},A,2',
      '2,A|D,multiple,2,{},A,2',
    ].join('\n'));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).toHaveBeenCalledWith('exam-1', {
      exam_template_id: 'tmpl-1',
      exam_version: 'A',
      answer_key: {
        '1': { grading_type: 'single', correct_choices: ['C'], points: 2, partial_weights: null },
        '2': { grading_type: 'multiple', correct_choices: ['A', 'D'], points: 2, partial_weights: null },
      },
      scoring_rules: { default_points_per_question: 2 },
    });
  });

  it('imports multiple files, one answer key per file', async () => {
    const { component, answerKeyService } = setup();
    const versionBPayload = { ...versionAPayload, exam_version: 'B' };
    stageAndImport(component, JSON.stringify(versionAPayload), JSON.stringify(versionBPayload));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).toHaveBeenCalledTimes(2);
    expect(component.importResult()).toEqual({ imported: 2, total: 2, failures: [] });
  });

  it('reports per-file failures without blocking the other imports', async () => {
    const { component, answerKeyService } = setup();
    stageAndImport(component, 'not json', JSON.stringify(versionAPayload));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).toHaveBeenCalledTimes(1); // only the valid file reached the API
    const result = component.importResult();
    expect(result).toMatchObject({ imported: 1, total: 2 });
    expect(result?.failures).toHaveLength(1);
    expect(result?.failures[0].message).toContain('not valid JSON');
  });

  it('surfaces the backend validation message when the API rejects an imported file', async () => {
    const { component, answerKeyService } = setup();
    answerKeyService.createAnswerKey.mockReturnValueOnce(
      throwError(() => ({ error: { error: { message: "Choice 'F' is not a valid option" } } })),
    );
    stageAndImport(component, JSON.stringify(versionAPayload));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(component.importResult()?.failures[0].message).toContain("Choice 'F' is not a valid option");
  });

  it('shows an error when the imported JSON has no "questions" field', async () => {
    const { component, answerKeyService } = setup();
    stageAndImport(component, JSON.stringify({ exam_version: 'A' }));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(answerKeyService.createAnswerKey).not.toHaveBeenCalled();
    expect(component.importResult()?.failures[0].message).toContain('questions');
  });

  // --- clear an answer key, with inline confirmation ---

  it('requests confirmation without immediately clearing the key', () => {
    const { component, answerKeyService } = setup(of([existingKey]));
    component.requestClearKey(existingKey);
    expect(answerKeyService.deleteAnswerKey).not.toHaveBeenCalled();
    expect(component.confirmingClearKeyId()).toBe(existingKey.id);
    expect(component.existingKeys()).toEqual([existingKey]);
  });

  it('clears the key after confirmation and leaves that version ready to rebuild', () => {
    const { component, answerKeyService } = setup(of([existingKey, existingKeyB]));
    component.requestClearKey(existingKey);
    component.clearKey(existingKey); // this is the currently-selected key
    expect(answerKeyService.deleteAnswerKey).toHaveBeenCalledWith('key-1');
    expect(component.existingKeys().map((k) => k.id)).toEqual(['key-2']);
    expect(component.selectedVersion()).toBe('A');
    expect(component.selectedKeyId()).toBeNull();
  });

  it('starts a fresh new key when the last remaining answer key is cleared', () => {
    const { component } = setup(of([existingKey]));
    component.requestClearKey(existingKey);
    component.clearKey(existingKey);
    expect(component.existingKeys()).toEqual([]);
    expect(component.selectedKeyId()).toBeNull();
  });

  it('clearing a key that is not selected leaves the current selection untouched', () => {
    const { component } = setup(of([existingKey, existingKeyB])); // selects existingKey by default
    component.requestClearKey(existingKeyB);
    component.clearKey(existingKeyB);
    expect(component.existingKeys().map((k) => k.id)).toEqual(['key-1']);
    expect(component.selectedKeyId()).toBe('key-1');
  });

  it('shows a 403-specific message when the backend forbids clearing', () => {
    const { component, answerKeyService } = setup(of([existingKey]));
    answerKeyService.deleteAnswerKey.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    component.requestClearKey(existingKey);
    component.clearKey(existingKey);
    expect(component.error()).toContain('created');
  });

  // --- QOL: keyboard answer entry (#306) ---

  function key(component: AnswerKey, k: string) {
    component.handleKeydown(
      { key: k, target: document.body, preventDefault: () => {} } as unknown as KeyboardEvent,
    );
  }

  it('typing a choice letter answers the active question and advances (single)', () => {
    const { component } = setup();
    key(component, 'c');
    expect(component.questions()[0].correctChoices).toEqual(['C']);
    expect(component.activeQuestion()).toBe(1);
    key(component, 'a');
    expect(component.questions()[1].correctChoices).toEqual(['A']);
  });

  it('typing does not advance on multiple-answer questions', () => {
    const { component } = setup();
    component.setGradingType(0, 'multiple');
    key(component, 'a');
    key(component, 'b');
    expect(component.questions()[0].correctChoices).toEqual(['A', 'B']);
    expect(component.activeQuestion()).toBe(0);
  });

  it('arrow keys move the active question', () => {
    const { component } = setup();
    key(component, 'ArrowDown');
    expect(component.activeQuestion()).toBe(1);
    key(component, 'ArrowUp');
    expect(component.activeQuestion()).toBe(0);
    key(component, 'ArrowRight');
    expect(component.activeQuestion()).toBe(1);
    key(component, 'ArrowLeft');
    expect(component.activeQuestion()).toBe(0);
  });

  it('centres the newly active question after keyboard navigation', async () => {
    const { component, fixture } = setup();
    const question = fixture.nativeElement.querySelector('[data-question-index="1"]') as HTMLElement;
    question.scrollIntoView = vi.fn();

    key(component, 'ArrowDown');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(question.scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth', block: 'center', inline: 'nearest',
    });
  });

  it('delete clears the active question without moving', () => {
    const { component } = setup();
    key(component, 'a');
    expect(component.activeQuestion()).toBe(1);
    key(component, 'b');
    key(component, 'Backspace');
    expect(component.questions()[1].correctChoices).toEqual([]);
    expect(component.activeQuestion()).toBe(1);
  });

  it('ignores keys typed into form fields', () => {
    const { component } = setup();
    const input = document.createElement('input');
    component.handleKeydown(
      { key: 'a', target: input, preventDefault: () => {} } as unknown as KeyboardEvent,
    );
    expect(component.questions()[0].correctChoices).toEqual([]);
  });

  it('finalizes the template with OMR when a generated template has an answer key', () => {
    const { component, templateService } = setup(of([defaultKey]));
    component.template.set({
      ...template,
      n_versions: 1,
      generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf',
    });
    component.finalizeTemplate();
    expect(templateService.finalizeTemplate).toHaveBeenCalledWith('tmpl-1');
    expect(component.template()?.omr_template_id).toBe('omr-1');
  });

  it('allows finalizing without answer keys even when layout generation needs recovery', () => {
    const { component } = setup();
    component.template.set({
      ...template,
      n_versions: 1,
    });
    expect(component.canFinalizeTemplate()).toBe(true);

    component.existingKeys.set([defaultKey]);
    expect(component.canFinalizeTemplate()).toBe(true);

    component.template.set({
      ...template,
      n_versions: 1,
      generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf',
      omr_template_id: 'omr-1',
    });
    expect(component.canFinalizeTemplate()).toBe(false);
  });

  it('automatically recovers registration when complete saved keys are loaded', () => {
    const singleVersionTemplate = { ...template, n_versions: 1 };
    const { component, templateService } = setup(of([defaultKey]), singleVersionTemplate);

    expect(templateService.finalizeTemplate).toHaveBeenCalledWith('tmpl-1');
    expect(component.template()?.generated_pdf_path).toBe('generated/tmpl-1/bubble_sheet.pdf');
    expect(component.template()?.omr_template_id).toBe('omr-1');
  });

  it('does not require every configured answer-key version before finalizing', () => {
    const keys = ['A', 'B', 'C', 'D'].map((version, index) => ({
      ...existingKey,
      id: `key-${version}`,
      exam_version: version,
      created_at: `2026-07-0${index + 1}T00:00:00Z`,
    }));
    const { component } = setup(of(keys.slice(0, 3)));
    component.template.set({
      ...template,
      generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf',
    });
    expect(component.canFinalizeTemplate()).toBe(true);

    component.existingKeys.set(keys);
    expect(component.canFinalizeTemplate()).toBe(true);
  });

  // wizardStep (embedded as step 2 of the exam-creation wizard)

  it('does not show the step indicator or Next button outside the wizard', () => {
    const { fixture } = setup();
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('app-wizard-steps')).toBeNull();
    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    expect(buttons.some((b) => b.textContent?.includes('Next: Exam PDFs'))).toBe(false);
  });

  it('shows the step indicator and a Next button once wizardStep is set', () => {
    const { fixture, component } = setup();
    fixture.componentRef.setInput('wizardStep', 2);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('app-wizard-steps')).not.toBeNull();
    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    const nextBtn = buttons.find((b) => b.textContent?.includes('Next: Exam PDFs'));
    expect(nextBtn).toBeDefined();
  });

  it('disables the Next button until every version has a complete answer key', () => {
    const { fixture } = setup(of([existingKey])); // only version A is complete; template has 4 versions
    fixture.componentRef.setInput('wizardStep', 2);
    fixture.detectChanges();

    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    const nextBtn = buttons.find((b) => b.textContent?.includes('Next: Exam PDFs'))!;
    expect(nextBtn.disabled).toBe(true);

    nextBtn.click();
    // Clicking a disabled button must not advance the wizard -- otherwise a
    // prof could skip straight to uploading scans with no answer key set,
    // silently breaking grading later with no obvious cause.
    const spy = vi.fn();
    fixture.componentInstance.nextRequested.subscribe(spy);
    nextBtn.click();
    expect(spy).not.toHaveBeenCalled();
  });

  it('emits nextRequested when the wizard Next button is clicked once every version is complete', () => {
    const allVersionsComplete = ['A', 'B', 'C', 'D'].map((version, index) => ({
      ...existingKey,
      id: `key-${version}`,
      exam_version: version,
      created_at: `2026-07-0${index + 1}T00:00:00Z`,
    }));
    const { fixture, component } = setup(of(allVersionsComplete));
    fixture.componentRef.setInput('wizardStep', 2);
    fixture.detectChanges();
    const spy = vi.fn();
    component.nextRequested.subscribe(spy);

    const buttons: HTMLButtonElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    const nextBtn = buttons.find((b) => b.textContent?.includes('Next: Exam PDFs'))!;
    expect(nextBtn.disabled).toBe(false);
    nextBtn.click();

    expect(spy).toHaveBeenCalled();
  });
});
