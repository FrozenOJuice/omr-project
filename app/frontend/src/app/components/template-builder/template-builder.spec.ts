import { TestBed } from '@angular/core/testing';
import { vi } from 'vitest';
import { of, Subject, throwError } from 'rxjs';
import { TemplateBuilder } from './template-builder';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ExamTemplateResponse, ExamTemplateUsageResponse } from '../../models/exam-template.model';

const existing: ExamTemplateResponse = {
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

const other: ExamTemplateResponse = {
  id: 'tmpl-2',
  name: 'Standard 1Q',
  created_by: 'user-1',
  question_config: { '1': { choices: ['A', 'B', 'C', 'D'] } },
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

const versionedBlueprint: ExamTemplateResponse = {
  ...existing,
  id: 'tmpl-3',
  blueprint: 'ubco_100',
  version_from_q1: true,
};

const emptyUsage: ExamTemplateUsageResponse = {
  template_id: 'tmpl-1',
  exam_count: 0,
  answer_key_count: 0,
  scan_count: 0,
  exams: [],
};

const usedUsage: ExamTemplateUsageResponse = {
  template_id: 'tmpl-1',
  exam_count: 1,
  answer_key_count: 1,
  scan_count: 2,
  exams: [
    {
      id: 'exam-1',
      name: 'Midterm',
      course_id: 'course-1',
      answer_key_count: 1,
      scan_count: 2,
    },
  ],
};

function setup(listReturn = of([] as ExamTemplateResponse[])) {
  const service = {
    listMyTemplates: vi.fn(() => listReturn),
    createTemplate: vi.fn(() => of(existing)),
    updateTemplate: vi.fn(() => of(existing)),
    createUbco100Template: vi.fn(() => of({ ...existing, total_questions: 100 })),
    getTemplateUsage: vi.fn(() => of(emptyUsage)),
    deleteTemplate: vi.fn(() => of(void 0)),
    archiveTemplate: vi.fn(() =>
      of({ ...existing, archived_at: '2026-07-25T12:00:00Z' }),
    ),
    restoreTemplate: vi.fn(() => of(existing)),
    generatePdf: vi.fn(() =>
      of<ExamTemplateResponse>({ ...existing, generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf' }),
    ),
    previewPdf: vi.fn(() => of(new Blob(['%PDF-1.4']))),
  };

  TestBed.configureTestingModule({
    imports: [TemplateBuilder],
    providers: [{ provide: ExamTemplateService, useValue: service }],
  });

  const fixture = TestBed.createComponent(TemplateBuilder);
  const component = fixture.componentInstance;
  fixture.detectChanges(); // ngOnInit
  return { fixture, component, service };
}

function pointerEvent(pointerId: number, clientY: number): PointerEvent {
  return { pointerId, clientY, preventDefault: vi.fn() } as unknown as PointerEvent;
}

describe('TemplateBuilder', () => {
  it('keeps deletion dragging separate from adding a question', () => {
    const { component } = setup();
    component.startCustom(10);
    const sheet = document.createElement('div');
    const firstRow = document.createElement('div');
    firstRow.className = 'sheet-question-row';
    // offsetTop is deliberately unrelated to the viewport position; mixing
    // these coordinate systems caused a click on Q9 to select Q9 onward.
    Object.defineProperty(firstRow, 'offsetTop', { value: 900 });
    firstRow.getBoundingClientRect = () => ({ top: 140, height: 32 }) as DOMRect;
    sheet.append(firstRow);
    sheet.getBoundingClientRect = () => ({ top: 100, bottom: 5000 }) as DOMRect;
    sheet.setPointerCapture = vi.fn();
    sheet.hasPointerCapture = vi.fn(() => true);
    sheet.releasePointerCapture = vi.fn();

    component.beginQuestionGesture(8, pointerEvent(1, 100 + 40 + 8.5 * 32), sheet);
    expect(component.selectedQuestions()).toEqual([8]);

    component.moveQuestionGesture(pointerEvent(1, 100 + 40 + 9.5 * 32));
    expect(component.selectedQuestions()).toEqual([8, 9]);

    component.moveQuestionGesture(pointerEvent(1, 100 + 40 + 10.5 * 32));
    expect(component.selectedQuestions()).toEqual([8, 9]);
    component.endQuestionGesture(pointerEvent(1, 100 + 40 + 10.5 * 32));

    component.addQuestion();
    expect(component.questions()).toHaveLength(11);
    expect(component.questions()[10]).toEqual(['A', 'B', 'C', 'D', 'E']);
    expect(component.desiredCount()).toBe(11);
    expect(component.selectedQuestions()).toEqual([]);
  });

  it('keeps the add button at the same viewport position after adding a row', () => {
    const { component } = setup();
    component.startCustom(3);
    const sheet = document.createElement('div');
    const addButton = document.createElement('button');
    sheet.scrollTop = 80;
    let buttonTop = 420;
    addButton.getBoundingClientRect = () => ({ top: buttonTop }) as DOMRect;
    const animationFrame = vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => {
      buttonTop = 452;
      callback(0);
      return 1;
    });

    component.addQuestion(sheet, addButton);

    expect(component.questions()).toHaveLength(4);
    expect(sheet.scrollTop).toBe(112);
    animationFrame.mockRestore();
  });

  beforeEach(() => vi.clearAllMocks());

  it('creates and loads my templates', () => {
    const { component, service } = setup(of([existing]));
    expect(service.listMyTemplates).toHaveBeenCalledWith(true);
    expect(component.myTemplates()).toEqual([existing]);
  });

  it('archives a template and removes it from the active view', () => {
    const { component, service } = setup(of([existing]));

    component.archive(existing);

    expect(service.archiveTemplate).toHaveBeenCalledWith('tmpl-1');
    expect(component.myTemplates()[0].archived_at).not.toBeNull();
    expect(component.visibleTemplates()).toEqual([]);
  });

  it('flushes a pending autosave before archiving a template', () => {
    vi.useFakeTimers();
    try {
      const { fixture, component, service } = setup(of([existing]));
      const pendingSave = new Subject<ExamTemplateResponse>();
      const renamed = { ...existing, name: 'Renamed before archive' };
      service.updateTemplate.mockReturnValueOnce(pendingSave.asObservable());
      service.archiveTemplate.mockReturnValueOnce(
        of({ ...renamed, archived_at: '2026-07-25T12:00:00Z' }),
      );

      component.edit(existing);
      component.templateName.set(renamed.name);
      fixture.detectChanges();
      expect(vi.getTimerCount()).toBeGreaterThan(0);

      component.archive(existing);

      expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-1', {
        name: 'Renamed before archive',
      });
      expect(service.archiveTemplate).not.toHaveBeenCalled();

      pendingSave.next(renamed);
      pendingSave.complete();

      expect(service.archiveTemplate).toHaveBeenCalledWith('tmpl-1');
      expect(component.myTemplates()[0]).toEqual({
        ...renamed,
        archived_at: '2026-07-25T12:00:00Z',
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it('shows and restores archived templates', () => {
    const archived = { ...existing, archived_at: '2026-07-25T12:00:00Z' };
    const { component, service } = setup(of([archived]));
    component.setArchiveView(true);

    expect(component.visibleTemplates()).toEqual([archived]);
    component.restore(archived);

    expect(service.restoreTemplate).toHaveBeenCalledWith('tmpl-1');
    expect(component.visibleTemplates()).toEqual([]);
  });

  it('applyDesiredCount grows the question list with the default choice count', () => {
    const { component } = setup();
    component.desiredCount.set(3);
    component.applyDesiredCount();
    expect(component.questions().length).toBe(3);
    expect(component.questions()[0]).toEqual(['A', 'B', 'C', 'D', 'E']);
  });

  it('clears deletion selections when the question count is applied', () => {
    const { component } = setup();
    component.startCustom(5);
    component.selectedQuestions.set([3, 4]);
    component.desiredCount.set(2);

    component.applyDesiredCount();

    expect(component.questions()).toHaveLength(2);
    expect(component.selectedQuestions()).toEqual([]);
  });

  it('caps custom templates at 200 questions', () => {
    const { component } = setup();
    component.startCustom(250);
    expect(component.questions()).toHaveLength(200);
    expect(component.desiredCount()).toBe(200);

    component.addQuestion();
    expect(component.questions()).toHaveLength(200);

    component.desiredCount.set(500);
    component.applyDesiredCount();
    expect(component.questions()).toHaveLength(200);
    expect(component.desiredCount()).toBe(200);
  });

  it('creates one default question when every question is deleted', () => {
    const { component } = setup();
    component.startCustom(3);
    component.setChoiceCount(0, 2);
    component.selectedQuestions.set([0, 1, 2]);

    component.deleteSelectedQuestions();

    expect(component.questions()).toEqual([['A', 'B', 'C', 'D', 'E']]);
    expect(component.desiredCount()).toBe(1);
    expect(component.selectedQuestions()).toEqual([]);
  });

  it('keeps one default question in every section after deleting its rows', () => {
    const { component } = setup();
    component.startCustom(1);
    component.addSection('true_false');
    component.selectedQuestions.set([0, 1]);

    component.deleteSelectedQuestions();

    expect(component.questions()).toEqual([
      ['A', 'B', 'C', 'D', 'E'],
      ['T', 'F'],
    ]);
    expect(component.sectionRows().map((row) => row.questionIndexes.length)).toEqual([1, 1]);
  });

  it.each(['Delete', 'Backspace'])('deletes selected questions with the %s key', (key) => {
    const { component } = setup();
    component.startCustom(3);
    component.selectedQuestions.set([1]);
    const event = { key, target: document.body, preventDefault: vi.fn() } as unknown as KeyboardEvent;

    component.handleDeleteShortcut(event);

    expect(component.questions()).toHaveLength(2);
    expect(event.preventDefault).toHaveBeenCalled();
  });

  it('does not use the delete shortcut while editing an input', () => {
    const { component } = setup();
    component.startCustom(3);
    component.selectedQuestions.set([1]);
    const event = {
      key: 'Backspace',
      target: document.createElement('input'),
      preventDefault: vi.fn(),
    } as unknown as KeyboardEvent;

    component.handleDeleteShortcut(event);

    expect(component.questions()).toHaveLength(3);
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it('applies a section question count when Enter is pressed', () => {
    const { fixture, component } = setup();
    component.startCustom(2);
    const section = component.sections()[0];
    component.setSectionQuestionCount(section.id, 4);
    fixture.detectChanges();

    const input: HTMLInputElement = fixture.nativeElement.querySelector('.section-question-count-control input');
    input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));

    expect(component.questions()).toHaveLength(4);
  });

  it('setChoiceCount changes one question only', () => {
    const { component } = setup();
    component.desiredCount.set(2);
    component.applyDesiredCount();
    component.setChoiceCount(0, 2);
    expect(component.questions()[0]).toEqual(['A', 'B']);
    expect(component.questions()[1].length).toBe(5);
  });

  it('explains the option-count marker and labels each option-count action', () => {
    const { fixture, component } = setup();
    component.startCustom(1);
    fixture.detectChanges();

    const help = fixture.nativeElement.querySelector('.option-count-help') as HTMLElement;
    const endpoint = fixture.nativeElement.querySelector('.sheet-cell.endpoint') as HTMLButtonElement;
    expect(help.textContent).toContain('shows how many answer options');
    expect(endpoint.textContent?.trim()).toBe('5');
    expect(endpoint.getAttribute('aria-label')).toBe('Question 1: set option count to 5');
  });


  it('create path sends name, question_config, sections, and n_versions', () => {
    const { component, service } = setup();
    component.templateName.set('My layout');
    component.nVersions.set(2);
    component.desiredCount.set(1);
    component.applyDesiredCount();
    component.save();
    expect(service.createTemplate).toHaveBeenCalledWith({
      name: 'My layout',
      question_config: { '1': { choices: ['A', 'B', 'C', 'D', 'E'] } },
      n_versions: 2,
      sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1'] }],
    });
  });

  it('does not PATCH an unchanged existing template', () => {
    const { component, service } = setup(of([existing]));
    component.edit(existing);
    component.save();
    expect(service.updateTemplate).not.toHaveBeenCalled();
    expect(service.createTemplate).not.toHaveBeenCalled();
    expect(component.saved()).toBe(true);
  });

  it('keeps the PDF preview collapsed until it is requested', () => {
    const { fixture, component, service } = setup(of([existing]));
    component.edit(existing);
    fixture.detectChanges();

    expect(fixture.nativeElement.querySelector('.preview-panel')).toBeNull();
    expect(service.previewPdf).not.toHaveBeenCalled();

    const toggle: HTMLButtonElement = fixture.nativeElement.querySelector('.preview-toggle');
    toggle.click();
    fixture.detectChanges();

    expect(service.previewPdf).toHaveBeenCalledWith('tmpl-1');
    expect(fixture.nativeElement.querySelector('.preview-panel')).not.toBeNull();
  });

  it('forces the PDF viewer sidebar closed so browsers that open it (e.g. Firefox) don\'t show a duplicated-looking thumbnail pane', () => {
    const { fixture, component, service } = setup(of([existing]));
    component.edit(existing);
    fixture.detectChanges();

    const toggle: HTMLButtonElement = fixture.nativeElement.querySelector('.preview-toggle');
    toggle.click();
    fixture.detectChanges();

    expect(service.previewPdf).toHaveBeenCalledWith('tmpl-1');
    const iframe: HTMLIFrameElement = fixture.nativeElement.querySelector('.preview-panel iframe');
    expect(iframe.src).toMatch(/#pagemode=none&navpanes=0&toolbar=0$/);
  });

  it('renaming an existing template sends only the changed name', () => {
    const { component, service } = setup(of([existing]));
    component.edit(existing);
    component.templateName.set('Renamed Layout');
    component.save();
    expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-1', { name: 'Renamed Layout' });
    expect(service.createTemplate).not.toHaveBeenCalled();
  });

  it('updates the version count for an unused custom template', () => {
    const updated = { ...existing, n_versions: 2 };
    const { component, service } = setup(of([existing]));
    service.updateTemplate.mockReturnValueOnce(of(updated));
    component.edit(existing);
    component.nVersions.set(2);

    component.save();

    expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-1', { n_versions: 2 });
    expect(component.savedNVersions()).toBe(2);
  });

  it('locks version editing when a custom template is assigned to an exam', () => {
    const { fixture, component, service } = setup(of([existing]));
    service.getTemplateUsage.mockReturnValueOnce(of(usedUsage));

    component.edit(existing);
    fixture.detectChanges();
    fixture.detectChanges();

    const input: HTMLInputElement = fixture.nativeElement.querySelector(
      'input[type="number"][max="26"]',
    );
    expect(component.versionCountLocked()).toBe(true);
    expect(input.readOnly).toBe(true);
    expect(fixture.nativeElement.textContent).toContain('Locked after assignment');
  });

  it('editing an existing template layout sends question_config and sections', () => {
    const { component, service } = setup(of([existing]));
    component.edit(existing);
    component.setChoiceCount(0, 5);
    component.save();
    expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-1', {
      question_config: {
        '1': { choices: ['A', 'B', 'C', 'D', 'E'] },
        '2': { choices: ['A', 'B', 'C', 'D'] },
      },
      sections: [{ id: 'section-1', name: 'Section 1', type: 'multiple_choice', question_ids: ['1', '2'] }],
    });
  });

  it('adds and renders a section with a starter question', () => {
    const { fixture, component } = setup();
    component.startCustom(2);
    component.addSection();
    fixture.detectChanges();

    expect(component.sections().map((section) => section.name)).toEqual(['Section 1', 'Section 2']);
    expect(component.questions()).toHaveLength(3);
    expect(fixture.nativeElement.querySelectorAll('.sheet-section-header')).toHaveLength(2);
  });

  it('does not reuse a section name after deleting a middle section', () => {
    const { component } = setup();
    component.startCustom(1);
    component.addSection();
    component.addSection();
    component.requestDeleteSection(component.sections()[1]);
    component.confirmDeleteSection();

    component.addSection();

    expect(component.sections().map(({ name }) => name)).toEqual([
      'Section 1',
      'Section 3',
      'Section 4',
    ]);
  });

  it('adds a True/False section with only T and F columns', () => {
    const { fixture, component } = setup();
    component.startCustom(1);
    component.addSection('true_false');
    fixture.detectChanges();

    expect(component.sections()[1].type).toBe('true_false');
    expect(component.questions()[1]).toEqual(['T', 'F']);
    const grids = fixture.nativeElement.querySelectorAll('.sheet-grid');
    expect(Array.from(grids[1].querySelectorAll('.sheet-header')).map(
      (header) => (header as HTMLElement).textContent?.trim(),
    )).toEqual(['T', 'F']);
  });

  it('sets the number of questions independently for each section', () => {
    const { component } = setup();
    component.startCustom(2);
    component.addSection('true_false');
    const trueFalseSection = component.sections()[1];

    component.setSectionQuestionCount(trueFalseSection.id, 4);
    component.applySectionQuestionCount(trueFalseSection.id);

    expect(component.sectionRows()[0].questionIndexes).toHaveLength(2);
    expect(component.sectionRows()[1].questionIndexes).toHaveLength(4);
    expect(component.questions().slice(2)).toEqual(Array.from({ length: 4 }, () => ['T', 'F']));
  });

  it('keeps section question counts within the 200-question template limit', () => {
    const { component } = setup();
    component.startCustom(199);
    component.addSection('true_false');
    const trueFalseSection = component.sections()[1];

    component.setSectionQuestionCount(trueFalseSection.id, 10);
    component.applySectionQuestionCount(trueFalseSection.id);

    expect(component.questions()).toHaveLength(200);
    expect(component.sectionQuestionCount(trueFalseSection.id)).toBe(1);
  });

  it('confirms a section type change before resetting its choices', () => {
    const { component } = setup();
    component.startCustom(2);
    const section = component.sections()[0];

    component.requestSectionTypeChange(section, 'true_false');
    expect(component.sections()[0].type).toBe('multiple_choice');
    expect(component.questions()[0]).toEqual(['A', 'B', 'C', 'D', 'E']);

    component.confirmSectionTypeChange();
    expect(component.sections()[0].type).toBe('true_false');
    expect(component.questions()).toEqual([['T', 'F'], ['T', 'F']]);
  });

  it('moves selected questions between sections', () => {
    const { component } = setup();
    component.startCustom(2);
    component.addSection();
    const target = component.sections()[1];
    component.selectedQuestions.set([0]);
    component.moveTargetSectionId = target.id;

    component.moveSelectedQuestions();

    expect(component.sectionRows()[1].questionIndexes).toHaveLength(2);
    expect(component.selectedQuestions()).toEqual([]);
  });

  it('does not move every question out of a section', () => {
    const { component } = setup();
    component.startCustom(1);
    component.addSection();
    component.selectedQuestions.set([0]);
    component.moveTargetSectionId = component.sections()[1].id;

    component.moveSelectedQuestions();

    expect(component.sectionRows().map((row) => row.questionIndexes.length)).toEqual([1, 1]);
    expect(component.error()).toContain('needs at least one question');
  });

  it('requires confirmation before deleting a section and its questions', () => {
    const { component } = setup();
    component.startCustom(2);
    component.addSection();
    const section = component.sections()[1];

    component.requestDeleteSection(section);
    expect(component.sectionDeleteCandidate()).toEqual(section);
    expect(component.questions()).toHaveLength(3);

    component.confirmDeleteSection();
    expect(component.sections()).toHaveLength(1);
    expect(component.questions()).toHaveLength(2);
  });

  it('renames and reorders sections', () => {
    const { component } = setup();
    component.startCustom(1);
    component.addSection();
    const second = component.sections()[1];
    component.renameSection(second.id, 'Written response');
    component.moveSection(second.id, -1);

    expect(component.sections()[0].name).toBe('Written response');
    expect(component.questionSectionIds()[0]).toBe(second.id);
  });

  it('validates section names before saving', () => {
    const { component } = setup();
    component.startCustom(1);
    component.templateName.set('Quiz');
    component.renameSection(component.sections()[0].id, 'x'.repeat(101));

    expect(component.validationError()).toContain('100 characters');
  });

  it('can shrink an unused saved template layout', () => {
    const { component } = setup(of([existing]));
    component.edit(existing); // 2 saved questions
    component.desiredCount.set(1);
    component.applyDesiredCount();
    expect(component.questions().length).toBe(1);
    expect(component.error()).toBe('');
  });

  it('does not save without a name', () => {
    const { component, service } = setup();
    component.desiredCount.set(1);
    component.applyDesiredCount();
    component.save();
    expect(service.createTemplate).not.toHaveBeenCalled();
    expect(component.error()).toContain('name');
  });

  it('UBC preset creates server-side and loads the result for editing', () => {
    const { component, service } = setup();
    component.useUbco100Preset();
    expect(service.createUbco100Template).toHaveBeenCalledWith(false, '', 4);
    expect(component.editingId()).toBe('tmpl-1');
    expect(component.saved()).toBe(true);
  });

  it('UBC preset forwards the "use Q1 as version" toggle and the chosen name', () => {
    const { component, service } = setup();
    component.templateName.set('Midterm 1');
    component.versionFromQ1.set(true);
    component.nVersions.set(3);
    component.useUbco100Preset();
    expect(service.createUbco100Template).toHaveBeenCalledWith(true, 'Midterm 1', 3);
  });

  it('requires two to five versions when UBC Q1 selects the version', () => {
    const { component, service } = setup();
    component.versionFromQ1.set(true);
    component.nVersions.set(1);

    component.useUbco100Preset();

    expect(service.createUbco100Template).not.toHaveBeenCalled();
    expect(component.error()).toContain('between 2 and 5');
  });

  it('editing a blueprint template only sends the name on save, never question_config', () => {
    const { component, service } = setup(of([versionedBlueprint]));
    component.edit(versionedBlueprint);
    component.templateName.set('Renamed');
    component.save();
    expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-3', { name: 'Renamed' });
  });

  it('updates the version count for an unused UBCO template', () => {
    const updated = { ...versionedBlueprint, n_versions: 2 };
    const { component, service } = setup(of([versionedBlueprint]));
    service.updateTemplate.mockReturnValueOnce(of(updated));
    component.edit(versionedBlueprint);
    component.nVersions.set(2);

    component.save();

    expect(service.updateTemplate).toHaveBeenCalledWith('tmpl-3', { n_versions: 2 });
    expect(component.savedNVersions()).toBe(2);
  });

  it('shows Q1 as the exam version when editing a version_from_q1 template', () => {
    const blueprintTemplate: ExamTemplateResponse = {
      ...versionedBlueprint,
      question_config: { '2': { choices: ['A', 'B', 'C', 'D', 'E'] } },
    };
    const { fixture, component } = setup(of([blueprintTemplate]));
    component.edit(blueprintTemplate);
    fixture.detectChanges();
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('Q1');
    expect(text).toContain('Exam version');
  });

  it('does not show the reserved Q1 row for a template without version_from_q1', () => {
    const { fixture, component } = setup(of([existing]));
    component.edit(existing);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('.q-row--reserved')).toBeNull();
  });

  it('requestDelete loads usage and keeps the template until confirmed', () => {
    const { component, service } = setup(of([existing]));
    component.requestDelete(existing);
    expect(service.getTemplateUsage).toHaveBeenCalledWith('tmpl-1');
    expect(service.deleteTemplate).not.toHaveBeenCalled();
    expect(component.deleteCandidate()).toEqual(existing);
    expect(component.deleteUsage()).toEqual(emptyUsage);
    expect(component.myTemplates()).toEqual([existing]);
  });

  it('confirmDelete removes an unused template from the list', () => {
    const { component, service } = setup(of([existing]));
    component.requestDelete(existing);
    component.confirmDelete();
    expect(service.deleteTemplate).toHaveBeenCalledWith('tmpl-1', false);
    expect(component.myTemplates()).toEqual([]);
    expect(component.deleteCandidate()).toBeNull();
  });

  it('confirmDelete emits when a template is deleted', () => {
    const { component } = setup(of([existing]));
    const spy = vi.fn();
    component.templateDeleted.subscribe(spy);

    component.requestDelete(existing);
    component.confirmDelete();

    expect(spy).toHaveBeenCalledOnce();
  });

  it('confirmDelete force deletes a used template after confirmation', () => {
    const { component, service } = setup(of([existing]));
    service.getTemplateUsage.mockReturnValueOnce(of(usedUsage));
    component.requestDelete(existing);
    component.confirmDelete();
    expect(service.deleteTemplate).toHaveBeenCalledWith('tmpl-1', true);
    expect(component.myTemplates()).toEqual([]);
  });

  it('cancelDelete clears pending delete state', () => {
    const { component } = setup(of([existing]));
    component.requestDelete(existing);
    component.cancelDelete();
    expect(component.deleteCandidate()).toBeNull();
    expect(component.deleteUsage()).toBeNull();
  });

  it('keeps the confirmation open with usage details when delete returns template_in_use', () => {
    const { component, service } = setup(of([existing]));
    service.deleteTemplate.mockReturnValueOnce(throwError(() => ({
      status: 409,
      error: {
        error: {
          code: 'template_in_use',
          details: usedUsage,
        },
      },
    })));

    component.requestDelete(existing);
    component.confirmDelete();

    expect(service.deleteTemplate).toHaveBeenCalledWith('tmpl-1', false);
    expect(component.deleteCandidate()).toEqual(existing);
    expect(component.deleteUsage()).toEqual(usedUsage);
    expect(component.error()).toContain('used');
  });

  it('keeps the confirmation open when template_in_use is detail-wrapped', () => {
    const { component, service } = setup(of([existing]));
    service.deleteTemplate.mockReturnValueOnce(throwError(() => ({
      status: 409,
      error: {
        detail: {
          code: 'template_in_use',
          details: usedUsage,
        },
      },
    })));

    component.requestDelete(existing);
    component.confirmDelete();

    expect(component.deleteCandidate()).toEqual(existing);
    expect(component.deleteUsage()).toEqual(usedUsage);
    expect(component.error()).toContain('used');
  });

  it('reloads usage when delete returns a 409 without details', () => {
    const { component, service } = setup(of([existing]));
    service.getTemplateUsage
      .mockReturnValueOnce(of(emptyUsage))
      .mockReturnValueOnce(of(usedUsage));
    service.deleteTemplate.mockReturnValueOnce(throwError(() => ({
      status: 409,
      error: { detail: 'Conflict' },
    })));

    component.requestDelete(existing);
    component.confirmDelete();

    expect(service.getTemplateUsage).toHaveBeenCalledTimes(2);
    expect(service.getTemplateUsage).toHaveBeenNthCalledWith(2, 'tmpl-1');
    expect(component.deleteCandidate()).toEqual(existing);
    expect(component.deleteUsage()).toEqual(usedUsage);
    expect(component.error()).toContain('used');
  });

  it('shows an error when saving fails', () => {
    const { component, service } = setup();
    service.createTemplate.mockReturnValueOnce(throwError(() => new Error()));
    component.templateName.set('X');
    component.desiredCount.set(1);
    component.applyDesiredCount();
    component.save();
    expect(component.error()).toContain('Failed');
  });

  it('shows a clear message when a locked template layout cannot be changed', () => {
    const { component, service } = setup(of([existing]));
    service.updateTemplate.mockReturnValueOnce(throwError(() => ({
      status: 409,
      error: {
        error: {
          code: 'template_locked',
        },
      },
    })));

    component.edit(existing);
    component.setChoiceCount(0, 5);
    component.save();

    expect(component.error()).toContain('layout is locked');
  });

  // generatePdf

  it('generatePdf does nothing without an editingId', () => {
    const { component, service } = setup();
    component.generatePdf();
    expect(service.generatePdf).not.toHaveBeenCalled();
  });

  it('generatePdf calls the service and stores the returned generated_pdf_path', () => {
    const { component, service } = setup(of([existing]));
    component.edit(existing);
    component.generatePdf();
    expect(service.generatePdf).toHaveBeenCalledWith('tmpl-1');
    expect(component.generatedPdfPath()).toBe('generated/tmpl-1/bubble_sheet.pdf');
  });

  it('generatePdf sets an error on failure', () => {
    const { component, service } = setup(of([existing]));
    service.generatePdf.mockReturnValueOnce(throwError(() => new Error()));
    component.edit(existing);
    component.generatePdf();
    expect(component.error()).toContain('Failed');
    expect(component.isGeneratingPdf()).toBe(false);
  });

  // edit() reflects generation state

  it('edit() picks up the template generated_pdf_path', () => {
    const { component } = setup(of([existing]));
    component.edit({ ...existing, generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf' });
    expect(component.generatedPdfPath()).toBe('generated/tmpl-1/bubble_sheet.pdf');
  });

  it('startNew() clears generatedPdfPath', () => {
    const { component } = setup(of([existing]));
    component.edit({ ...existing, generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf' });
    component.startNew();
    expect(component.generatedPdfPath()).toBeNull();
  });

  // stale in-flight responses must not clobber a template switched to in the meantime

  it('generatePdf ignores a stale response after switching templates, but still clears the loading flag and updates the list', () => {
    const { component, service } = setup(of([existing, other]));
    const pending = new Subject<ExamTemplateResponse>();
    service.generatePdf.mockReturnValueOnce(pending.asObservable());

    component.edit(existing);
    component.generatePdf();
    expect(component.isGeneratingPdf()).toBe(true);

    component.edit(other); // user switches to template B before A's response arrives
    pending.next({ ...existing, generated_pdf_path: 'generated/tmpl-1/bubble_sheet.pdf' });
    pending.complete();

    // loading flag always clears, and the background list is kept in sync...
    expect(component.isGeneratingPdf()).toBe(false);
    expect(component.myTemplates().find((t) => t.id === 'tmpl-1')?.generated_pdf_path).toBe(
      'generated/tmpl-1/bubble_sheet.pdf',
    );
    // ...but the form currently showing template B must not be touched by A's response
    expect(component.editingId()).toBe('tmpl-2');
    expect(component.generatedPdfPath()).toBeNull();
  });

  it('generatePdf clears the loading flag on a stale error without surfacing it on the new template', () => {
    const { component, service } = setup(of([existing, other]));
    const pending = new Subject<ExamTemplateResponse>();
    service.generatePdf.mockReturnValueOnce(pending.asObservable());

    component.edit(existing);
    component.generatePdf();
    component.edit(other);
    pending.error(new Error('boom'));

    expect(component.isGeneratingPdf()).toBe(false);
    expect(component.error()).toBe('');
  });

  it('save ignores a stale response after switching templates, but still clears isSaving and updates the list', () => {
    const { component, service } = setup(of([existing, other]));
    const pending = new Subject<ExamTemplateResponse>();
    service.updateTemplate.mockReturnValueOnce(pending.asObservable());

    component.edit(existing);
    component.templateName.set('Rename before switching');
    component.save();
    expect(component.isSaving()).toBe(true);

    component.edit(other); // user switches to template B before A's save response arrives
    const updated = { ...existing, name: 'Renamed while switching' };
    pending.next(updated);
    pending.complete();

    expect(component.isSaving()).toBe(false);
    expect(component.myTemplates().find((t) => t.id === 'tmpl-1')?.name).toBe('Renamed while switching');
    // template B's form must remain what the user is currently looking at
    expect(component.editingId()).toBe('tmpl-2');
    expect(component.templateName()).toBe('Standard 1Q');
  });

  it('save clears isSaving on a stale error without surfacing it on the new template', () => {
    const { component, service } = setup(of([existing, other]));
    const pending = new Subject<ExamTemplateResponse>();
    service.updateTemplate.mockReturnValueOnce(pending.asObservable());

    component.edit(existing);
    component.templateName.set('Rename before stale error');
    component.save();
    component.edit(other);
    pending.error(new Error('boom'));

    expect(component.isSaving()).toBe(false);
    expect(component.error()).toBe('');
  });
});
