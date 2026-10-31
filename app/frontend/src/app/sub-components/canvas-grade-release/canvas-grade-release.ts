import { DatePipe, KeyValuePipe } from '@angular/common';
import {
  ChangeDetectionStrategy,
  Component,
  EventEmitter,
  Input,
  OnInit,
  Output,
  computed,
  inject,
  signal,
} from '@angular/core';
import { FormsModule } from '@angular/forms';
import { forkJoin, Observable } from 'rxjs';
import { CanvasAssignment, CanvasGradeRelease as GradeRelease } from '../../models/canvas.model';
import { Exam } from '../../models/exam.model';
import { CanvasService } from '../../services/canvas.service';
import { extractApiErrorMessage } from '../../utils/api-error';

@Component({
  selector: 'app-canvas-grade-release',
  imports: [DatePipe, FormsModule, KeyValuePipe],
  templateUrl: './canvas-grade-release.html',
  styleUrl: './canvas-grade-release.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CanvasGradeRelease implements OnInit {
  @Input({ required: true }) courseId = '';
  @Input({ required: true }) exam!: Exam;
  @Output() dismissed = new EventEmitter<void>();
  @Output() assignmentChanged = new EventEmitter<GradeRelease>();

  private canvasService = inject(CanvasService);

  readonly assignments = signal<CanvasAssignment[]>([]);
  readonly status = signal<GradeRelease | null>(null);
  readonly selectedAssignmentId = signal<string | null>(null);
  readonly editingAssignment = signal(false);
  readonly loading = signal(true);
  readonly saving = signal(false);
  readonly sending = signal(false);
  readonly confirming = signal(false);
  readonly error = signal('');
  readonly success = signal('');

  readonly targetLocked = computed(() => this.status()?.target_locked ?? false);
  readonly selectedAssignment = computed(() =>
    this.assignments().find((assignment) => assignment.id === this.selectedAssignmentId()),
  );

  ngOnInit(): void {
    forkJoin({
      assignments: this.canvasService.getAssignments(this.courseId),
      status: this.canvasService.getGradeRelease(this.exam.id),
    }).subscribe({
      next: ({ assignments, status }) => {
        this.assignments.set(assignments);
        this.applyStatus(status);
        this.editingAssignment.set(status.assignment_id === null);
        this.loading.set(false);
      },
      error: (error) => {
        this.error.set(extractApiErrorMessage(
          error,
          'Canvas assignment information could not be loaded.',
        ));
        this.loading.set(false);
      },
    });
  }

  canLink(assignment: CanvasAssignment): boolean {
    return (
      assignment.available &&
      (!assignment.linked_exam_id || assignment.linked_exam_id === this.exam.id)
    );
  }

  canReceiveGrades(assignment: CanvasAssignment | undefined): boolean {
    return (
      !!assignment?.available &&
      assignment.points_possible !== null &&
      assignment.points_possible > 0
    );
  }

  editAssignment(): void {
    if (!this.targetLocked()) {
      this.editingAssignment.set(true);
      this.error.set('');
      this.success.set('');
    }
  }

  cancelAssignmentEdit(): void {
    if (this.saving()) return;
    if (this.status()?.assignment_id === null) {
      this.close();
      return;
    }
    this.selectedAssignmentId.set(this.status()?.assignment_id ?? null);
    this.editingAssignment.set(false);
    this.error.set('');
  }

  saveAssignment(): void {
    if (this.saving() || this.selectedAssignmentId() === this.status()?.assignment_id) return;
    const selectedAssignmentId = this.selectedAssignmentId();
    const request: Observable<GradeRelease> =
      selectedAssignmentId === null
        ? this.canvasService.unlinkExamAssignment(this.exam.id)
        : this.canvasService.linkExamAssignment(this.exam.id, selectedAssignmentId);

    this.saving.set(true);
    this.error.set('');
    request.subscribe({
      next: (status) => {
        this.applyStatus(status);
        this.editingAssignment.set(status.assignment_id === null);
        this.saving.set(false);
        this.success.set(status.assignment_id
          ? 'Canvas assignment linked.'
          : 'Canvas assignment unlinked.');
        this.assignmentChanged.emit(status);
      },
      error: (error) => {
        this.error.set(extractApiErrorMessage(
          error,
          'The Canvas assignment link could not be saved.',
        ));
        this.saving.set(false);
      },
    });
  }

  review(): void {
    const status = this.status();
    if (this.exam.released && status?.assignment_id && status.eligible_count) {
      this.confirming.set(true);
      this.error.set('');
      this.success.set('');
    }
  }

  send(): void {
    if (this.sending() || !this.status()?.assignment_id) return;
    this.sending.set(true);
    this.error.set('');
    this.canvasService.releaseGrades(this.exam.id).subscribe({
      next: (status) => {
        this.applyStatus(status);
        this.sending.set(false);
        this.confirming.set(false);
        const issues = [
          status.last_skipped_count ? `${status.last_skipped_count} skipped` : '',
          status.last_failed_count ? `${status.last_failed_count} failed` : '',
        ].filter(Boolean);
        const summary = `${status.last_sent_count} student result${status.last_sent_count === 1 ? '' : 's'} sent to Canvas${
          issues.length ? `; ${issues.join(', ')}` : ''
        }.`;
        if (status.last_failed_count && !status.last_sent_count) {
          this.error.set(summary);
          this.success.set('');
        } else {
          this.success.set(summary);
        }
      },
      error: (error) => {
        this.error.set(extractApiErrorMessage(
          error,
          'Grades and marked results could not be sent to Canvas.',
        ));
        this.sending.set(false);
      },
    });
  }

  close(): void {
    if (!this.saving() && !this.sending()) this.dismissed.emit();
  }

  skippedLabel(reason: string): string {
    return (
      (
        {
          unresolved_grade: 'Unresolved grades',
          invalid_score: 'Grades with no possible score',
          duplicate_student_grades: 'Duplicate student grades',
          not_linked_to_canvas: 'Students not linked to Canvas',
        } as Record<string, string>
      )[reason] ?? reason
    );
  }

  private applyStatus(status: GradeRelease): void {
    this.status.set(status);
    this.selectedAssignmentId.set(status.assignment_id);
  }
}
