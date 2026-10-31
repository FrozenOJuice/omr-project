import { ChangeDetectionStrategy, Component, computed, effect, EventEmitter, inject, OnDestroy, OnInit, Output, signal, untracked } from '@angular/core';
import { DomSanitizer, SafeResourceUrl } from '@angular/platform-browser';
import { FormsModule } from '@angular/forms';
import { ExamTemplateService } from '../../services/exam-template.service';
import {
  ExamTemplateResponse,
  ExamTemplateUsageResponse,
  QuestionConfigItem,
  TemplateSection,
  TemplateSectionType,
  UpdateExamTemplateRequest,
} from '../../models/exam-template.model';

const DEFAULT_CHOICE_COUNT = 5; // UBC sheets use A-E
const MAX_QUESTION_COUNT = 200;
const DEFAULT_MAX_OPTION_COUNT = 26; // matches the sheet's old fixed A-Z limit
const OPTION_COUNT_CEILING = 100; // sanity bound on how high the "max options" field itself can go
// Exam versions stay single-letter (A-Z), separately capped at 26 by the backend schema.
const VERSION_LABELS = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'];

// Past Z, options are labelled A1, A2, ... A9, B1, B2, ... instead of a
// second letter (AA, AB, ...). A printed digit is much more consistent in
// how much ink it takes up than a second letter would be (a "W" or "M"
// covers a lot more of the bubble than an "I" does), so bubbles further
// into the alphabet don't start from a heavier baseline before anyone's
// even marked them, which would eat into the OMR scanner's fill margin.
// 0 is skipped since it can be mistaken for the letter O.
function optionLabel(index: number): string {
  if (index < 26) return String.fromCharCode(65 + index);
  const extended = index - 26;
  const letter = String.fromCharCode(65 + Math.floor(extended / 9));
  const digit = (extended % 9) + 1;
  return `${letter}${digit}`;
}

function labelsFor(count: number): string[] {
  return Array.from({ length: count }, (_, i) => optionLabel(i));
}

interface QuestionSelectionGesture {
  pointerId: number;
  anchorIndex: number;
  unselect: boolean;
  baseSelection: number[];
  sheet: HTMLElement;
}

interface SectionDraft {
  id: string;
  name: string;
  type: TemplateSectionType;
}

interface SectionTypeChange {
  section: SectionDraft;
  type: TemplateSectionType;
}

@Component({
  selector: 'app-template-builder',
  imports: [FormsModule],
  templateUrl: './template-builder.html',
  styleUrl: './template-builder.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class TemplateBuilder implements OnInit, OnDestroy {
  private templateService = inject(ExamTemplateService);
  private sanitizer = inject(DomSanitizer);

  // A few seconds after the user stops editing, this saves the draft and (if
  // the layout changed) regenerates the PDF, so a template stays ready to
  // use without anyone having to click anything. Generating only locks the
  // question layout once the template is actually attached to an exam, so
  // doing this automatically is safe.
  private static readonly AUTOSAVE_DELAY_MS = 3000;
  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      this.templateName();
      this.nVersions();
      this.questions();
      this.sections();
      this.questionSectionIds();
      // scheduleAutosave() also reads other signals (isSaving, the saved
      // baselines) to decide whether to schedule. Those must not become
      // effect dependencies too, or a save toggling isSaving would
      // retrigger this effect and reschedule the timer forever.
      untracked(() => this.scheduleAutosave());
    });
  }

  @Output() close = new EventEmitter<void>();
  @Output() templateDeleted = new EventEmitter<void>();

  // A template is a reusable bubble-sheet layout: a name plus how many
  // questions and how many choices each has. Answer keys are defined per
  // exam, not here.

  readonly myTemplates = signal<ExamTemplateResponse[]>([]);
  readonly showArchived = signal(false);
  readonly visibleTemplates = computed(() =>
    this.myTemplates().filter((template) =>
      this.showArchived()
        ? template.archived_at !== null
        : template.archived_at === null,
    ),
  );
  readonly isLoading = signal(false);
  readonly isSaving = signal(false);
  readonly error = signal('');
  readonly saved = signal(false);

  // Builder state — editingId null means we're creating a new template.
  readonly editingId = signal<string | null>(null);
  readonly savedTemplateName = signal('');
  readonly savedLayoutFingerprint = signal('');
  readonly savedNVersions = signal(4);
  readonly templateName = signal('');
  readonly nVersions = signal(4);
  readonly versionFromQ1 = signal(false); // UBC preset only: treat Q1 as the version selector
  readonly questions = signal<string[][]>([]); // choices per question, in order
  readonly sections = signal<SectionDraft[]>([]);
  readonly questionSectionIds = signal<string[]>([]);
  readonly sectionDeleteCandidate = signal<SectionDraft | null>(null);
  readonly sectionTypeChangeCandidate = signal<SectionTypeChange | null>(null);
  readonly sectionDeleteQuestionCount = computed(() => {
    const candidate = this.sectionDeleteCandidate();
    return candidate
      ? this.questionSectionIds().filter((sectionId) => sectionId === candidate.id).length
      : 0;
  });
  moveTargetSectionId = '';

  readonly sectionRows = computed(() =>
    this.sections().map((section) => ({
      section,
      questionIndexes: this.questionSectionIds()
        .map((sectionId, index) => sectionId === section.id ? index : -1)
        .filter((index) => index >= 0),
    })),
  );

  // Set while creating/editing a UBCO blueprint template. Its question layout
  // is fixed, while a Q1 version selector can use between two and five versions.
  readonly isBlueprint = signal(false);
  // Blueprint templates skip question keys (e.g. "2".."100"), so the array
  // position no longer matches the physical question number — track the
  // real keys to label rows correctly.
  readonly questionKeys = signal<string[]>([]);
  readonly showVersionsField = computed(() =>
    this.questions().length > 0 && (!this.isBlueprint() || this.versionFromQ1()),
  );
  readonly blueprintGridRows = computed(() =>
    Math.ceil((this.questions().length + (this.versionFromQ1() ? 1 : 0)) / 4),
  );
  readonly isCheckingVersionUsage = signal(false);
  readonly versionCountLocked = signal(false);
  readonly versionCountReadOnly = computed(
    () => this.isCheckingVersionUsage() || this.versionCountLocked(),
  );
  readonly ubcoVersionError = computed<string | null>(() => {
    if (!this.versionFromQ1()) return null;
    const count = this.nVersions();
    return Number.isInteger(count) && count >= 2 && count <= 5
      ? null
      : 'UBCO versions must be between 2 and 5.';
  });
  readonly lastVersionLabel = computed(() =>
    VERSION_LABELS[Math.min(26, Math.max(1, this.nVersions())) - 1],
  );

  readonly generatedPdfPath = signal<string | null>(null);
  readonly omrTemplateId = signal<string | null>(null);
  // True once there's genuinely nothing left to do for this template: it's
  // saved, nothing's changed since, and a PDF already exists (a save with no
  // changes can still be worth clicking if the PDF hasn't been generated yet).
  readonly nothingToDo = computed(() =>
    !!this.editingId() && !this.hasUnsavedChanges() && !!this.generatedPdfPath(),
  );
  // Multi-stage "is this template ready to go" summary, shown prominently
  // next to the template name rather than as a small pill easy to miss.
  readonly templateStatus = computed<{ label: string; tagClass: string } | null>(() => {
    if (this.isSaving()) return { label: 'Saving…', tagClass: 'tag-amber' };
    if (this.isGeneratingPdf()) return { label: 'Generating PDF…', tagClass: 'tag-amber' };
    if (!this.editingId()) return this.questions().length > 0 ? { label: 'Not saved yet', tagClass: 'tag-amber' } : null;
    if (this.hasUnsavedChanges()) return { label: 'Unsaved changes', tagClass: 'tag-amber' };
    if (this.omrTemplateId()) return { label: 'Registered', tagClass: 'tag-green' };
    if (this.generatedPdfPath()) return { label: 'Saved, PDF generated', tagClass: 'tag-green' };
    return { label: 'Saved', tagClass: 'tag-green' };
  });
  // Locked once an exam, answer key, or scan actually references this
  // template (or it's a blueprint). A generated PDF or OMR registration
  // alone doesn't lock anything, since both can be regenerated for free.
  // Set from the same usage check edit() already runs for
  // versionCountLocked, not from generatedPdfPath/omrTemplateId.
  readonly questionConfigLocked = signal(false);
  // Editing should also be blocked while the usage check is still in
  // flight, not just once it resolves locked. Otherwise there's a brief
  // window where a genuinely locked template looks editable.
  readonly gridEditingLocked = computed(
    () => this.questionConfigLocked() || this.isCheckingVersionUsage(),
  );
  readonly isGeneratingPdf = signal(false);
  readonly isCheckingDelete = signal(false);
  readonly isDeleting = signal(false);
  readonly deleteCandidate = signal<ExamTemplateResponse | null>(null);
  readonly deleteUsage = signal<ExamTemplateUsageResponse | null>(null);
  readonly archiveActionId = signal<string | null>(null);

  readonly previewUrl = signal<SafeResourceUrl | null>(null);
  readonly isLoadingPreview = signal(false);
  readonly showPreview = signal(false);
  // The raw blob: URL behind previewUrl, kept so it can be revoked once it's
  // no longer shown (browsers don't free these on their own).
  private previewObjectUrl: string | null = null;

  readonly desiredCount = signal(10);
  readonly sectionQuestionCounts = signal<Record<string, number>>({});
  readonly maxQuestionCount = MAX_QUESTION_COUNT;
  // How many options a question can be dragged/typed up to in this grid.
  // User-adjustable (not persisted) rather than a fixed constant, since
  // raising it widens the grid and the generated PDF wraps wide questions
  // onto extra lines instead of failing outright.
  readonly maxOptionCount = signal(DEFAULT_MAX_OPTION_COUNT);
  // Pending value for the "Max options" field, mirroring desiredCount's
  // relationship to questions().length. It only diverges from maxOptionCount
  // while the user is actively typing, until the Set button commits it.
  readonly desiredMaxOptionCount = signal(DEFAULT_MAX_OPTION_COUNT);
  readonly optionCountCeiling = OPTION_COUNT_CEILING;
  readonly maxOptionCountDirty = computed(() => this.desiredMaxOptionCount() !== this.maxOptionCount());
  readonly optionPreview = signal<{ question: number; count: number } | null>(null);
  readonly selectedQuestions = signal<number[]>([]);
  readonly atQuestionLimit = computed(() => this.questions().length >= MAX_QUESTION_COUNT);
  readonly optionColumns = computed(() => labelsFor(this.maxOptionCount()));
  readonly trueFalseColumns = ['T', 'F'];
  private isDraggingCells = false;
  private questionGesture: QuestionSelectionGesture | null = null;
  private questionPointerY = 0;
  private scrollFrame: number | null = null;
  private scrollTarget: HTMLElement | null = null;
  private scrollDelta = { x: 0, y: 0 };

  readonly validationError = computed<string | null>(() => {
    if (this.templateName().trim().length === 0) return 'Give the template a name.';
    if (this.questions().length === 0) return 'Add at least one question.';
    if (this.questions().length > MAX_QUESTION_COUNT) return `Templates support up to ${MAX_QUESTION_COUNT} questions.`;
    if (this.sections().length === 0) return 'Add at least one section.';
    if (this.sections().some((section) => !section.name.trim())) return 'Give every section a name.';
    if (this.sections().some((section) => section.name.trim().length > 100)) {
      return 'Section names must be 100 characters or fewer.';
    }
    const sectionNames = this.sections().map((section) => section.name.trim().toLowerCase());
    if (new Set(sectionNames).size !== sectionNames.length) return 'Section names must be unique.';
    if (this.sectionRows().some((row) => row.questionIndexes.length === 0)) return 'Every section needs at least one question.';
    const n = this.nVersions();
    if (!Number.isInteger(n) || n < 1 || n > 26) return 'Versions must be between 1 and 26.';
    return null;
  });

  readonly canSave = computed(() => this.validationError() === null && !this.isSaving());

  readonly deleteHasUsage = computed(() => {
    const usage = this.deleteUsage();
    return !!usage && (usage.exam_count > 0 || usage.answer_key_count > 0 || usage.scan_count > 0);
  });

  ngOnInit(): void {
    this.loadMyTemplates();
  }

  ngOnDestroy(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    if (this.previewObjectUrl) URL.revokeObjectURL(this.previewObjectUrl);
  }

  private loadPreview(id: string): void {
    if (this.previewObjectUrl) URL.revokeObjectURL(this.previewObjectUrl);
    this.previewObjectUrl = null;
    this.previewUrl.set(null);
    this.isLoadingPreview.set(true);
    this.templateService.previewPdf(id).subscribe({
      next: (blob) => {
        this.isLoadingPreview.set(false);
        if (this.editingId() !== id || !this.showPreview()) return;
        this.previewObjectUrl = URL.createObjectURL(blob);
        // Some browsers' built-in PDF viewers (notably Firefox's PDF.js) open
        // with the page-thumbnails sidebar visible by default, which reads as
        // a "doubled" render -- a small thumbnail pane next to the full page.
        // These PDF open-parameter fragments force it closed; Chrome/PDFium
        // (which doesn't show that sidebar anyway) just ignores them.
        const previewSrc = `${this.previewObjectUrl}#pagemode=none&navpanes=0&toolbar=0`;
        this.previewUrl.set(this.sanitizer.bypassSecurityTrustResourceUrl(previewSrc));
      },
      // Autosave triggers this same preview refresh after every layout
      // change, so a layout that can't actually render (e.g. too many
      // questions or options to fit the page) needs to surface here, right
      // away, rather than staying quiet until the next manual save happens
      // to also try generating the PDF.
      error: (err: unknown) => {
        this.isLoadingPreview.set(false);
        if (this.editingId() !== id) return;
        this.clearPreview();
        this.parseBlobError(err).then((parsed) => {
          if (this.editingId() !== id) return;
          this.error.set(this.errorMessage(parsed) ?? 'This layout could not be rendered as a PDF.');
        });
      },
    });
  }

  private clearPreview(): void {
    if (this.previewObjectUrl) URL.revokeObjectURL(this.previewObjectUrl);
    this.previewObjectUrl = null;
    this.previewUrl.set(null);
    this.isLoadingPreview.set(false);
  }

  togglePreview(): void {
    const id = this.editingId();
    if (!id || this.isBlueprint()) return;
    if (this.showPreview()) {
      this.showPreview.set(false);
      this.clearPreview();
      return;
    }
    this.showPreview.set(true);
    this.loadPreview(id);
  }

  private scheduleAutosave(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    if (!this.canSave() || !this.hasUnsavedChanges()) return;
    // Don't keep retrying a change that's already known to be rejected. A
    // plain rename is still fine, since it's never locked.
    const body = this.buildUpdateBody(
      this.templateName().trim(),
      this.buildQuestionConfig(),
      this.buildSections(),
    );
    if ('question_config' in body && this.gridEditingLocked()) return;
    if ('n_versions' in body && this.versionCountLocked()) return;
    this.autosaveTimer = setTimeout(() => {
      this.autosaveTimer = null;
      this.save(false);
    }, TemplateBuilder.AUTOSAVE_DELAY_MS);
  }

  readonly hasUnsavedChanges = computed(() => {
    if (!this.editingId()) return true; // nothing persisted yet, so a valid draft is always worth saving
    const body = this.buildUpdateBody(
      this.templateName().trim(),
      this.buildQuestionConfig(),
      this.buildSections(),
    );
    return Object.keys(body).length > 0;
  });

  private loadMyTemplates(): void {
    this.isLoading.set(true);
    this.templateService.listMyTemplates(true).subscribe({
      next: (templates) => {
        this.isLoading.set(false);
        this.myTemplates.set(templates);
      },
      error: () => {
        this.isLoading.set(false);
        this.error.set('Failed to load your templates.');
      },
    });
  }

  startNew(): void {
    this.showArchived.set(false);
    this.editingId.set(null);
    this.savedTemplateName.set('');
    this.savedLayoutFingerprint.set('');
    this.savedNVersions.set(4);
    this.templateName.set('');
    this.nVersions.set(4);
    this.versionFromQ1.set(false);
    this.questions.set([]);
    this.sections.set([]);
    this.questionSectionIds.set([]);
    this.sectionDeleteCandidate.set(null);
    this.sectionTypeChangeCandidate.set(null);
    this.moveTargetSectionId = '';
    this.desiredCount.set(10);
    this.maxOptionCount.set(DEFAULT_MAX_OPTION_COUNT);
    this.desiredMaxOptionCount.set(DEFAULT_MAX_OPTION_COUNT);
    this.sectionQuestionCounts.set({});
    this.generatedPdfPath.set(null);
    this.omrTemplateId.set(null);
    this.isBlueprint.set(false);
    this.questionKeys.set([]);
    this.isCheckingVersionUsage.set(false);
    this.versionCountLocked.set(false);
    this.questionConfigLocked.set(false);
    this.showPreview.set(false);
    this.saved.set(false);
    this.error.set('');
    this.selectedQuestions.set([]);
    this.clearPreview();
  }

  startCustom(count = this.desiredCount()): void {
    const questionCount = Math.min(MAX_QUESTION_COUNT, Math.max(1, Math.floor(count)));
    const section = this.newSection('Section 1');
    this.sections.set([section]);
    this.questions.set(Array.from({ length: questionCount }, () => labelsFor(DEFAULT_CHOICE_COUNT)));
    this.questionSectionIds.set(Array.from({ length: questionCount }, () => section.id));
    this.questionKeys.set(Array.from({ length: questionCount }, (_, index) => String(index + 1)));
    this.desiredCount.set(questionCount);
    this.sectionQuestionCounts.set({ [section.id]: questionCount });
    this.saved.set(false);
  }

  addSection(type: TemplateSectionType = 'multiple_choice'): void {
    if (this.gridEditingLocked() || this.questions().length >= MAX_QUESTION_COUNT) return;
    const section = this.newSection(this.nextSectionName(), type);
    this.sections.update((sections) => [...sections, section]);
    this.questions.update((questions) => [...questions, this.defaultChoices(type)]);
    this.questionSectionIds.update((sectionIds) => [...sectionIds, section.id]);
    this.normalizeQuestionOrder();
    this.desiredCount.set(this.questions().length);
    this.syncSectionQuestionCounts();
    this.saved.set(false);
  }

  private nextSectionName(): string {
    const existing = new Set(this.sections().map(({ name }) => name.toLowerCase()));
    let number = this.sections().length + 1;
    while (existing.has(`section ${number}`)) number++;
    return `Section ${number}`;
  }

  sectionQuestionCount(sectionId: string): number {
    return this.sectionQuestionCounts()[sectionId]
      ?? this.questionSectionIds().filter((id) => id === sectionId).length;
  }

  setSectionQuestionCount(sectionId: string, count: number): void {
    this.sectionQuestionCounts.update((counts) => ({ ...counts, [sectionId]: count }));
  }

  maxSectionQuestionCount(sectionId: string): number {
    const current = this.questionSectionIds().filter((id) => id === sectionId).length;
    return MAX_QUESTION_COUNT - (this.questions().length - current);
  }

  applySectionQuestionCount(sectionId: string): void {
    if (this.gridEditingLocked()) return;
    const section = this.sections().find(({ id }) => id === sectionId);
    if (!section) return;
    const currentIndexes = this.questionSectionIds()
      .map((id, index) => id === sectionId ? index : -1)
      .filter((index) => index >= 0);
    const requested = Math.floor(this.sectionQuestionCount(sectionId));
    const target = Math.min(
      this.maxSectionQuestionCount(sectionId),
      Math.max(1, Number.isFinite(requested) ? requested : currentIndexes.length),
    );

    if (target > currentIndexes.length) {
      const addCount = target - currentIndexes.length;
      this.questions.update((questions) => [
        ...questions,
        ...Array.from({ length: addCount }, () => this.defaultChoices(section.type)),
      ]);
      this.questionSectionIds.update((sectionIds) => [
        ...sectionIds,
        ...Array.from({ length: addCount }, () => sectionId),
      ]);
    } else if (target < currentIndexes.length) {
      const remove = new Set(currentIndexes.slice(target));
      this.questions.update((questions) => questions.filter((_, index) => !remove.has(index)));
      this.questionSectionIds.update((sectionIds) => sectionIds.filter((_, index) => !remove.has(index)));
    }

    this.normalizeQuestionOrder();
    this.desiredCount.set(this.questions().length);
    this.syncSectionQuestionCounts();
    this.selectedQuestions.set([]);
    this.saved.set(false);
  }

  requestSectionTypeChange(section: SectionDraft, type: TemplateSectionType): void {
    if (this.gridEditingLocked() || section.type === type) return;
    this.sectionTypeChangeCandidate.set({ section, type });
  }

  cancelSectionTypeChange(): void {
    this.sectionTypeChangeCandidate.set(null);
  }

  confirmSectionTypeChange(): void {
    const change = this.sectionTypeChangeCandidate();
    if (!change || this.gridEditingLocked()) return;
    const questionIndexes = new Set(
      this.questionSectionIds()
        .map((sectionId, index) => sectionId === change.section.id ? index : -1)
        .filter((index) => index >= 0),
    );
    this.sections.update((sections) => sections.map((section) =>
      section.id === change.section.id ? { ...section, type: change.type } : section,
    ));
    this.questions.update((questions) => questions.map((choices, index) =>
      questionIndexes.has(index) ? this.defaultChoices(change.type) : choices,
    ));
    this.cancelSectionTypeChange();
    this.optionPreview.set(null);
    this.saved.set(false);
  }

  renameSection(sectionId: string, name: string): void {
    if (this.gridEditingLocked()) return;
    this.sections.update((sections) =>
      sections.map((section) => section.id === sectionId ? { ...section, name } : section),
    );
    this.saved.set(false);
  }

  moveSection(sectionId: string, offset: -1 | 1): void {
    if (this.gridEditingLocked()) return;
    const sections = [...this.sections()];
    const index = sections.findIndex((section) => section.id === sectionId);
    const target = index + offset;
    if (index < 0 || target < 0 || target >= sections.length) return;
    [sections[index], sections[target]] = [sections[target], sections[index]];
    this.sections.set(sections);
    this.normalizeQuestionOrder();
    this.saved.set(false);
  }

  requestDeleteSection(section: SectionDraft): void {
    if (this.gridEditingLocked() || this.sections().length <= 1) return;
    this.sectionDeleteCandidate.set(section);
  }

  cancelDeleteSection(): void {
    this.sectionDeleteCandidate.set(null);
  }

  confirmDeleteSection(): void {
    const candidate = this.sectionDeleteCandidate();
    if (!candidate || this.gridEditingLocked() || this.sections().length <= 1) return;
    const keep = this.questionSectionIds().map((id) => id !== candidate.id);
    this.questions.set(this.questions().filter((_, index) => keep[index]));
    this.questionSectionIds.set(this.questionSectionIds().filter((_, index) => keep[index]));
    this.sections.update((sections) => sections.filter((section) => section.id !== candidate.id));
    this.cancelDeleteSection();
    this.normalizeQuestionOrder();
    this.desiredCount.set(this.questions().length);
    this.syncSectionQuestionCounts();
    this.selectedQuestions.set([]);
    this.saved.set(false);
  }

  moveSelectedQuestions(): void {
    if (this.gridEditingLocked()) return;
    const targetSection = this.sections().find((section) => section.id === this.moveTargetSectionId);
    if (!targetSection) return;
    const selected = new Set(this.selectedQuestions());
    const sectionTypes = new Map(this.sections().map((section) => [section.id, section.type]));
    const currentSectionIds = this.questionSectionIds();
    const emptiedSection = this.sections().find((section) =>
      section.id !== targetSection.id
      && currentSectionIds.some((sectionId) => sectionId === section.id)
      && currentSectionIds.every((sectionId, index) =>
        sectionId !== section.id || selected.has(index)
      ),
    );
    if (emptiedSection) {
      this.error.set(
        `${emptiedSection.name} needs at least one question. Leave one behind or delete the section.`,
      );
      return;
    }
    this.questionSectionIds.update((sectionIds) =>
      sectionIds.map((sectionId, index) => selected.has(index) ? this.moveTargetSectionId : sectionId),
    );
    this.questions.update((questions) => questions.map((choices, index) =>
      selected.has(index) && sectionTypes.get(currentSectionIds[index]) !== targetSection.type
        ? this.defaultChoices(targetSection.type)
        : choices,
    ));
    this.normalizeQuestionOrder();
    this.syncSectionQuestionCounts();
    this.moveTargetSectionId = '';
    this.error.set('');
    this.saved.set(false);
  }

  cancelNew(): void {
    const first = this.myTemplates()[0];
    first ? this.edit(first) : this.startNew();
  }

  previewOptions(question: number, count: number): void {
    this.optionPreview.set({ question, count });
  }

  beginCellDrag(questionIndex: number, optionIndex: number): void {
    if (
      this.gridEditingLocked()
      || this.sectionTypeForQuestion(questionIndex) !== 'multiple_choice'
    ) return;
    this.unselectQuestion(questionIndex);
    this.isDraggingCells = true;
    this.setChoiceCount(questionIndex, optionIndex + 1);
  }

  dragCell(questionIndex: number, optionIndex: number): void {
    if (
      this.gridEditingLocked()
      || !this.isDraggingCells
      || this.sectionTypeForQuestion(questionIndex) !== 'multiple_choice'
    ) return;
    this.unselectQuestion(questionIndex);
    this.setChoiceCount(questionIndex, optionIndex + 1);
  }

  private unselectQuestion(index: number): void {
    this.selectedQuestions.update((selected) => selected.filter((value) => value !== index));
  }

  endCellDrag(): void {
    this.isDraggingCells = false;
    this.stopAutoScroll();
  }

  beginQuestionGesture(index: number, event: PointerEvent, sheet: HTMLElement): void {
    if (this.gridEditingLocked()) return;
    event.preventDefault();
    sheet.setPointerCapture(event.pointerId);
    const baseSelection = this.selectedQuestions();
    const unselect = baseSelection.includes(index);
    this.questionGesture = {
      pointerId: event.pointerId,
      anchorIndex: index,
      unselect,
      baseSelection,
      sheet,
    };
    this.questionPointerY = event.clientY;
    this.selectedQuestions.set(
      unselect ? baseSelection.filter((selected) => selected !== index) : [index],
    );
  }

  moveQuestionGesture(event: PointerEvent): void {
    const gesture = this.questionGesture;
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    this.questionPointerY = event.clientY;
    this.updateQuestionGesture();
    this.updateAutoScroll(event, gesture.sheet, 40, 0, 8);
  }

  endQuestionGesture(event: PointerEvent): void {
    const gesture = this.questionGesture;
    if (!gesture || event.pointerId !== gesture.pointerId) return;
    this.questionGesture = null;
    if (gesture.sheet.hasPointerCapture(event.pointerId)) {
      gesture.sheet.releasePointerCapture(event.pointerId);
    }
    this.stopAutoScroll();
  }

  private updateQuestionGesture(): void {
    const gesture = this.questionGesture;
    if (!gesture) return;
    const renderedRows = Array.from(
      gesture.sheet.querySelectorAll<HTMLElement>('.sheet-question-row[data-question-index]'),
    );
    if (renderedRows.length > 0) {
      const row = renderedRows.reduce((nearest, candidate) => {
        const candidateBounds = candidate.getBoundingClientRect();
        const nearestBounds = nearest.getBoundingClientRect();
        const candidateDistance = Math.abs(
          this.questionPointerY - (candidateBounds.top + candidateBounds.height / 2),
        );
        const nearestDistance = Math.abs(
          this.questionPointerY - (nearestBounds.top + nearestBounds.height / 2),
        );
        return candidateDistance < nearestDistance ? candidate : nearest;
      });
      const questionIndex = Number(row.dataset['questionIndex']);
      this.updateQuestionSelection(gesture, questionIndex);
      return;
    }

    // Unit-test and pre-section fallback for a sheet with one representative
    // row rather than every rendered question row.
    const firstRow = gesture.sheet.querySelector<HTMLElement>('.sheet-question-row');
    if (!firstRow) return;
    const { top, height } = firstRow.getBoundingClientRect();
    const questionIndex = Math.min(
      this.questions().length - 1,
      Math.max(0, Math.floor((this.questionPointerY - top) / height)),
    );

    this.updateQuestionSelection(gesture, questionIndex);
  }

  private updateQuestionSelection(
    gesture: QuestionSelectionGesture,
    questionIndex: number,
  ): void {
    const boundedIndex = Math.min(this.questions().length - 1, Math.max(0, questionIndex));
    const start = Math.min(gesture.anchorIndex, boundedIndex);
    const end = Math.max(gesture.anchorIndex, boundedIndex);
    this.selectedQuestions.set(
      gesture.unselect
        ? gesture.baseSelection.filter((selected) => selected < start || selected > end)
        : Array.from({ length: end - start + 1 }, (_, offset) => start + offset),
    );
  }

  addQuestion(sheet?: HTMLElement, addButton?: HTMLElement, sectionId?: string): void {
    if (this.gridEditingLocked() || this.questions().length >= MAX_QUESTION_COUNT) return;
    const buttonTop = addButton?.getBoundingClientRect().top;
    const targetSectionId = sectionId ?? this.sections().at(-1)?.id ?? this.sections()[0]?.id;
    const sectionType = this.sections().find((section) => section.id === targetSectionId)?.type
      ?? 'multiple_choice';
    this.questions.update((questions) => [...questions, this.defaultChoices(sectionType)]);
    this.questionSectionIds.update((sectionIds) => [
      ...sectionIds,
      targetSectionId,
    ]);
    this.normalizeQuestionOrder();
    this.desiredCount.set(this.questions().length);
    this.syncSectionQuestionCounts();
    this.selectedQuestions.set([]);
    this.saved.set(false);

    if (sheet && addButton && buttonTop !== undefined) {
      requestAnimationFrame(() => {
        sheet.scrollTop += addButton.getBoundingClientRect().top - buttonTop;
      });
    }
  }

  deleteSelectedQuestions(): void {
    if (this.gridEditingLocked()) return;
    const selected = new Set(this.selectedQuestions());
    if (!selected.size) return;
    const remainingQuestions = this.questions().filter((_, index) => !selected.has(index));
    const remainingSectionIds = this.questionSectionIds()
      .filter((_, index) => !selected.has(index));
    this.sections().forEach((section) => {
      if (!remainingSectionIds.includes(section.id)) {
        remainingQuestions.push(this.defaultChoices(section.type));
        remainingSectionIds.push(section.id);
      }
    });
    this.questions.set(remainingQuestions);
    this.questionSectionIds.set(remainingSectionIds);
    this.normalizeQuestionOrder();
    this.desiredCount.set(this.questions().length);
    this.syncSectionQuestionCounts();
    this.selectedQuestions.set([]);
    this.saved.set(false);
  }

  handleDeleteShortcut(event: KeyboardEvent): void {
    if (!this.selectedQuestions().length || (event.key !== 'Delete' && event.key !== 'Backspace')) return;
    if ((event.target as Element | null)?.closest('input, textarea, select, [contenteditable]')) return;
    event.preventDefault();
    this.deleteSelectedQuestions();
  }

  autoScrollSheet(event: MouseEvent, sheet: HTMLElement): void {
    if (!this.isDraggingCells) return;
    this.updateAutoScroll(event, sheet, 48, 12, 10);
  }

  private updateAutoScroll(
    event: MouseEvent,
    sheet: HTMLElement,
    edge: number,
    speedX: number,
    speedY: number,
  ): void {
    const bounds = sheet.getBoundingClientRect();
    this.scrollTarget = sheet;
    this.scrollDelta = {
      x: speedX && event.clientX > bounds.right - edge ? speedX : speedX && event.clientX < bounds.left + edge ? -speedX : 0,
      y: event.clientY > bounds.bottom - edge ? speedY : event.clientY < bounds.top + edge ? -speedY : 0,
    };
    if (!this.scrollDelta.x && !this.scrollDelta.y) this.stopAutoScroll();
    else if (this.scrollFrame === null) this.runAutoScroll();
  }

  private runAutoScroll(): void {
    this.scrollFrame = requestAnimationFrame(() => {
      if (!this.scrollTarget || (!this.scrollDelta.x && !this.scrollDelta.y)) {
        this.stopAutoScroll();
        return;
      }
      this.scrollTarget.scrollBy(this.scrollDelta.x, this.scrollDelta.y);
      if (this.questionGesture) this.updateQuestionGesture();
      this.runAutoScroll();
    });
  }

  private stopAutoScroll(): void {
    if (this.scrollFrame !== null) cancelAnimationFrame(this.scrollFrame);
    this.scrollFrame = null;
    this.scrollTarget = null;
    this.scrollDelta = { x: 0, y: 0 };
  }

  edit(template: ExamTemplateResponse, checkUsage = true): void {
    if (template.archived_at !== null) return;
    const fallbackSection: TemplateSection = {
      id: 'section-1',
      name: 'Section 1',
      type: 'multiple_choice',
      question_ids: Object.keys(template.question_config).sort((a, b) => Number(a) - Number(b)),
    };
    const templateSections = template.sections?.length ? template.sections : [fallbackSection];
    const assignedKeys = templateSections.flatMap((section) => section.question_ids)
      .filter((key) => template.question_config[key]);
    const unassignedKeys = Object.keys(template.question_config)
      .filter((key) => !assignedKeys.includes(key))
      .sort((a, b) => Number(a) - Number(b));
    const keys = [...assignedKeys, ...unassignedKeys];
    const sectionIdsByQuestion = new Map(
      templateSections.flatMap((section) => section.question_ids.map((key) => [key, section.id])),
    );
    this.editingId.set(template.id);
    this.templateName.set(template.name);
    this.nVersions.set(template.n_versions);
    this.questions.set(keys.map((k) => [...template.question_config[k].choices]));
    this.sections.set(templateSections.map(({ id, name, type = 'multiple_choice' }) => ({ id, name, type })));
    this.questionSectionIds.set(keys.map((key) => sectionIdsByQuestion.get(key) ?? templateSections[0].id));
    this.desiredCount.set(keys.length);
    // A previously-saved template may already have a question wider than the
    // default cap (e.g. saved with a higher cap in an earlier session), so
    // the grid needs to be at least that wide to display it, not silently hide it.
    const widestSaved = Math.max(DEFAULT_MAX_OPTION_COUNT, ...keys.map((k) => template.question_config[k].choices.length));
    this.maxOptionCount.set(Math.min(OPTION_COUNT_CEILING, widestSaved));
    this.desiredMaxOptionCount.set(this.maxOptionCount());
    this.sectionQuestionCounts.set(Object.fromEntries(
      templateSections.map((section) => [
        section.id,
        keys.filter((key) => sectionIdsByQuestion.get(key) === section.id).length,
      ]),
    ));
    this.generatedPdfPath.set(template.generated_pdf_path);
    this.omrTemplateId.set(template.omr_template_id);
    this.isBlueprint.set(template.blueprint !== null);
    this.versionFromQ1.set(template.version_from_q1);
    this.questionKeys.set(keys);
    this.rememberSavedTemplate(template);
    this.saved.set(false);
    this.error.set('');
    this.selectedQuestions.set([]);
    if (template.blueprint) {
      this.showPreview.set(false);
      this.clearPreview();
    } else if (this.showPreview()) {
      this.loadPreview(template.id);
    } else {
      this.clearPreview();
    }

    // Blueprint templates are always locked (fixed physical sheet). A custom
    // one is locked only once real usage shows up, which needs a fetch, so
    // reuse the same one for both versionCountLocked and this.
    this.questionConfigLocked.set(template.blueprint !== null);
    const shouldCheckUsage = checkUsage && this.showVersionsField();
    this.isCheckingVersionUsage.set(shouldCheckUsage);
    this.versionCountLocked.set(false);
    if (shouldCheckUsage) {
      this.templateService.getTemplateUsage(template.id).subscribe({
        next: (usage) => {
          if (this.editingId() !== template.id) return;
          this.isCheckingVersionUsage.set(false);
          this.versionCountLocked.set(usage.exam_count > 0);
          if (!template.blueprint) {
            this.questionConfigLocked.set(
              usage.exam_count > 0 || usage.answer_key_count > 0 || usage.scan_count > 0,
            );
          }
        },
        error: () => {
          if (this.editingId() !== template.id) return;
          this.isCheckingVersionUsage.set(false);
          this.versionCountLocked.set(true);
          this.questionConfigLocked.set(true);
          this.error.set('Unable to check whether this template is assigned to an exam.');
        },
      });
    }
  }

  generatePdf(): void {
    const id = this.editingId();
    if (!id) return;
    this.error.set('');
    this.isGeneratingPdf.set(true);
    this.templateService.generatePdf(id).subscribe({
      next: (t) => {
        this.isGeneratingPdf.set(false);
        this.myTemplates.update((list) => list.map((x) => (x.id === t.id ? t : x)));
        if (this.editingId() !== id) return; // user switched to another template while this was in flight
        this.generatedPdfPath.set(t.generated_pdf_path);
        this.omrTemplateId.set(t.omr_template_id);
      },
      error: () => {
        this.isGeneratingPdf.set(false);
        if (this.editingId() !== id) return;
        this.error.set('Failed to generate the template PDF.');
      },
    });
  }

  // Max options is "pending until confirmed" rather than applying on every
  // keystroke, since raising it widens every multiple_choice section's grid.
  applyMaxOptionCount(): void {
    if (this.gridEditingLocked() || !this.maxOptionCountDirty()) return;
    this.setMaxOptionCount(this.desiredMaxOptionCount());
  }

  applyDesiredCount(): void {
    if (this.gridEditingLocked()) return;
    const next = Math.min(MAX_QUESTION_COUNT, Math.max(1, Math.floor(this.desiredCount())));
    if (this.sections().length === 0) {
      const section = this.newSection('Section 1');
      this.sections.set([section]);
    }
    this.desiredCount.set(next);
    this.error.set('');
    this.saved.set(false);
    const questions = [...this.questions()];
    const sectionIds = [...this.questionSectionIds()];
    const targetSectionId = this.sections().at(-1)?.id ?? this.sections()[0]?.id;
    const targetSectionType = this.sections().find((section) => section.id === targetSectionId)?.type
      ?? 'multiple_choice';
    while (questions.length < next) {
      questions.push(this.defaultChoices(targetSectionType));
      sectionIds.push(targetSectionId);
    }
    if (next < questions.length) {
      questions.length = next;
      sectionIds.length = next;
    }
    this.questions.set(questions);
    this.questionSectionIds.set(sectionIds);
    this.normalizeQuestionOrder();
    this.syncSectionQuestionCounts();
    this.selectedQuestions.set([]);
  }

  setChoiceCount(index: number, count: number): void {
    if (this.gridEditingLocked() || this.sectionTypeForQuestion(index) !== 'multiple_choice') return;
    const n = Math.min(this.maxOptionCount(), Math.max(2, Math.floor(count)));
    this.saved.set(false);
    this.questions.update((qs) => qs.map((q, i) => (i === index ? labelsFor(n) : q)));
  }

  setMaxOptionCount(count: number): void {
    const n = Math.min(OPTION_COUNT_CEILING, Math.max(2, Math.floor(count)));
    this.maxOptionCount.set(n);
    this.desiredMaxOptionCount.set(n);
    // Lowering the cap below a question's current option count clamps that
    // question down too, same as dragging its own endpoint back manually.
    this.questions.update((qs) => qs.map((q) => (q.length > n ? labelsFor(n) : q)));
    this.saved.set(false);
  }

  // UR2.8: standard preset — the backend generates the full 100Q A-E layout.
  useUbco100Preset(): void {
    const versionError = this.ubcoVersionError();
    if (versionError) {
      this.error.set(versionError);
      return;
    }
    this.error.set('');
    this.isSaving.set(true);
    this.templateService.createUbco100Template(
      this.versionFromQ1(),
      this.templateName(),
      this.nVersions(),
    ).subscribe({
      next: (t) => {
        this.isSaving.set(false);
        this.myTemplates.update((list) => [t, ...list]);
        this.edit(t, false);
        this.saved.set(true); // after edit(), which resets the flag
      },
      error: () => {
        this.isSaving.set(false);
        this.error.set('Failed to create the UBC 100Q template.');
      },
    });
  }

  // allowGenerate lets a save also generate the PDF. Only an explicit click
  // passes true; autosave always passes false, since generating locks the
  // question layout and shouldn't happen without the user asking for it.
  save(allowGenerate = true, onComplete?: (success: boolean) => void): void {
    const validation = this.validationError();
    if (validation) {
      this.error.set(validation);
      onComplete?.(false);
      return;
    }
    this.error.set('');
    this.isSaving.set(true);

    const question_config = this.buildQuestionConfig();
    const sections = this.buildSections();
    const id = this.editingId();
    const name = this.templateName().trim();
    // A blueprint's questions are fixed by its physical sheet — buildUpdateBody
    // only includes question_config when it actually changed, which for a
    // blueprint template it never does (the UI won't let it), so this never
    // trips the backend's "template_locked" guard on a plain rename.
    const updateBody = id ? this.buildUpdateBody(name, question_config, sections) : null;
    // A brand-new template's layout is "changed" by definition. For an
    // existing one, only true if this save touches the layout or version
    // count, since a generated PDF needs redrawing when either changes.
    const layoutChanged = !id || (
      updateBody !== null
      && (
        'question_config' in updateBody
        || 'sections' in updateBody
        || 'n_versions' in updateBody
      )
    );

    if (id && Object.keys(updateBody ?? {}).length === 0) {
      this.isSaving.set(false);
      this.saved.set(true);
      if (allowGenerate && !this.generatedPdfPath()) this.generatePdf();
      onComplete?.(true);
      return;
    }

    const request$ = id
      ? this.templateService.updateTemplate(id, updateBody!)
      : this.templateService.createTemplate({
          name,
          question_config,
          n_versions: this.nVersions(),
          sections,
        });

    request$.subscribe({
      next: (t) => {
        this.isSaving.set(false);
        this.myTemplates.update((list) => {
          const others = list.filter((x) => x.id !== t.id);
          return [t, ...others];
        });
        if (this.editingId() !== id) {
          onComplete?.(true);
          return; // user switched to another template while this was in flight
        }
        this.saved.set(true);
        this.editingId.set(t.id);
        this.rememberSavedTemplate(t);
        this.generatedPdfPath.set(t.generated_pdf_path);
        this.omrTemplateId.set(t.omr_template_id);
        if (!t.blueprint && layoutChanged && this.showPreview()) this.loadPreview(t.id);
        if (allowGenerate && (layoutChanged || !t.generated_pdf_path)) this.generatePdf();
        onComplete?.(true);
      },
      error: (err) => {
        this.isSaving.set(false);
        if (this.editingId() !== id) {
          onComplete?.(false);
          return;
        }
        if (this.errorCode(err) === 'template_locked') {
          this.questionConfigLocked.set(true);
          this.error.set('This template layout is locked because it is already in use. Rename it or create a new template.');
          onComplete?.(false);
          return;
        }
        if (this.errorCode(err) === 'template_versions_locked') {
          this.nVersions.set(this.savedNVersions());
          this.versionCountLocked.set(true);
          this.error.set('The version count cannot be changed after assigning this template to an exam.');
          onComplete?.(false);
          return;
        }
        this.error.set('Failed to save the template. Please try again.');
        onComplete?.(false);
      },
    });
  }

  setArchiveView(showArchived: boolean): void {
    if (this.showArchived() === showArchived) return;
    this.startNew();
    this.showArchived.set(showArchived);
  }

  archive(template: ExamTemplateResponse): void {
    if (template.archived_at !== null || this.archiveActionId() !== null) return;
    const hasPendingAutosave = this.autosaveTimer !== null;
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    this.error.set('');
    this.archiveActionId.set(template.id);

    if (hasPendingAutosave) {
      this.save(false, (success) => {
        if (success) {
          this.performArchive(template);
        } else {
          this.archiveActionId.set(null);
        }
      });
      return;
    }

    this.performArchive(template);
  }

  private performArchive(template: ExamTemplateResponse): void {
    this.templateService.archiveTemplate(template.id).subscribe({
      next: (archived) => {
        this.archiveActionId.set(null);
        this.myTemplates.update((templates) =>
          templates.map((item) => item.id === archived.id ? archived : item),
        );
        if (this.editingId() === archived.id) this.startNew();
        this.templateDeleted.emit();
      },
      error: () => {
        this.archiveActionId.set(null);
        this.error.set('Failed to archive the template.');
      },
    });
  }

  restore(template: ExamTemplateResponse): void {
    if (template.archived_at === null || this.archiveActionId() !== null) return;
    this.error.set('');
    this.archiveActionId.set(template.id);
    this.templateService.restoreTemplate(template.id).subscribe({
      next: (restored) => {
        this.archiveActionId.set(null);
        this.myTemplates.update((templates) =>
          templates.map((item) => item.id === restored.id ? restored : item),
        );
        this.templateDeleted.emit();
      },
      error: () => {
        this.archiveActionId.set(null);
        this.error.set('Failed to restore the template.');
      },
    });
  }

  requestDelete(template: ExamTemplateResponse): void {
    this.error.set('');
    this.deleteCandidate.set(template);
    this.deleteUsage.set(null);
    this.isCheckingDelete.set(true);

    this.templateService.getTemplateUsage(template.id).subscribe({
      next: (usage) => {
        if (this.deleteCandidate()?.id !== template.id) return;
        this.isCheckingDelete.set(false);
        this.deleteUsage.set(usage);
      },
      error: () => {
        if (this.deleteCandidate()?.id !== template.id) return;
        this.isCheckingDelete.set(false);
        this.cancelDelete();
        this.error.set('Failed to check where this template is used.');
      },
    });
  }

  cancelDelete(): void {
    if (this.isDeleting()) return;
    this.deleteCandidate.set(null);
    this.deleteUsage.set(null);
    this.isCheckingDelete.set(false);
  }

  confirmDelete(): void {
    const template = this.deleteCandidate();
    if (!template || this.isCheckingDelete() || this.isDeleting()) return;

    this.error.set('');
    this.isDeleting.set(true);
    this.templateService.deleteTemplate(template.id, this.deleteHasUsage()).subscribe({
      next: () => {
        this.isDeleting.set(false);
        this.myTemplates.update((list) => list.filter((t) => t.id !== template.id));
        this.templateDeleted.emit();
        if (this.editingId() === template.id) this.startNew();
        this.cancelDelete();
      },
      error: (err) => {
        this.isDeleting.set(false);
        const usage = this.usageFromDeleteError(err);
        if (usage) {
          this.showDeleteConflict(usage);
          return;
        }
        if ((err as { status?: number })?.status === 409) {
          this.reloadDeleteUsageAfterConflict(template);
          return;
        }
        this.error.set('Failed to delete the template.');
      },
    });
  }

  private showDeleteConflict(usage: ExamTemplateUsageResponse): void {
    this.deleteUsage.set(usage);
    this.error.set('This template is used by existing exams. Review the affected exams before deleting.');
  }

  private reloadDeleteUsageAfterConflict(template: ExamTemplateResponse): void {
    this.isCheckingDelete.set(true);
    this.templateService.getTemplateUsage(template.id).subscribe({
      next: (usage) => {
        if (this.deleteCandidate()?.id !== template.id) return;
        this.isCheckingDelete.set(false);
        this.showDeleteConflict(usage);
      },
      error: () => {
        if (this.deleteCandidate()?.id !== template.id) return;
        this.isCheckingDelete.set(false);
        this.error.set('Failed to delete the template.');
      },
    });
  }

  private buildQuestionConfig(): Record<string, QuestionConfigItem> {
    // Blueprint templates (e.g. version_from_q1) skip keys, so array position
    // no longer matches the real question number — use the tracked key when
    // one exists, falling back to positional numbering for a brand-new
    // from-scratch custom template that has no keys yet.
    const keys = this.questionKeys();
    const out: Record<string, QuestionConfigItem> = {};
    this.questions().forEach((choices, i) => {
      out[keys[i] ?? String(i + 1)] = { choices: [...choices] };
    });
    return out;
  }

  private buildSections(): TemplateSection[] {
    const keys = this.questionKeys();
    const sectionIds = this.questionSectionIds();
    return this.sections().map((section) => ({
      ...section,
      name: section.name.trim(),
      question_ids: keys.filter((_, index) => sectionIds[index] === section.id),
    }));
  }

  private rememberSavedTemplate(template: ExamTemplateResponse): void {
    this.savedTemplateName.set(template.name);
    this.savedLayoutFingerprint.set(this.layoutFingerprintFromTemplate(template));
    this.savedNVersions.set(template.n_versions);
  }

  private buildUpdateBody(
    name: string,
    questionConfig: Record<string, QuestionConfigItem>,
    sections: TemplateSection[],
  ): UpdateExamTemplateRequest {
    const body: UpdateExamTemplateRequest = {};
    if (name !== this.savedTemplateName()) {
      body.name = name;
    }
    if (this.layoutFingerprint(questionConfig, sections) !== this.savedLayoutFingerprint()) {
      body.question_config = questionConfig;
      body.sections = sections;
    }
    if (this.nVersions() !== this.savedNVersions()) {
      body.n_versions = this.nVersions();
    }
    return body;
  }

  private layoutFingerprint(
    config: Record<string, QuestionConfigItem>,
    sections: TemplateSection[],
  ): string {
    return JSON.stringify(
      [Object.keys(config)
        .sort((a, b) => Number(a) - Number(b))
        .map((key) => [key, [...config[key].choices]]), sections],
    );
  }

  private layoutFingerprintFromTemplate(template: ExamTemplateResponse): string {
    return this.layoutFingerprint(template.question_config, template.sections);
  }

  optionColumnsFor(section: SectionDraft): string[] {
    return section.type === 'true_false' ? this.trueFalseColumns : this.optionColumns();
  }

  sectionTypeLabel(type: TemplateSectionType): string {
    return type === 'true_false' ? 'True / False' : 'Multiple choice';
  }

  private newSection(name: string, type: TemplateSectionType = 'multiple_choice'): SectionDraft {
    const existing = new Set(this.sections().map(({ id }) => id));
    let number = this.sections().length + 1;
    while (existing.has(`section-${number}`)) number++;
    return { id: `section-${number}`, name, type };
  }

  private defaultChoices(type: TemplateSectionType): string[] {
    return type === 'true_false' ? ['T', 'F'] : labelsFor(DEFAULT_CHOICE_COUNT);
  }

  private sectionTypeForQuestion(index: number): TemplateSectionType {
    const sectionId = this.questionSectionIds()[index];
    return this.sections().find((section) => section.id === sectionId)?.type ?? 'multiple_choice';
  }

  private syncSectionQuestionCounts(): void {
    const sectionIds = this.questionSectionIds();
    this.sectionQuestionCounts.set(Object.fromEntries(
      this.sections().map((section) => [
        section.id,
        sectionIds.filter((id) => id === section.id).length,
      ]),
    ));
  }

  private normalizeQuestionOrder(): void {
    if (this.isBlueprint()) return;
    const questions = this.questions();
    const sectionIds = this.questionSectionIds();
    const sectionOrder = new Map(this.sections().map((section, index) => [section.id, index]));
    const indexes = questions.map((_, index) => index).sort((a, b) =>
      (sectionOrder.get(sectionIds[a]) ?? 0) - (sectionOrder.get(sectionIds[b]) ?? 0),
    );
    this.questions.set(indexes.map((index) => questions[index]));
    this.questionSectionIds.set(indexes.map((index) => sectionIds[index]));
    this.questionKeys.set(indexes.map((_, index) => String(index + 1)));
    this.selectedQuestions.set([]);
  }

  private usageFromDeleteError(err: unknown): ExamTemplateUsageResponse | null {
    const payload = this.findTemplateInUsePayload((err as { error?: unknown })?.error ?? err);
    if (!payload || !this.isTemplateUsage(payload.details)) return null;
    return payload.details;
  }

  private errorCode(err: unknown): string | null {
    const payload = this.findErrorPayload((err as { error?: unknown })?.error ?? err);
    return typeof payload?.['code'] === 'string' ? payload['code'] : null;
  }

  private errorMessage(err: unknown): string | null {
    const payload = this.findErrorPayload((err as { error?: unknown })?.error ?? err);
    return typeof payload?.['message'] === 'string' ? payload['message'] : null;
  }

  // A blob-typed request (previewPdf uses responseType: 'blob' to fetch a
  // PDF) also gets its error body back as a Blob instead of parsed JSON,
  // since Angular has no way to know the error response isn't the PDF it
  // asked for. This reads that blob's text and parses it so errorCode/
  // errorMessage can use their normal parsing path on it either way.
  private async parseBlobError(err: unknown): Promise<unknown> {
    const body = (err as { error?: unknown } | null)?.error;
    if (!(body instanceof Blob)) return err;
    try {
      return { error: JSON.parse(await body.text()) };
    } catch {
      return err;
    }
  }

  private findErrorPayload(value: unknown): Record<string, unknown> | null {
    if (!this.isRecord(value)) return null;
    if (typeof value['code'] === 'string') return value;
    return this.findErrorPayload(value['error']) ?? this.findErrorPayload(value['detail']);
  }

  private findTemplateInUsePayload(value: unknown): { details?: unknown } | null {
    if (!this.isRecord(value)) return null;
    if (value['code'] === 'template_in_use') return value;
    return this.findTemplateInUsePayload(value['error']) ?? this.findTemplateInUsePayload(value['detail']);
  }

  private isTemplateUsage(value: unknown): value is ExamTemplateUsageResponse {
    return this.isRecord(value)
      && typeof value['template_id'] === 'string'
      && typeof value['exam_count'] === 'number'
      && typeof value['answer_key_count'] === 'number'
      && typeof value['scan_count'] === 'number'
      && Array.isArray(value['exams']);
  }

  private isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null;
  }
}
