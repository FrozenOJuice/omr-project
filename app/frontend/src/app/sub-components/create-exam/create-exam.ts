import { ChangeDetectorRef, Component, EventEmitter, inject, Input, OnChanges, OnInit, Output, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ExamService } from '../../services/exam.service';
import { ExamTemplateService } from '../../services/exam-template.service';
import { ExamTemplateResponse } from '../../models/exam-template.model';
import {
  ApiExam,
  DEFAULT_EXAM_DURATION_MINUTES,
  EXAM_DURATION_PRESETS,
} from '../../models/exam.model';
import { WizardSteps } from '../wizard-steps/wizard-steps';
import { CanvasAssignment } from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';

@Component({
  selector: 'app-create-exam',
  imports: [FormsModule, WizardSteps],
  templateUrl: './create-exam.html',
  styleUrl: './create-exam.css',
})
export class CreateExam implements OnInit, OnChanges {
  private examService = inject(ExamService);
  private templateService = inject(ExamTemplateService);
  private canvasService = inject(CanvasService);
  private cdr = inject(ChangeDetectorRef);

  @Input() courseId!: string;
  // When set, this modal is one step of the exam-creation wizard (course-detail.html):
  // shows the step indicator and labels its submit button "Next" instead of "Create Exam".
  @Input() wizardStep: number | null = null;
  @Input() canvasAssignmentMode = false;
  @Output() close = new EventEmitter<void>();
  @Output() created = new EventEmitter<ApiExam>();
  @Output() manageTemplates = new EventEmitter<void>();

  name = '';
  description = '';
  // Scheduling is optional. When a date is provided, start_time / end_time
  // are derived from the date, start time, and duration for the backend.
  date = '';
  startClock = '';
  durationMinutes: number | null = DEFAULT_EXAM_DURATION_MINUTES;
  // Every exam is created against a reusable bubble-sheet template.
  templateId = '';
  canvasAssignmentId: string | null = null;
  isLoading = false;
  error = '';
  canvasAssignmentsError = '';

  readonly durationPresets = EXAM_DURATION_PRESETS;
  readonly templates = signal<ExamTemplateResponse[]>([]);
  readonly templatesLoaded = signal(false);
  readonly canvasAssignments = signal<CanvasAssignment[]>([]);
  readonly canvasAssignmentsLoaded = signal(false);

  ngOnInit(): void {
    this.templateService.listMyTemplates().subscribe({
      next: (templates) => {
        this.templates.set(templates);
        this.templatesLoaded.set(true);
      },
      error: () => this.templatesLoaded.set(true),
    });
    if (this.canvasAssignmentMode) {
      this.canvasService.getAssignments(this.courseId).subscribe({
        next: assignments => {
          this.canvasAssignments.set(assignments);
          this.canvasAssignmentsLoaded.set(true);
        },
        error: () => {
          this.canvasAssignmentsError = 'Canvas assignments could not be loaded. You can link one later.';
          this.canvasAssignmentsLoaded.set(true);
        },
      });
    }
  }

  private get startDate(): Date | null {
    if (!this.date || !this.startClock) return null;
    const d = new Date(`${this.date}T${this.startClock}`);
    return isNaN(d.getTime()) ? null : d;
  }

  private get endDate(): Date | null {
    const start = this.startDate;
    if (!start || !this.durationMinutes || this.durationMinutes <= 0) return null;
    return new Date(start.getTime() + this.durationMinutes * 60000);
  }

  private get scheduleValid(): boolean {
    if (!this.date && !this.startClock) return true;
    return this.startDate !== null && this.endDate !== null;
  }

  get canSubmit(): boolean {
    return (
      this.name.trim().length > 0 &&
      this.templateId.length > 0 &&
      this.scheduleValid &&
      (!this.canvasAssignmentMode || this.canvasAssignmentId !== null)
    );
  }

  get endsAt(): string {
    const end = this.endDate;
    if (!end) return '';
    return end.toLocaleString(undefined, {
      weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
  }

  ngOnChanges(): void {
    this.name = '';
    this.description = '';
    this.date = '';
    this.startClock = '';
    this.durationMinutes = DEFAULT_EXAM_DURATION_MINUTES;
    this.templateId = '';
    this.canvasAssignmentId = null;
    this.error = '';
    this.canvasAssignmentsError = '';
    this.isLoading = false;
  }

  goToTemplates(): void {
    this.close.emit();
    this.manageTemplates.emit();
  }

  selectCanvasAssignment(assignmentId: string | null): void {
    this.canvasAssignmentId = assignmentId;
    const assignment = this.canvasAssignments().find(item => item.id === assignmentId);
    this.name = assignment?.name ?? '';
  }

  setDate(date: string): void {
    this.date = date;
    if (!date) this.startClock = '';
  }

  submit(): void {
    const start = this.startDate;
    const end = this.endDate;
    if (!this.canSubmit) return;
    this.isLoading = true;
    this.error = '';

    this.examService.createExam(
      this.name.trim(),
      this.description.trim() || null,
      start ? this.toLocalDateTime(start) : null,
      end ? this.toLocalDateTime(end) : null,
      'student',
      this.courseId,
      this.templateId,
      this.canvasAssignmentId,
    ).subscribe({
      next: (exam) => {
        this.isLoading = false;
        this.created.emit(exam);
        this.cdr.markForCheck();
      },
      error: () => {
        this.isLoading = false;
        this.error = 'Failed to create exam. Please try again.';
        this.cdr.markForCheck();
      },
    });
  }

  private toLocalDateTime(d: Date): string {
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }
}
