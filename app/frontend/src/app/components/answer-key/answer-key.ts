import {
  ChangeDetectionStrategy,
  Component,
  computed,
  effect,
  ElementRef,
  EventEmitter,
  HostListener,
  inject,
  Input,
  OnDestroy,
  OnInit,
  Output,
  signal,
  untracked,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { firstValueFrom } from 'rxjs';
import { WizardSteps } from '../../sub-components/wizard-steps/wizard-steps';
import { ExamAnswerKeyService } from '../../services/exam-answer-key.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ExamService } from '../../services/exam.service';
import { CourseService } from '../../services/course.service';
import { ExamTemplateResponse, TemplateSectionType } from '../../models/exam-template.model';
import {
  AnswerKeyItem,
  AnswerKeyScanMatchAction,
  AnswerKeyScanMatchingMode,
  ConfirmAnswerKeyScanMatchesRequest,
  CreateExamAnswerKeyRequest,
  ExamAnswerKeyResponse,
  ExtractAnswerKeyScanBatchResponse,
  ExtractedAnswerKeyQuestion,
  ExtractedAnswerKeySheet,
  GradingType,
} from '../../models/exam-answer-key.model';

/** Working (UI-side) state for one question; the choices come from the exam's
 *  template and are fixed here — this page only fills in the answers. */
interface QuestionDraft {
  id: string; // the template's question_config key, e.g. "2" — not the array position
  choices: string[];
  gradingType: GradingType;
  correctChoices: string[];
  partialWeights: Record<string, number>;
  points: number | null;
}

interface VersionSlot {
  version: string | null;
  label: string;
  key: ExamAnswerKeyResponse | null;
  status: 'missing' | 'partial' | 'complete';
  hasScannedDraft: boolean;
}

interface AnswerSection {
  id: string;
  name: string;
  type: TemplateSectionType;
  questions: { question: QuestionDraft; index: number }[];
  gridRows: number;
}

interface ImportResult {
  imported: number;
  total: number;
  failures: { filename: string; message: string }[];
}

interface AnswerKeyScanMatchDraft {
  sheetIndex: number;
  action: AnswerKeyScanMatchAction;
  // Undefined means the sheet still needs a decision. Null is a resolved
  // target for a single-version exam's unversioned answer key.
  targetVersion: string | null | undefined;
}

interface AnswerKeyVersionDraft {
  version: string | null;
  selectedKeyId: string | null;
  savedEntryCount: number | null;
  questions: QuestionDraft[];
  questionsUsed: number;
  pointsPerQuestion: number;
  sectionPointDrafts: Record<string, number | null>;
  saved: boolean;
  // What this version looked like as of its last load/save -- kept alongside
  // the (possibly dirty) live draft so switching versions and back restores
  // the correct "has this changed since it was last saved?" state, not just
  // whatever the draft happened to hold when it was stashed.
  baselineSnapshot: string;
}

const DEFAULT_POINTS = 1; // most questions are single-answer worth 1 point
const MAX_ANSWER_KEY_SCAN_BYTES = 10_000_000;
const PDF_CONTENT_TYPES = new Set(['application/pdf', 'application/x-pdf', 'application/octet-stream']);

@Component({
  selector: 'app-answer-key',
  imports: [FormsModule, WizardSteps],
  templateUrl: './answer-key.html',
  styleUrl: './answer-key.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AnswerKey implements OnInit, OnDestroy {
  private static readonly AUTOSAVE_DELAY_MS = 3000;

  private answerKeyService = inject(ExamAnswerKeyService);
  private templateService = inject(ExamTemplateService);
  private examService = inject(ExamService);
  private courseService = inject(CourseService);
  private host = inject(ElementRef<HTMLElement>);

  // How many version pills are clipped past the first row, measured rather
  // than a fixed count, since how many pills fit on one row depends on the
  // viewport/window width, not just the version count.
  private pillRowObserver?: ResizeObserver;
  private observedVersionPillsEl?: HTMLElement;
  readonly versionStripHiddenCount = signal(0);

  private autosaveTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    effect(() => {
      this.versionSlots();
      setTimeout(() => this.syncVersionPillsObserver());
    });

    effect(() => {
      // The draft fields that make a key worth saving. scheduleAutosave()
      // also reads canSave()/isSaving() to decide whether to schedule; those
      // must stay untracked, or isSaving flipping mid-save would retrigger
      // this effect and keep rescheduling the timer.
      this.questions();
      this.questionsUsed();
      this.pointsPerQuestion();
      untracked(() => this.scheduleAutosave());
    });
  }

  @Input() examId = '';
  // When set, this is one step of the exam-creation wizard (course-detail.html):
  // shows the step indicator and a "Next: Exam PDFs" button.
  @Input() wizardStep: number | null = null;
  @Output() close = new EventEmitter<void>();
  @Output() refreshRequested = new EventEmitter<void>();
  @Output() nextRequested = new EventEmitter<void>();

  readonly examName = signal('');
  readonly courseName = signal('');
  readonly template = signal<ExamTemplateResponse | null>(null);
  // Once an exam has any graded submission, the answer key is locked,
  // since editing it afterward would silently desync it from what was graded.
  readonly examGraded = signal(false);

  readonly existingKeys = signal<ExamAnswerKeyResponse[]>([]);
  readonly selectedKeyId = signal<string | null>(null); // null = building a new key
  readonly savedEntryCount = signal<number | null>(null); // questions in the saved key
  readonly selectedVersion = signal<string | null>(null);

  readonly questions = signal<QuestionDraft[]>([]);
  readonly pointsPerQuestion = signal(1);
  // The exam may use fewer questions than the template provides (e.g. 80 of the
  // UBC 100Q sheet). Only the first N get an answer key; the grader ignores the rest.
  readonly questionsUsed = signal(0);
  readonly activeQuestion = signal(0); // keyboard-entry cursor

  readonly isLoading = signal(false);
  readonly isSaving = signal(false);
  readonly isImporting = signal(false);
  readonly isUploadingAnswerKeyScan = signal(false);
  // One modal with two tabs: "Upload Scan" (PDF, OMR extraction) and "Import
  // File" (JSON/CSV export). Both stage file(s) first and require an explicit
  // submit rather than uploading as soon as a file is chosen.
  readonly uploadModalOpen = signal(false);
  readonly uploadModalTab = signal<'scan' | 'import'>('scan');
  readonly stagedScanFiles = signal<File[]>([]);
  readonly stagedImportFiles = signal<File[]>([]);
  readonly importResult = signal<ImportResult | null>(null);
  readonly answerKeyScanExtraction = signal<ExtractAnswerKeyScanBatchResponse | null>(null);
  readonly answerKeyScanReviewOpen = signal(false);
  readonly answerKeyScanMatchingMode = signal<AnswerKeyScanMatchingMode>('automatic');
  readonly answerKeyScanMatches = signal<AnswerKeyScanMatchDraft[]>([]);
  readonly answerKeyScanMatchError = signal('');
  readonly confirmedAnswerKeyScanMatches = signal<ConfirmAnswerKeyScanMatchesRequest | null>(null);
  // Auto-saving each version a confirmed scan match was applied to, so the
  // instructor doesn't have to revisit every affected version to save it.
  readonly isSavingScannedVersions = signal(false);
  readonly scanAutoSaveResult = signal<{
    saved: number;
    total: number;
    failures: { version: string | null; message: string }[];
  } | null>(null);
  // Which sheets in the match modal have their detected answers expanded,
  // so an instructor can spot-check what OMR actually read for that sheet.
  readonly expandedScanSheets = signal<Set<number>>(new Set());
  readonly answerKeyVersionDrafts = signal<Record<string, AnswerKeyVersionDraft>>({});
  readonly scannedDraftVersions = signal<string[]>([]);
  readonly isFinalizingTemplate = signal(false);
  readonly isGeneratingExamPdf = signal(false);
  readonly examGeneratedPdfPath = signal<string | null>(null);
  readonly confirmingClearKeyId = signal<string | null>(null);
  readonly isClearingKey = signal(false);
  readonly error = signal('');
  readonly saved = signal(false);
  readonly versionStripExpanded = signal(false);
  readonly sectionPointDrafts = signal<Record<string, number | null>>({});
  // Snapshot of {questions, questionsUsed, pointsPerQuestion} as of the last
  // load/save, compared against the live draft below to disable Save until
  // something actually changes -- otherwise a fully valid, untouched key
  // looks just as "saveable" as one with a pending edit.
  private readonly baselineSnapshot = signal('');

  copySourceId = ''; // version picker for "copy values from"

  readonly gradingTypes: GradingType[] = ['single', 'multiple', 'partial'];

  readonly visibleQuestions = computed(() => this.questions().slice(0, this.questionsUsed()));

  readonly versionSlots = computed<VersionSlot[]>(() => {
    const count = this.template()?.n_versions ?? 1;
    const versions = count === 1
      ? [null]
      : Array.from({ length: count }, (_, index) => String.fromCharCode(65 + index));
    return versions.map((version) => {
      const key = this.existingKeys().find((candidate) => candidate.exam_version === version) ?? null;
      return {
        version,
        label: version ? `Version ${version}` : 'Answer key',
        key,
        status: !key ? 'missing' : this.isKeyComplete(key) ? 'complete' : 'partial',
        hasScannedDraft: this.scannedDraftVersions().includes(this.versionDraftKey(version)),
      };
    });
  });

  readonly completedVersionCount = computed(() =>
    this.versionSlots().filter((slot) => slot.status === 'complete').length,
  );

  readonly hasMultipleVersions = computed(() => this.versionSlots().length > 1);

  // Whether the fold toggle should appear at all: true only once the
  // measured overflow (versionStripHiddenCount) says pills actually spill
  // past the first row at the current width.
  readonly versionStripCollapsible = computed(() => this.versionStripHiddenCount() > 0);

  readonly unansweredQuestionCount = computed(() =>
    this.visibleQuestions().filter((question) => question.correctChoices.length === 0).length,
  );
  readonly answerSections = computed<AnswerSection[]>(() => {
    const template = this.template();
    if (!template) return [];
    const visible = this.visibleQuestions();
    const byId = new Map(visible.map((question, index) => [question.id, { question, index }]));
    const assigned = new Set<string>();
    const sections: AnswerSection[] = (template.sections ?? []).map((section) => {
      const questions = section.question_ids.flatMap((id) => {
        const entry = byId.get(id);
        if (!entry) return [];
        assigned.add(id);
        return [entry];
      });
      return {
        id: section.id,
        name: section.name,
        type: section.type,
        questions,
        gridRows: Math.ceil(questions.length / 2),
      };
    }).filter((section) => section.questions.length > 0);
    const unassigned = visible
      .map((question, index) => ({ question, index }))
      .filter(({ question }) => !assigned.has(question.id));
    if (unassigned.length) {
      sections.push({
        id: 'unassigned',
        name: sections.length ? 'Other questions' : 'Questions',
        type: 'multiple_choice',
        questions: unassigned,
        gridRows: Math.ceil(unassigned.length / 2),
      });
    }
    return sections;
  });

  readonly currentVersionLabel = computed(() =>
    this.selectedVersion() ? `Version ${this.selectedVersion()}` : 'Answer key',
  );

  readonly currentKey = computed(() =>
    this.existingKeys().find((key) => key.id === this.selectedKeyId()) ?? null,
  );

  readonly copySources = computed(() =>
    this.existingKeys().filter((k) => k.id !== this.selectedKeyId()),
  );

  readonly answerKeyScanTargetVersions = computed<(string | null)[]>(() => {
    const count = this.template()?.n_versions ?? 1;
    return count === 1
      ? [null]
      : Array.from({ length: count }, (_, index) => String.fromCharCode(65 + index));
  });

  readonly answerKeyScanMatchValidationError = computed<string | null>(() => {
    const extraction = this.answerKeyScanExtraction();
    if (!extraction) return 'No scanned answer keys are available.';

    const matches = this.answerKeyScanMatches();
    const unresolved = matches.filter((match) => !this.isAnswerKeyScanMatchResolved(match));
    if (unresolved.length > 0) {
      return `${unresolved.length} sheet${unresolved.length === 1 ? '' : 's'} still need a version or must be skipped.`;
    }

    const assigned = matches
      .filter((match) => match.action === 'apply')
      .map((match) => match.targetVersion ?? '__unversioned__');
    if (new Set(assigned).size !== assigned.length) {
      return 'Each answer-key version can only be assigned to one sheet.';
    }
    return null;
  });

  readonly confirmedAnswerKeyScanCount = computed(() =>
    this.confirmedAnswerKeyScanMatches()?.matches.filter((match) => match.action === 'apply').length ?? 0,
  );

  // Only worth labeling each sheet with its source file once more than one
  // file was uploaded at a time, otherwise it's a redundant repeat of the
  // upload the instructor just made.
  readonly answerKeyScanHasMultipleSourceFiles = computed(() => {
    const extraction = this.answerKeyScanExtraction();
    if (!extraction) return false;
    return new Set(extraction.sheets.map((sheet) => sheet.source_filename)).size > 1;
  });

  readonly validationError = computed<string | null>(() => AnswerKey.validateQuestions(this.visibleQuestions()));

  private static validateQuestions(questions: QuestionDraft[]): string | null {
    if (questions.length === 0) return 'This exam has no template questions to answer.';
    for (const q of questions) {
      if (q.gradingType === 'single' && q.correctChoices.length > 1) {
        return `Question ${q.id} is single-answer but has multiple correct choices.`;
      }
      if (q.gradingType === 'partial' && q.correctChoices.length > 0) {
        if (q.correctChoices.some((choice) => {
          const weight = q.partialWeights[choice];
          return !Number.isFinite(weight) || weight < 0 || weight > 1;
        })) {
          return `Question ${q.id} partial-credit weights must be between 0 and 1.`;
        }
        const total = q.correctChoices.reduce((sum, choice) => sum + (q.partialWeights[choice] ?? 0), 0);
        if (Math.abs(total - 1) > 1e-6) {
          return `Question ${q.id} partial-credit weights must add up to exactly 100%, not ${Math.round(total * 100)}%.`;
        }
      }
    }
    return null;
  }

  private static buildAnswerKeyPayload(questions: QuestionDraft[]): Record<string, AnswerKeyItem> {
    const out: Record<string, AnswerKeyItem> = {};
    // Only the questions in use get entries: the grader ignores everything
    // past the last answer-key entry, which is how a 100Q sheet marks only 80.
    questions.forEach((q) => {
      out[q.id] = {
        grading_type: q.gradingType,
        correct_choices: [...q.correctChoices],
        points: q.points,
        partial_weights: q.gradingType === 'partial' ? { ...q.partialWeights } : null,
      };
    });
    return out;
  }

  private static snapshotOf(questions: QuestionDraft[], questionsUsed: number, pointsPerQuestion: number): string {
    return JSON.stringify({ questions, questionsUsed, pointsPerQuestion });
  }

  private currentDraftSnapshot(): string {
    return AnswerKey.snapshotOf(this.questions(), this.questionsUsed(), this.pointsPerQuestion());
  }

  readonly isDirty = computed(() => this.currentDraftSnapshot() !== this.baselineSnapshot());

  readonly canSave = computed(() =>
    this.validationError() === null && !this.isSaving() && this.isDirty() && !this.examGraded(),
  );

  // Small save-state readout next to the Save button, so autosave firing
  // silently in the background doesn't leave the user unsure whether their
  // edits actually persisted.
  readonly saveStatus = computed<{ label: string; tagClass: string } | null>(() => {
    if (this.isSaving()) return { label: 'Saving…', tagClass: 'tag-amber' };
    if (this.validationError()) return null; // the validation message below already covers this
    if (this.isDirty()) return { label: 'Unsaved changes', tagClass: 'tag-amber' };
    if (this.saved()) return { label: 'Saved', tagClass: 'tag-green' };
    return null;
  });

  // Advancing past this wizard step without a complete answer key for every
  // version would leave scans un-gradeable later with no obvious cause, so
  // require every version to be filled in first.
  readonly canAdvanceWizard = computed(() =>
    this.completedVersionCount() === this.versionSlots().length,
  );
  readonly canFinalizeTemplate = computed(() => {
    const template = this.template();
    return (
      !!template &&
      !template.omr_template_id &&
      !this.isFinalizingTemplate()
    );
  });
  // A blueprint template has no digital PDF to add exam details to (the
  // physical sheet is pre-printed), so there's nothing to generate for it.
  readonly canGenerateExamPdf = computed(() => {
    const template = this.template();
    return (
      !!template &&
      !template.blueprint &&
      !!template.omr_template_id &&
      !this.examGeneratedPdfPath() &&
      this.completedVersionCount() === this.versionSlots().length &&
      !this.isGeneratingExamPdf()
    );
  });

  ngOnInit(): void {
    if (!this.examId) {
      this.error.set('No exam was specified.');
      return;
    }
    this.loadEverything();
  }

  ngOnDestroy(): void {
    this.pillRowObserver?.disconnect();
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
  }

  private scheduleAutosave(): void {
    if (this.autosaveTimer) clearTimeout(this.autosaveTimer);
    this.autosaveTimer = null;
    if (!this.canSave()) return;
    this.autosaveTimer = setTimeout(() => {
      this.autosaveTimer = null;
      // Re-check rather than trusting the canSave() above: a manual save (or
      // another autosave) may have already caught up while this was pending,
      // and firing again would be a wasted, identical request.
      if (this.canSave()) this.save();
    }, AnswerKey.AUTOSAVE_DELAY_MS);
  }

  // Re-attaches the ResizeObserver if the .version-pills element changed (it
  // only exists once hasMultipleVersions() is true) and re-measures overflow.
  private syncVersionPillsObserver(): void {
    const el = this.host.nativeElement.querySelector('.version-pills') as HTMLElement | null;
    if (el === this.observedVersionPillsEl) {
      this.measureVersionPillsOverflow();
      return;
    }
    this.pillRowObserver?.disconnect();
    this.observedVersionPillsEl = el ?? undefined;
    if (!el) {
      this.versionStripHiddenCount.set(0);
      return;
    }
    // jsdom (unit tests) doesn't implement ResizeObserver; measuring once via
    // the call below still works there, it just won't react to later resizes.
    if (typeof ResizeObserver !== 'undefined') {
      this.pillRowObserver = new ResizeObserver(() => this.measureVersionPillsOverflow());
      this.pillRowObserver.observe(el);
    }
    this.measureVersionPillsOverflow();
  }

  // Pills past the first row are how many are hidden while collapsed.
  // Clipping is CSS-only (max-height + overflow), so this only needs to
  // count, not decide which ones are visible.
  private measureVersionPillsOverflow(): void {
    const el = this.observedVersionPillsEl;
    const pills = el ? Array.from(el.querySelectorAll<HTMLElement>('.version-pill')) : [];
    if (pills.length === 0) {
      this.versionStripHiddenCount.set(0);
      return;
    }
    const firstRowTop = pills[0].offsetTop;
    const visibleInFirstRow = pills.filter((pill) => pill.offsetTop === firstRowTop).length;
    this.versionStripHiddenCount.set(Math.max(0, pills.length - visibleInFirstRow));
  }

  private loadEverything(): void {
    this.isLoading.set(true);
    this.examService.getExam(this.examId).subscribe({
      next: (exam) => {
        this.examName.set(exam.name);
        this.examGeneratedPdfPath.set(exam.generated_pdf_path ?? null);
        this.examGraded.set(exam.has_any_grade);
        this.courseService.getCourse(exam.course_id).subscribe({
          next: (course) => this.courseName.set(course.name),
          error: () => { },
        });
        if (!exam.exam_template_id) {
          this.isLoading.set(false);
          this.error.set('This exam has no bubble-sheet template attached.');
          return;
        }
        this.templateService.getTemplate(exam.exam_template_id).subscribe({
          next: (template) => {
            this.template.set(template);
            this.loadKeys(template);
          },
          error: () => {
            this.isLoading.set(false);
            this.error.set("Failed to load the exam's template.");
          },
        });
      },
      error: () => {
        this.isLoading.set(false);
        this.error.set('Failed to load the exam.');
      },
    });
  }

  private loadKeys(template: ExamTemplateResponse): void {
    this.answerKeyService.listAnswerKeysByExam(this.examId).subscribe({
      next: (keys) => {
        this.isLoading.set(false);
        this.existingKeys.set(keys);
        this.answerKeyVersionDrafts.set({});
        this.scannedDraftVersions.set([]);
        const initialVersion = this.versionSlots()[0]?.version ?? null;
        const initialKey = keys.find((key) => key.exam_version === initialVersion);
        initialKey ? this.loadKeyIntoForm(initialKey) : this.startVersion(initialVersion);
        this.autoFinalizeTemplateIfReady();
      },
      error: () => {
        this.isLoading.set(false);
        this.startNewKey();
      },
    });
  }

  private blankDraftsFromTemplate(): QuestionDraft[] {
    const template = this.template();
    if (!template) return [];
    const keys = Object.keys(template.question_config).sort((a, b) => Number(a) - Number(b));
    return keys.map((k) => ({
      id: k,
      choices: [...template.question_config[k].choices],
      gradingType: 'single' as GradingType,
      correctChoices: [],
      partialWeights: {},
      points: DEFAULT_POINTS,
    }));
  }

  private isKeyComplete(key: ExamAnswerKeyResponse): boolean {
    const entries = Object.values(key.answer_key);
    return entries.length > 0 && entries.every((item) =>
      item.correct_choices.length > 0
      && (item.grading_type !== 'single' || item.correct_choices.length === 1)
      && (item.grading_type !== 'partial' || !!item.partial_weights),
    );
  }

  startNewKey(): void {
    const slot = this.versionSlots().find((candidate) => candidate.key === null)
      ?? this.versionSlots()[0];
    this.selectVersion(slot?.version ?? null);
  }

  selectVersion(version: string | null): void {
    this.stashCurrentVersionDraft();
    this.confirmingClearKeyId.set(null);
    const storedDraft = this.answerKeyVersionDrafts()[this.versionDraftKey(version)];
    if (storedDraft) {
      this.restoreAnswerKeyVersionDraft(storedDraft);
      return;
    }
    const key = this.existingKeys().find((candidate) => candidate.exam_version === version);
    key ? this.loadKeyIntoForm(key) : this.startVersion(version);
  }

  private startVersion(version: string | null): void {
    this.selectedKeyId.set(null);
    this.savedEntryCount.set(null);
    this.selectedVersion.set(version);
    this.questions.set(this.blankDraftsFromTemplate());
    this.questionsUsed.set(this.questions().length);
    this.pointsPerQuestion.set(1);
    this.activeQuestion.set(0);
    this.copySourceId = '';
    this.saved.set(false);
    this.sectionPointDrafts.set({});
    this.error.set('');
    this.baselineSnapshot.set(this.currentDraftSnapshot());
  }

  selectKey(key: ExamAnswerKeyResponse): void {
    this.stashCurrentVersionDraft();
    this.removeVersionDraft(key.exam_version);
    this.loadKeyIntoForm(key);
  }

  private loadKeyIntoForm(key: ExamAnswerKeyResponse): void {
    const template = this.template();
    if (!template) return;
    const keys = Object.keys(template.question_config).sort((a, b) => Number(a) - Number(b));
    const defaultPoints = key.scoring_rules?.['default_points_per_question']
      ?? key.scoring_rules?.['points_per_question']
      ?? DEFAULT_POINTS;
    this.selectedKeyId.set(key.id);
    this.selectedVersion.set(key.exam_version);
    this.questions.set(
      keys.map((k) => {
        const item = key.answer_key[k];
        return {
          id: k,
          choices: [...template.question_config[k].choices],
          gradingType: item?.grading_type ?? 'single',
          correctChoices: item ? [...item.correct_choices] : [],
          partialWeights: item?.partial_weights ? { ...item.partial_weights } : {},
          points: item ? (item.points ?? defaultPoints) : defaultPoints,
        };
      }),
    );
    const entryCount = Object.keys(key.answer_key).length;
    this.savedEntryCount.set(entryCount);
    this.questionsUsed.set(entryCount > 0 ? entryCount : this.questions().length);
    this.pointsPerQuestion.set(defaultPoints);
    this.activeQuestion.set(0);
    this.copySourceId = '';
    this.saved.set(false);
    this.sectionPointDrafts.set({});
    this.error.set('');
    this.baselineSnapshot.set(this.currentDraftSnapshot());
  }

  private versionDraftKey(version: string | null): string {
    return version ?? '__unversioned__';
  }

  private cloneQuestionDrafts(questions: QuestionDraft[]): QuestionDraft[] {
    return questions.map((question) => ({
      ...question,
      choices: [...question.choices],
      correctChoices: [...question.correctChoices],
      partialWeights: { ...question.partialWeights },
    }));
  }

  private stashCurrentVersionDraft(): void {
    if (this.questions().length === 0) return;
    const version = this.selectedVersion();
    if (!this.answerKeyScanTargetVersions().includes(version)) return;
    this.answerKeyVersionDrafts.update((drafts) => ({
      ...drafts,
      [this.versionDraftKey(version)]: this.captureCurrentVersionDraft(),
    }));
  }

  private captureCurrentVersionDraft(): AnswerKeyVersionDraft {
    return {
      version: this.selectedVersion(),
      selectedKeyId: this.selectedKeyId(),
      savedEntryCount: this.savedEntryCount(),
      questions: this.cloneQuestionDrafts(this.questions()),
      questionsUsed: this.questionsUsed(),
      pointsPerQuestion: this.pointsPerQuestion(),
      sectionPointDrafts: { ...this.sectionPointDrafts() },
      saved: this.saved(),
      baselineSnapshot: this.baselineSnapshot(),
    };
  }

  private restoreAnswerKeyVersionDraft(draft: AnswerKeyVersionDraft): void {
    this.selectedVersion.set(draft.version);
    this.selectedKeyId.set(draft.selectedKeyId);
    this.savedEntryCount.set(draft.savedEntryCount);
    this.questions.set(this.cloneQuestionDrafts(draft.questions));
    this.questionsUsed.set(draft.questionsUsed);
    this.pointsPerQuestion.set(draft.pointsPerQuestion);
    this.sectionPointDrafts.set({ ...draft.sectionPointDrafts });
    this.activeQuestion.set(0);
    this.copySourceId = '';
    this.saved.set(draft.saved);
    this.error.set('');
    this.baselineSnapshot.set(draft.baselineSnapshot);
  }

  private buildVersionDraft(version: string | null): AnswerKeyVersionDraft {
    const key = this.existingKeys().find((candidate) => candidate.exam_version === version);
    if (!key) {
      const questions = this.blankDraftsFromTemplate();
      return {
        version,
        selectedKeyId: null,
        savedEntryCount: null,
        questions,
        questionsUsed: questions.length,
        pointsPerQuestion: DEFAULT_POINTS,
        sectionPointDrafts: {},
        saved: false,
        baselineSnapshot: AnswerKey.snapshotOf(questions, questions.length, DEFAULT_POINTS),
      };
    }

    const template = this.template();
    const defaultPoints = key.scoring_rules?.['default_points_per_question']
      ?? key.scoring_rules?.['points_per_question']
      ?? DEFAULT_POINTS;
    const questions = this.blankDraftsFromTemplate().map((question) => {
      const item = key.answer_key[question.id];
      if (!item || !template) return question;
      return {
        ...question,
        gradingType: item.grading_type,
        correctChoices: [...item.correct_choices],
        partialWeights: item.partial_weights ? { ...item.partial_weights } : {},
        points: item.points ?? defaultPoints,
      };
    });
    const entryCount = Object.keys(key.answer_key).length;
    const questionsUsed = entryCount > 0 ? entryCount : questions.length;
    return {
      version,
      selectedKeyId: key.id,
      savedEntryCount: entryCount,
      questions,
      questionsUsed,
      pointsPerQuestion: defaultPoints,
      sectionPointDrafts: {},
      saved: false,
      baselineSnapshot: AnswerKey.snapshotOf(questions, questionsUsed, defaultPoints),
    };
  }

  private removeVersionDraft(version: string | null): void {
    const draftKey = this.versionDraftKey(version);
    this.answerKeyVersionDrafts.update((drafts) => {
      const { [draftKey]: _removed, ...remaining } = drafts;
      return remaining;
    });
    this.scannedDraftVersions.update((versions) => versions.filter((candidate) => candidate !== draftKey));
  }

  requestClearKey(key: ExamAnswerKeyResponse): void {
    this.confirmingClearKeyId.set(key.id);
  }

  cancelClearKey(): void {
    this.confirmingClearKeyId.set(null);
  }

  clearKey(key: ExamAnswerKeyResponse): void {
    if (this.confirmingClearKeyId() !== key.id || this.isClearingKey()) return;
    this.error.set('');
    this.isClearingKey.set(true);
    this.answerKeyService.deleteAnswerKey(key.id).subscribe({
      next: () => {
        this.isClearingKey.set(false);
        this.confirmingClearKeyId.set(null);
        this.existingKeys.update((list) => list.filter((k) => k.id !== key.id));
        this.removeVersionDraft(key.exam_version);
        this.refreshRequested.emit();
        if (this.selectedKeyId() !== key.id) return;
        this.startVersion(key.exam_version);
      },
      error: (err: { status?: number }) => {
        this.isClearingKey.set(false);
        this.error.set(
          err?.status === 403
            ? 'You can only clear an answer key for an exam you created.'
            : 'Failed to clear the answer key. Please try again.',
        );
      },
    });
  }

  // --- exam question cutoff (use fewer questions than the template has) ---
  setQuestionsUsed(value: number): void {
    const total = this.questions().length;
    const n = Math.min(total, Math.max(1, Math.floor(value || 0)));
    const savedCount = this.savedEntryCount();
    // The backend PATCH merges answer_key entries and can't delete them, so a
    // saved key can't lose questions.
    if (this.selectedKeyId() !== null && savedCount !== null && n < savedCount) {
      this.error.set(
        `This key is saved with ${savedCount} questions. Reducing the count isn't supported yet — create a new key instead.`,
      );
      return;
    }
    this.error.set('');
    this.saved.set(false);
    this.questionsUsed.set(n);
    if (this.activeQuestion() >= n) this.activeQuestion.set(n - 1);
  }

  // --- copy values from another version's key ---
  copyFromSelected(): void {
    const source = this.existingKeys().find((k) => k.id === this.copySourceId);
    if (!source) return;
    const defaultPoints = source.scoring_rules?.['default_points_per_question']
      ?? source.scoring_rules?.['points_per_question']
      ?? DEFAULT_POINTS;
    this.questions.update((qs) =>
      qs.map((q) => {
        const item = source.answer_key[q.id];
        if (!item) return q;
        return {
          id: q.id,
          choices: q.choices,
          gradingType: item.grading_type,
          correctChoices: [...item.correct_choices],
          partialWeights: item.partial_weights ? { ...item.partial_weights } : {},
          points: item.points ?? defaultPoints,
        };
      }),
    );
    const sourceCount = Object.keys(source.answer_key).length;
    const floor = this.selectedKeyId() !== null ? (this.savedEntryCount() ?? 1) : 1;
    this.questionsUsed.set(Math.max(sourceCount, floor));
    this.pointsPerQuestion.set(defaultPoints);
    this.saved.set(false);
    this.error.set('');
  }

  openUploadModal(tab: 'scan' | 'import' = 'scan'): void {
    if (this.isUploadingAnswerKeyScan() || this.isImporting()) return;
    this.stagedScanFiles.set([]);
    this.stagedImportFiles.set([]);
    this.importResult.set(null);
    this.error.set('');
    this.uploadModalTab.set(tab);
    this.uploadModalOpen.set(true);
  }

  closeUploadModal(): void {
    if (this.isUploadingAnswerKeyScan() || this.isImporting()) return;
    this.uploadModalOpen.set(false);
  }

  selectUploadModalTab(tab: 'scan' | 'import'): void {
    this.uploadModalTab.set(tab);
  }

  // --- import: each selected JSON or CSV export is created as its own answer
  // key immediately, no manual save. ---
  onImportFilesChosen(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.stagedImportFiles.set(input.files ? Array.from(input.files) : []);
    input.value = ''; // allow re-selecting the same file(s) after a failed import
    this.importResult.set(null);
    this.error.set('');
  }

  removeStagedImportFile(file: File): void {
    this.stagedImportFiles.update((files) => files.filter((f) => f !== file));
  }

  clearStagedImportFiles(): void {
    this.stagedImportFiles.set([]);
    this.importResult.set(null);
    this.error.set('');
  }

  importStagedFiles(): void {
    const files = this.stagedImportFiles();
    if (files.length === 0) return;
    const template = this.template();
    if (!template) return;

    this.error.set('');
    this.importResult.set(null);
    this.isImporting.set(true);
    this.runImport(files, template.id);
  }

  private async runImport(files: File[], templateId: string): Promise<void> {
    const failures: { filename: string; message: string }[] = [];
    let importedCount = 0;
    let lastImported: ExamAnswerKeyResponse | null = null;

    for (const file of files) {
      try {
        const payload = this.buildImportPayload(await this.parseImportFile(file), templateId);
        const key = await firstValueFrom(this.answerKeyService.createAnswerKey(this.examId, payload));
        importedCount++;
        lastImported = key;
        this.existingKeys.update((list) => [key, ...list.filter((k) => k.id !== key.id)]);
      } catch (err) {
        failures.push({ filename: file.name, message: this.importErrorMessage(err) });
      }
    }

    this.isImporting.set(false);
    this.stagedImportFiles.set([]);
    this.importResult.set({ imported: importedCount, total: files.length, failures });
    if (lastImported) this.selectKey(lastImported);
    if (importedCount > 0) this.refreshRequested.emit();
    this.autoFinalizeTemplateIfReady();
  }

  // Choices always come from this exam's template, never the file — the file
  // only supplies which choice(s) are correct. Invalid choices are caught by
  // the backend's usual answer-key validation.
  private buildImportPayload(parsed: unknown, templateId: string): CreateExamAnswerKeyRequest {
    if (!parsed || typeof parsed !== 'object') {
      throw new Error("doesn't look like an answer-key export");
    }
    const { questions, exam_version, default_points_per_question } = parsed as {
      questions?: unknown;
      exam_version?: string | null;
      default_points_per_question?: number;
    };
    if (!questions || typeof questions !== 'object') {
      throw new Error('missing "questions" field');
    }

    const answer_key: Record<string, AnswerKeyItem> = {};
    for (const [q, item] of Object.entries(questions as Record<string, Partial<AnswerKeyItem>>)) {
      answer_key[q] = {
        grading_type: this.gradingTypes.includes(item.grading_type as GradingType)
          ? (item.grading_type as GradingType)
          : 'single',
        correct_choices: Array.isArray(item.correct_choices) ? item.correct_choices : [],
        points: typeof item.points === 'number' ? item.points : null,
        partial_weights:
          item.partial_weights && typeof item.partial_weights === 'object' ? item.partial_weights : null,
      };
    }

    return {
      exam_template_id: templateId,
      exam_version: exam_version || null,
      answer_key,
      scoring_rules:
        typeof default_points_per_question === 'number'
          ? { default_points_per_question }
          : null,
    };
  }

  private async parseImportFile(file: File): Promise<unknown> {
    const content = await file.text();
    if (file.name.toLowerCase().endsWith('.csv') || file.type.toLowerCase() === 'text/csv') {
      return this.parseCsvImport(content);
    }
    return JSON.parse(content);
  }

  private parseCsvImport(content: string): unknown {
    const rows = this.parseCsvRows(content);
    const [header, ...dataRows] = rows;
    if (!header?.length) throw new Error('CSV file is empty');
    const columns = header.map((value) => value.trim().toLowerCase());
    const questionColumn = columns.indexOf('question');
    const choicesColumn = columns.indexOf('correct_choices');
    if (questionColumn < 0 || choicesColumn < 0) {
      throw new Error('CSV must include "question" and "correct_choices" columns');
    }

    const valueAt = (row: string[], name: string): string => {
      const index = columns.indexOf(name);
      return index >= 0 ? (row[index] ?? '').trim() : '';
    };
    const questions: Record<string, Partial<AnswerKeyItem>> = {};
    let examVersion: string | null = null;
    let defaultPoints: number | undefined;
    for (const row of dataRows) {
      const question = (row[questionColumn] ?? '').trim();
      if (!question) continue;
      const pointsText = valueAt(row, 'points');
      const partialWeightsText = valueAt(row, 'partial_weights');
      let partialWeights: Record<string, number> | null = null;
      if (partialWeightsText && partialWeightsText !== '{}') {
        try {
          const parsed = JSON.parse(partialWeightsText);
          partialWeights = parsed && typeof parsed === 'object' ? parsed : null;
        } catch {
          throw new Error(`Question ${question} has invalid partial_weights JSON`);
        }
      }
      questions[question] = {
        grading_type: valueAt(row, 'grading_type') as GradingType || 'single',
        correct_choices: valueAt(row, 'correct_choices').split(/[|;,]/).map((choice) => choice.trim()).filter(Boolean),
        points: pointsText === '' ? null : Number(pointsText),
        partial_weights: partialWeights,
      };
      examVersion ??= valueAt(row, 'exam_version') || null;
      const defaultPointsText = valueAt(row, 'default_points_per_question');
      if (defaultPoints === undefined && defaultPointsText !== '') defaultPoints = Number(defaultPointsText);
    }
    if (Object.keys(questions).length === 0) throw new Error('CSV contains no question rows');
    return {
      exam_version: examVersion,
      default_points_per_question: defaultPoints,
      questions,
    };
  }

  private parseCsvRows(content: string): string[][] {
    const rows: string[][] = [];
    let row: string[] = [];
    let value = '';
    let quoted = false;
    for (let index = 0; index < content.length; index++) {
      const character = content[index];
      if (character === '"') {
        if (quoted && content[index + 1] === '"') {
          value += '"';
          index++;
        } else {
          quoted = !quoted;
        }
      } else if (character === ',' && !quoted) {
        row.push(value);
        value = '';
      } else if ((character === '\n' || character === '\r') && !quoted) {
        if (character === '\r' && content[index + 1] === '\n') index++;
        row.push(value);
        if (row.some((cell) => cell.trim())) rows.push(row);
        row = [];
        value = '';
      } else {
        value += character;
      }
    }
    if (quoted) throw new Error('CSV has an unclosed quoted value');
    row.push(value);
    if (row.some((cell) => cell.trim())) rows.push(row);
    return rows;
  }

  private importErrorMessage(err: unknown): string {
    if (err instanceof SyntaxError) return 'not valid JSON';
    const e = err as { status?: number; error?: { error?: { message?: string } } } | Error;
    const backendMessage = (e as { error?: { error?: { message?: string } } })?.error?.error?.message;
    if (backendMessage) return backendMessage;
    if (e instanceof Error) return e.message;
    return 'import failed';
  }

  // --- scanned answer-key upload: extraction is retained for the matching
  // and confirmation step; it does not modify or save the current draft. ---
  onScanFilesChosen(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.stagedScanFiles.set(input.files ? Array.from(input.files) : []);
    input.value = ''; // allow re-selecting the same file(s) after validation/API errors
    this.error.set('');
  }

  removeStagedScanFile(file: File): void {
    this.stagedScanFiles.update((files) => files.filter((f) => f !== file));
  }

  clearStagedScanFiles(): void {
    this.stagedScanFiles.set([]);
    this.error.set('');
  }

  uploadStagedScans(): void {
    const files = this.stagedScanFiles();
    if (files.length === 0 || this.isUploadingAnswerKeyScan()) return;

    for (const file of files) {
      if (!file.name.toLowerCase().endsWith('.pdf')
        || (file.type && !PDF_CONTENT_TYPES.has(file.type.toLowerCase()))) {
        this.error.set(`${file.name}: please select a PDF answer key.`);
        return;
      }
      if (file.size > MAX_ANSWER_KEY_SCAN_BYTES) {
        this.error.set(`${file.name}: the answer-key PDF must be 10 MB or smaller.`);
        return;
      }
    }

    this.answerKeyScanExtraction.set(null);
    this.answerKeyScanReviewOpen.set(false);
    this.answerKeyScanMatches.set([]);
    this.answerKeyScanMatchError.set('');
    this.confirmedAnswerKeyScanMatches.set(null);
    this.scanAutoSaveResult.set(null);
    this.expandedScanSheets.set(new Set());
    this.error.set('');
    this.isUploadingAnswerKeyScan.set(true);
    this.answerKeyService.extractAnswerKeyScan(
      this.examId,
      files,
      this.questionsUsed(),
    ).subscribe({
      next: (extraction) => {
        this.isUploadingAnswerKeyScan.set(false);
        this.uploadModalOpen.set(false);
        this.stagedScanFiles.set([]);
        this.initializeAnswerKeyScanMatching(extraction);
      },
      error: (err) => {
        this.isUploadingAnswerKeyScan.set(false);
        this.error.set(this.answerKeyScanUploadErrorMessage(err));
      },
    });
  }

  private initializeAnswerKeyScanMatching(extraction: ExtractAnswerKeyScanBatchResponse): void {
    this.answerKeyScanExtraction.set(extraction);
    this.answerKeyScanMatchingMode.set('automatic');
    this.answerKeyScanMatches.set(this.buildAutomaticAnswerKeyScanMatches(extraction));
    this.answerKeyScanMatchError.set('');
    this.confirmedAnswerKeyScanMatches.set(null);
    this.answerKeyScanReviewOpen.set(true);
  }

  setAnswerKeyScanMatchingMode(mode: AnswerKeyScanMatchingMode): void {
    const extraction = this.answerKeyScanExtraction();
    if (!extraction) return;

    this.answerKeyScanMatchingMode.set(mode);
    this.answerKeyScanMatchError.set('');
    this.confirmedAnswerKeyScanMatches.set(null);
    if (mode === 'automatic') {
      this.answerKeyScanMatches.set(this.buildAutomaticAnswerKeyScanMatches(extraction));
    } else if (mode === 'ordered') {
      this.answerKeyScanMatches.set(this.buildOrderedAnswerKeyScanMatches(extraction));
    } else {
      this.answerKeyScanMatches.set(extraction.sheets.map((sheet) => ({
        sheetIndex: sheet.sheet_index,
        action: 'apply',
        targetVersion: undefined,
      })));
    }
  }

  private buildAutomaticAnswerKeyScanMatches(
    extraction: ExtractAnswerKeyScanBatchResponse,
  ): AnswerKeyScanMatchDraft[] {
    const targets = this.answerKeyScanTargetVersions();
    if (targets.length === 1 && targets[0] === null) {
      return extraction.sheets.map((sheet) => ({
        sheetIndex: sheet.sheet_index,
        action: 'apply',
        targetVersion: extraction.sheets.length === 1 ? null : undefined,
      }));
    }

    const allowed = new Set(targets.filter((target): target is string => target !== null));
    const detected = extraction.sheets.map((sheet) => {
      const version = sheet.version.status === 'detected'
        ? sheet.version.detected_version?.toUpperCase() ?? null
        : null;
      return version && allowed.has(version) ? version : null;
    });
    const counts = new Map<string, number>();
    for (const version of detected) {
      if (version) counts.set(version, (counts.get(version) ?? 0) + 1);
    }

    return extraction.sheets.map((sheet, index) => {
      const version = detected[index];
      return {
        sheetIndex: sheet.sheet_index,
        action: 'apply',
        targetVersion: version && counts.get(version) === 1 ? version : undefined,
      };
    });
  }

  private buildOrderedAnswerKeyScanMatches(
    extraction: ExtractAnswerKeyScanBatchResponse,
  ): AnswerKeyScanMatchDraft[] {
    const targets = this.answerKeyScanTargetVersions();
    return extraction.sheets.map((sheet, index) => ({
      sheetIndex: sheet.sheet_index,
      action: 'apply',
      targetVersion: index < targets.length ? targets[index] : undefined,
    }));
  }

  answerKeyScanMatchFor(sheetIndex: number): AnswerKeyScanMatchDraft | undefined {
    return this.answerKeyScanMatches().find((match) => match.sheetIndex === sheetIndex);
  }

  answerKeyScanTargetValue(match: AnswerKeyScanMatchDraft): string {
    if (match.action === 'skip') return '__skip__';
    if (match.targetVersion === undefined) return '__unresolved__';
    return match.targetVersion === null ? '__unversioned__' : match.targetVersion;
  }

  setAnswerKeyScanSheetTarget(sheetIndex: number, value: string): void {
    const current = this.answerKeyScanMatchFor(sheetIndex);
    if (!current) return;

    if (value === '__skip__') {
      this.updateAnswerKeyScanMatch(sheetIndex, 'skip', undefined);
      return;
    }
    if (value === '__unresolved__') {
      this.updateAnswerKeyScanMatch(sheetIndex, 'apply', undefined);
      return;
    }

    const target = value === '__unversioned__' ? null : value;
    if (!this.answerKeyScanTargetVersions().includes(target)) {
      this.answerKeyScanMatchError.set('That version is not used by this exam.');
      return;
    }
    if (this.isAnswerKeyScanVersionAssigned(target, sheetIndex)) {
      this.answerKeyScanMatchError.set(
        `${this.answerKeyScanTargetLabel(target)} is already assigned to another sheet.`,
      );
      return;
    }
    this.updateAnswerKeyScanMatch(sheetIndex, 'apply', target);
  }

  private updateAnswerKeyScanMatch(
    sheetIndex: number,
    action: AnswerKeyScanMatchAction,
    targetVersion: string | null | undefined,
  ): void {
    this.answerKeyScanMatches.update((matches) => matches.map((match) =>
      match.sheetIndex === sheetIndex
        ? { ...match, action, targetVersion }
        : match,
    ));
    this.answerKeyScanMatchError.set('');
    this.confirmedAnswerKeyScanMatches.set(null);
  }

  isAnswerKeyScanVersionAssigned(target: string | null, exceptSheetIndex: number): boolean {
    return this.answerKeyScanMatches().some((match) =>
      match.sheetIndex !== exceptSheetIndex
      && match.action === 'apply'
      && this.isAnswerKeyScanMatchResolved(match)
      && match.targetVersion === target,
    );
  }

  private isAnswerKeyScanMatchResolved(match: AnswerKeyScanMatchDraft): boolean {
    if (match.action === 'skip') return true;
    if (match.targetVersion === undefined) return false;
    return this.answerKeyScanTargetVersions().includes(match.targetVersion);
  }

  answerKeyScanTargetLabel(version: string | null): string {
    return version === null ? 'Answer key' : `Version ${version}`;
  }

  answerKeyScanPageLabel(sheet: ExtractedAnswerKeySheet): string {
    return sheet.page_start === sheet.page_end
      ? `Page ${sheet.page_start}`
      : `Pages ${sheet.page_start}–${sheet.page_end}`;
  }

  answerKeyScanConfidenceLabel(confidence: number | null): string {
    return confidence === null ? 'Not available' : `${Math.round(confidence * 100)}%`;
  }

  answerKeyScanDetectedVersionLabel(sheet: ExtractedAnswerKeySheet): string {
    if (sheet.version.status === 'not_applicable') return 'Not applicable';
    if (sheet.version.status === 'missing') return 'Not detected';
    if (sheet.version.status === 'ambiguous') {
      return sheet.version.selected_choices.length > 0
        ? `${sheet.version.selected_choices.join(', ')} (ambiguous)`
        : 'Ambiguous';
    }
    const version = sheet.version.detected_version ?? sheet.version.selected_choices[0];
    const invalid = sheet.warnings.some((warning) => warning.code === 'version_invalid');
    const duplicate = sheet.warnings.some((warning) => warning.code === 'version_duplicate');
    if (invalid) return `Version ${version} (invalid)`;
    if (duplicate) return `Version ${version} (duplicate)`;
    return `Version ${version}`;
  }

  answerKeyScanHasVersionProblem(sheet: ExtractedAnswerKeySheet): boolean {
    return sheet.version.status === 'missing'
      || sheet.version.status === 'ambiguous'
      || sheet.warnings.some((warning) =>
        warning.code === 'version_invalid' || warning.code === 'version_duplicate',
      );
  }

  // Expand a sheet's row in the match modal to see what OMR detected for
  // every question, as plain letters, rather than a separate annotated view.
  isScanSheetExpanded(sheetIndex: number): boolean {
    return this.expandedScanSheets().has(sheetIndex);
  }

  toggleScanSheetExpanded(sheetIndex: number): void {
    this.expandedScanSheets.update((expanded) => {
      const next = new Set(expanded);
      next.has(sheetIndex) ? next.delete(sheetIndex) : next.add(sheetIndex);
      return next;
    });
  }

  sortedAnswerEntries(sheet: ExtractedAnswerKeySheet): { id: string; question: ExtractedAnswerKeyQuestion }[] {
    return Object.entries(sheet.answers)
      .map(([id, question]) => ({ id, question }))
      .sort((a, b) => Number(a.id) - Number(b.id));
  }

  answerKeyScanAnswerLabel(question: ExtractedAnswerKeyQuestion): string {
    return question.selected_choices.length > 0 ? question.selected_choices.join(', ') : 'Blank';
  }

  confirmAnswerKeyScanMatches(): void {
    if (this.answerKeyScanMatchValidationError()) return;

    const confirmation: ConfirmAnswerKeyScanMatchesRequest = {
      matching_mode: this.answerKeyScanMatchingMode(),
      matches: this.answerKeyScanMatches().map((match) => ({
        sheet_index: match.sheetIndex,
        action: match.action,
        target_version: match.action === 'skip' ? null : (match.targetVersion ?? null),
      })),
      overwrite_existing: false,
    };
    this.confirmedAnswerKeyScanMatches.set(confirmation);
    this.applyConfirmedAnswerKeyScanSelections(confirmation);
    this.answerKeyScanMatchError.set('');
    this.answerKeyScanReviewOpen.set(false);

    const appliedVersions = confirmation.matches
      .filter((match) => match.action === 'apply')
      .map((match) => match.target_version);
    this.autoSaveScannedVersions(appliedVersions);
  }

  // Auto-save: once a scan match is confirmed, save every version it
  // touched immediately rather than requiring the instructor to revisit each
  // one (or wait for autosave) before the sheets are actually persisted.
  private async autoSaveScannedVersions(versions: (string | null)[]): Promise<void> {
    if (versions.length === 0) return;
    this.isSaving.set(true);
    this.isSavingScannedVersions.set(true);
    this.scanAutoSaveResult.set(null);

    const results = await Promise.all(versions.map((version) => this.saveVersionDraft(version)));
    const failures = results.filter(
      (failure): failure is { version: string | null; message: string } => failure !== null,
    );

    this.isSaving.set(false);
    this.isSavingScannedVersions.set(false);
    this.scanAutoSaveResult.set({ saved: versions.length - failures.length, total: versions.length, failures });
    this.refreshRequested.emit();
    this.autoFinalizeTemplateIfReady();
  }

  // Saves one version's draft, whether or not it's the currently active one:
  // reads live signals for the active version (so in-progress edits aren't
  // lost) and the stashed draft for any other.
  private async saveVersionDraft(version: string | null): Promise<{ version: string | null; message: string } | null> {
    const template = this.template();
    if (!template) return { version, message: 'The exam template is not loaded.' };

    const isActive = version === this.selectedVersion();
    const draftKey = this.versionDraftKey(version);
    const stored = this.answerKeyVersionDrafts()[draftKey];
    const questions = isActive
      ? this.visibleQuestions()
      : (stored?.questions.slice(0, stored.questionsUsed) ?? []);
    const questionsUsed = isActive ? this.questionsUsed() : (stored?.questionsUsed ?? questions.length);
    const pointsPerQuestion = isActive ? this.pointsPerQuestion() : (stored?.pointsPerQuestion ?? DEFAULT_POINTS);
    const selectedKeyId = isActive ? this.selectedKeyId() : (stored?.selectedKeyId ?? null);
    // What this version's draft looked like as of this request, compared
    // against its state again once the request resolves (see
    // applySavedScannedKey), since the version this save was sent for may no
    // longer be active, or may have been edited further, by the time it does.
    const sentSnapshot = AnswerKey.snapshotOf(isActive ? this.questions() : (stored?.questions ?? []), questionsUsed, pointsPerQuestion);

    const validation = AnswerKey.validateQuestions(questions);
    if (validation) return { version, message: validation };

    const answer_key = AnswerKey.buildAnswerKeyPayload(questions);
    const scoring_rules = { default_points_per_question: pointsPerQuestion };

    try {
      const key = await firstValueFrom(
        selectedKeyId
          ? this.answerKeyService.updateAnswerKey(selectedKeyId, { answer_key, scoring_rules })
          : this.answerKeyService.createAnswerKey(this.examId, {
            exam_template_id: template.id,
            exam_version: version,
            answer_key,
            scoring_rules,
          }),
      );
      this.applySavedScannedKey(version, key, sentSnapshot);
      return null;
    } catch (err) {
      return { version, message: this.saveErrorMessage(err as { status?: number; error?: { error?: { message?: string } } }) };
    }
  }

  // Applied against whichever version is *currently* active/stashed, not
  // whichever was active when the request was sent, since the instructor may
  // have switched versions, or edited this same version further, while the
  // save was in flight. selectedKeyId/savedEntryCount are always safe to
  // record (the create/update did happen), but the "saved" flag and
  // baseline only get cleared if the draft still matches what was sent.
  private applySavedScannedKey(version: string | null, key: ExamAnswerKeyResponse, sentSnapshot: string): void {
    this.existingKeys.update((list) => [key, ...list.filter((k) => k.id !== key.id)]);
    const draftKey = this.versionDraftKey(version);
    this.scannedDraftVersions.update((versions) => versions.filter((v) => v !== draftKey));
    const savedEntryCount = Object.keys(key.answer_key).length;

    if (version === this.selectedVersion()) {
      this.selectedKeyId.set(key.id);
      this.savedEntryCount.set(savedEntryCount);
      if (this.currentDraftSnapshot() === sentSnapshot) {
        this.saved.set(true);
        this.baselineSnapshot.set(sentSnapshot);
      }
      this.stashCurrentVersionDraft();
      return;
    }

    // Not the active version: patch the stashed draft directly so
    // switching to it later reflects the save instead of showing a false
    // "unsaved changes" badge.
    this.answerKeyVersionDrafts.update((drafts) => {
      const existing = drafts[draftKey];
      if (!existing) return drafts;
      const currentSnapshot = AnswerKey.snapshotOf(existing.questions, existing.questionsUsed, existing.pointsPerQuestion);
      const matchesSent = currentSnapshot === sentSnapshot;
      return {
        ...drafts,
        [draftKey]: {
          ...existing,
          selectedKeyId: key.id,
          savedEntryCount,
          saved: matchesSent ? true : existing.saved,
          baselineSnapshot: matchesSent ? sentSnapshot : existing.baselineSnapshot,
        },
      };
    });
  }

  private applyConfirmedAnswerKeyScanSelections(
    confirmation: ConfirmAnswerKeyScanMatchesRequest,
  ): void {
    const extraction = this.answerKeyScanExtraction();
    if (!extraction) return;

    this.stashCurrentVersionDraft();
    const sheetsByIndex = new Map(
      extraction.sheets.map((sheet) => [sheet.sheet_index, sheet]),
    );
    const drafts = { ...this.answerKeyVersionDrafts() };
    const scannedVersions = new Set(this.scannedDraftVersions());
    let firstAppliedVersion: string | null | undefined;

    for (const match of confirmation.matches) {
      if (match.action === 'skip') continue;
      const sheet = sheetsByIndex.get(match.sheet_index);
      if (!sheet) continue;

      const version = match.target_version;
      const draftKey = this.versionDraftKey(version);
      const baseDraft = drafts[draftKey] ?? this.buildVersionDraft(version);
      const questions = baseDraft.questions.map((question) => {
        const extracted = sheet.answers[question.id];
        return extracted
          ? { ...question, correctChoices: [...extracted.selected_choices] }
          : question;
      });
      const extractedQuestionCount = Object.keys(sheet.answers).length;
      const savedFloor = baseDraft.selectedKeyId ? (baseDraft.savedEntryCount ?? 0) : 0;
      const questionsUsed = Math.min(
        questions.length,
        Math.max(1, extractedQuestionCount, savedFloor),
      );

      drafts[draftKey] = {
        ...baseDraft,
        questions: this.cloneQuestionDrafts(questions),
        questionsUsed,
        saved: false,
      };
      scannedVersions.add(draftKey);
      if (firstAppliedVersion === undefined) firstAppliedVersion = version;
    }

    this.answerKeyVersionDrafts.set(drafts);
    this.scannedDraftVersions.set([...scannedVersions]);
    if (firstAppliedVersion !== undefined) {
      this.restoreAnswerKeyVersionDraft(drafts[this.versionDraftKey(firstAppliedVersion)]);
    }
  }

  cancelAnswerKeyScanMatching(): void {
    this.answerKeyScanReviewOpen.set(false);
    this.answerKeyScanExtraction.set(null);
    this.answerKeyScanMatches.set([]);
    this.answerKeyScanMatchError.set('');
    this.confirmedAnswerKeyScanMatches.set(null);
  }

  private answerKeyScanUploadErrorMessage(
    err: { status?: number; error?: { error?: { message?: string } } } | null,
  ): string {
    const backendMessage = err?.error?.error?.message;
    if (backendMessage) return backendMessage;
    if (err?.status === 413) return 'The answer-key PDF must be 10 MB or smaller.';
    if (err?.status === 403) return 'You can only upload an answer key for an exam you created.';
    if (err?.status === 502) return 'The OMR service could not scan this answer key. Please try again.';
    return 'Failed to scan the answer-key PDF. Please try again.';
  }

  // --- keyboard entry: type a choice label to answer, arrows/Enter to move ---
  @HostListener('window:keydown', ['$event'])
  handleKeydown(event: KeyboardEvent): void {
    if (this.isLoading() || !this.template() || this.examGraded()) return;
    const target = event.target as HTMLElement | null;
    if (target && ['INPUT', 'SELECT', 'TEXTAREA'].includes(target.tagName)) return;
    const order = this.answerSections().flatMap((section) => section.questions.map(({ index }) => index));
    if (order.length === 0) return;
    const idx = order.includes(this.activeQuestion()) ? this.activeQuestion() : order[0];
    const position = order.indexOf(idx);

    if (event.key === 'ArrowDown' || event.key === 'Enter') {
      this.activateQuestion(order[Math.min(position + 1, order.length - 1)]);
      event.preventDefault();
      return;
    }
    if (event.key === 'ArrowUp') {
      this.activateQuestion(order[Math.max(position - 1, 0)]);
      event.preventDefault();
      return;
    }
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      const direction = event.key === 'ArrowRight' ? 1 : -1;
      const section = this.answerSections().find((candidate) =>
        candidate.questions.some(({ index }) => index === idx),
      );
      const localIndex = section?.questions.findIndex(({ index }) => index === idx) ?? -1;
      const target = localIndex + direction * (section?.gridRows ?? 0);
      if (section && target >= 0 && target < section.questions.length) {
        this.activateQuestion(section.questions[target].index);
      }
      event.preventDefault();
      return;
    }
    if (event.key === 'Delete' || event.key === 'Backspace') {
      this.questions.update((questions) => questions.map((question, index) =>
        index === idx
          ? {
            ...question,
            correctChoices: [],
            partialWeights: question.gradingType === 'partial'
              ? this.defaultPartialWeights(question.choices, [])
              : question.partialWeights,
          }
          : question,
      ));
      this.saved.set(false);
      event.preventDefault();
      return;
    }
    if (event.key.length !== 1) return;
    const letter = event.key.toUpperCase();
    const q = this.visibleQuestions()[idx];
    if (q.choices.includes(letter)) {
      this.toggleCorrect(idx, letter);
      // Single-answer questions auto-advance; multi/partial stay so you can
      // toggle several choices.
      if (q.gradingType === 'single') {
        this.activateQuestion(order[Math.min(position + 1, order.length - 1)]);
      }
      event.preventDefault();
    }
  }

  setActive(index: number, event?: MouseEvent): void {
    this.activateQuestion(index);
    const target = event?.target as HTMLElement | null;
    if (!target?.closest('input, select, textarea')) {
      (document.activeElement as HTMLElement | null)?.blur();
    }
  }

  private activateQuestion(index: number): void {
    this.activeQuestion.set(index);
    setTimeout(() => {
      const selector = `[data-question-index="${index}"]`;
      const activeQuestion = this.host.nativeElement.querySelector(selector) as HTMLElement | null;
      activeQuestion?.scrollIntoView?.({
        behavior: 'smooth',
        block: 'center',
        inline: 'nearest',
      });
    });
  }

  // --- answer selection ---
  isCorrect(q: QuestionDraft, label: string): boolean {
    return q.correctChoices.includes(label);
  }

  weightPercent(q: QuestionDraft, label: string): number {
    return Math.floor((q.partialWeights[label] ?? 0) * 100);
  }

  toggleCorrect(index: number, label: string): void {
    this.saved.set(false);
    this.questions.update((qs) =>
      qs.map((q, i) => {
        if (i !== index) return q;
        if (q.gradingType === 'single') return { ...q, correctChoices: [label] };
        const has = q.correctChoices.includes(label);
        const correctChoices = has
          ? q.correctChoices.filter((c) => c !== label)
          : [...q.correctChoices, label];
        return {
          ...q,
          correctChoices,
          partialWeights: q.gradingType === 'partial'
            ? this.defaultPartialWeights(q.choices, correctChoices)
            : q.partialWeights,
        };
      }),
    );
  }

  // --- grading rules ---
  setGradingType(index: number, type: GradingType): void {
    this.saved.set(false);
    this.questions.update((qs) =>
      qs.map((q, i) => i === index ? this.withGradingType(q, type) : q),
    );
  }

  sectionGradingType(section: AnswerSection): GradingType | '' {
    const types = new Set(section.questions.map(({ question }) => question.gradingType));
    return types.size === 1 ? section.questions[0].question.gradingType : '';
  }

  applySectionGradingType(section: AnswerSection, type: GradingType): void {
    const indexes = new Set(section.questions.map(({ index }) => index));
    this.questions.update((questions) => questions.map((question, index) =>
      indexes.has(index) ? this.withGradingType(question, type) : question,
    ));
    this.saved.set(false);
  }

  setSectionPointDraft(sectionId: string, value: number | null): void {
    this.sectionPointDrafts.update((drafts) => ({ ...drafts, [sectionId]: value }));
  }

  applySectionPoints(section: AnswerSection): void {
    const points = this.sectionPointDrafts()[section.id];
    if (points === null || points === undefined || !Number.isFinite(points) || points < 0) return;
    const indexes = new Set(section.questions.map(({ index }) => index));
    this.questions.update((questions) => questions.map((question, index) =>
      indexes.has(index) ? { ...question, points } : question,
    ));
    this.saved.set(false);
  }

  setWeight(index: number, label: string, value: number): void {
    this.saved.set(false);
    // Clamp each weight to 0-1 here rather than only flagging via
    // validationError -- the number input's min/max attrs only constrain
    // the spinner arrows, not typed or pasted values, so an unclamped
    // weight could otherwise sit in state as e.g. 5 (500%) or -0.2 (-20%).
    //
    // Deliberately NOT also clamping against the *other* correct choices'
    // current weights here (e.g. capping A once A+B would exceed 1): a
    // student can mark every correct choice at once, so the grader does sum
    // them (see _score_question in grading_service.py, clamped to `points`
    // at the end) and an answer key whose weights add up past 100% is bad
    // data -- but doing that clamp per-keystroke fights normal editing,
    // since raising A while B still holds its old value would immediately
    // (and confusingly) claw A back down before the user gets to B. That
    // combined-total check instead happens once, in validationError, the
    // same way it already does for the single-invalid-weight case below.
    const clamped = Number.isFinite(value) ? Math.min(1, Math.max(0, value)) : 0;
    this.questions.update((questions) => questions.map((question, questionIndex) =>
      questionIndex === index
        ? { ...question, partialWeights: { ...question.partialWeights, [label]: clamped } }
        : question,
    ));
  }

  setPoints(index: number, value: number | null): void {
    this.saved.set(false);
    this.questions.update((qs) =>
      qs.map((q, i) => (i === index ? { ...q, points: value } : q)),
    );
  }

  private withGradingType(question: QuestionDraft, type: GradingType): QuestionDraft {
    if (type === 'single') {
      return {
        ...question,
        gradingType: type,
        correctChoices: question.correctChoices.slice(0, 1),
        partialWeights: {},
      };
    }
    if (type === 'partial') {
      return {
        ...question,
        gradingType: type,
        partialWeights: this.defaultPartialWeights(question.choices, question.correctChoices),
      };
    }
    return { ...question, gradingType: type, partialWeights: {} };
  }

  // --- save ---
  save(): void {
    const validation = this.validationError();
    if (validation) {
      this.error.set(validation);
      return;
    }
    const template = this.template();
    if (!template) return;
    this.error.set('');
    this.isSaving.set(true);

    const answer_key = this.buildAnswerKey();
    const scoring_rules = { default_points_per_question: this.pointsPerQuestion() };

    const id = this.selectedKeyId();
    const request$ = id
      ? this.answerKeyService.updateAnswerKey(id, { answer_key, scoring_rules })
      : this.answerKeyService.createAnswerKey(this.examId, {
        exam_template_id: template.id,
        exam_version: this.selectedVersion(),
        answer_key,
        scoring_rules,
      });

    request$.subscribe({
      next: (key) => {
        this.isSaving.set(false);
        this.saved.set(true);
        this.selectedKeyId.set(key.id);
        this.selectedVersion.set(key.exam_version);
        this.savedEntryCount.set(Object.keys(key.answer_key).length);
        this.existingKeys.update((list) => {
          const others = list.filter((k) => k.id !== key.id);
          return [key, ...others];
        });
        this.baselineSnapshot.set(this.currentDraftSnapshot());
        this.stashCurrentVersionDraft();
        const savedDraftKey = this.versionDraftKey(key.exam_version);
        this.scannedDraftVersions.update((versions) =>
          versions.filter((version) => version !== savedDraftKey),
        );
        this.refreshRequested.emit();
        this.autoFinalizeTemplateIfReady();
      },
      error: (err) => {
        this.isSaving.set(false);
        this.error.set(this.saveErrorMessage(err));
      },
    });
  }

  finalizeTemplate(): void {
    const template = this.template();
    if (!template) return;
    this.error.set('');
    this.isFinalizingTemplate.set(true);
    this.templateService.finalizeTemplate(template.id).subscribe({
      next: (updated) => {
        this.isFinalizingTemplate.set(false);
        this.template.set(updated);
        this.refreshRequested.emit();
        this.autoGenerateExamPdfIfReady();
      },
      error: () => {
        this.isFinalizingTemplate.set(false);
        this.error.set('Failed to prepare the template for scanning. Please try again.');
      },
    });
  }

  generateExamPdf(): void {
    if (!this.canGenerateExamPdf()) return;
    this.error.set('');
    this.isGeneratingExamPdf.set(true);
    this.examService.generateExamPdf(this.examId).subscribe({
      next: (exam) => {
        this.isGeneratingExamPdf.set(false);
        this.examGeneratedPdfPath.set(exam.generated_pdf_path ?? null);
        this.refreshRequested.emit();
      },
      error: () => {
        this.isGeneratingExamPdf.set(false);
        this.error.set('Failed to generate the exam PDF.');
      },
    });
  }

  // The template only ever needs finalizing (OMR registration) once -- a
  // later exam reusing the same template skips straight to generating its
  // own PDF, so this has to check independently rather than only running
  // from finalizeTemplate()'s success handler.
  private autoFinalizeTemplateIfReady(): void {
    // Preserve the existing automatic workflow once all keys are complete,
    // while still allowing an explicit early registration for scan-based key
    // extraction through canFinalizeTemplate().
    if (
      this.completedVersionCount() === this.versionSlots().length &&
      this.canFinalizeTemplate()
    ) {
      this.finalizeTemplate();
      return;
    }
    this.autoGenerateExamPdfIfReady();
  }

  private autoGenerateExamPdfIfReady(): void {
    if (!this.canGenerateExamPdf()) return;
    this.generateExamPdf();
  }

  private buildAnswerKey(): Record<string, AnswerKeyItem> {
    return AnswerKey.buildAnswerKeyPayload(this.visibleQuestions());
  }

  private defaultPartialWeights(choices: string[], correctChoices: string[]): Record<string, number> {
    const weightedChoices = correctChoices.length > 0 ? correctChoices : choices;
    const weight = correctChoices.length > 0 ? 1 / correctChoices.length : 0;
    return Object.fromEntries(weightedChoices.map((choice) => [choice, weight]));
  }

  private saveErrorMessage(
    err: { status?: number; error?: { error?: { message?: string } } } | null,
  ): string {
    if (err?.status === 403) return 'You can only define an answer key for an exam you created.';
    if (err?.status === 400) {
      return err.error?.error?.message ?? 'The answer key is invalid. Please review it and try again.';
    }
    return 'Failed to save the answer key. Please try again.';
  }

  versionLabel(key: ExamAnswerKeyResponse): string {
    return key.exam_version ? `Version ${key.exam_version}` : 'Answer key';
  }
}
