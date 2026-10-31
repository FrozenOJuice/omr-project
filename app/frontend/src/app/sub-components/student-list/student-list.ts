import { ChangeDetectorRef, Component, EventEmitter, inject, Input, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Course, Student, studentFullName } from '../../models/course.model';
import { CanvasRosterSync, canvasRosterSkipSummary } from '../../models/canvas.model';
import { CanvasService } from '../../services/canvas.service';
import { CourseService } from '../../services/course.service';
import { NotificationService } from '../../services/notification.service';
import { extractApiErrorMessage } from '../../utils/api-error';

type SortField = 'name' | 'studentNumber';
type SortDir   = 'asc' | 'desc';

@Component({
  selector: 'app-student-list',
  imports: [FormsModule],
  templateUrl: './student-list.html',
  styleUrl: './student-list.css',
})
export class StudentList {
  private courseService = inject(CourseService);
  private canvasService = inject(CanvasService);
  private notifications = inject(NotificationService);
  private cdr = inject(ChangeDetectorRef);

  @Input() course!: Course;
  @Input() embedded = false;
  @Input() isOwner = false;
  @Output() close = new EventEmitter<void>();
  @Output() openAddStudents = new EventEmitter<void>();
  @Output() studentRemoved = new EventEmitter<Student>();
  @Output() studentPromoted = new EventEmitter<Student>();
  @Output() rosterChanged = new EventEmitter<CanvasRosterSync | null>();

  searchQuery = '';
  sortField: SortField = 'name';
  sortDir: SortDir = 'asc';
  pendingRemoval: Student | null = null;
  removingStudentId: string | null = null;
  removeError = '';
  pendingPromotion: Student | null = null;
  promotingStudentId: string | null = null;
  promoteError = '';
  syncingRoster = false;
  invitingStudentId: string | null = null;
  invitingAll = false;
  confirmingInviteAll = false;

  fullName = studentFullName;

  get pendingInvitationCount(): number {
    return this.course.canManageCanvas
      ? this.course.studentList.filter(student =>
          student.active && student.accountStatus === 'pending' && !student.invitedAt
        ).length
      : 0;
  }

  get filteredStudents(): Student[] {
    const q = this.searchQuery.trim().toLowerCase();
    const list = q
      ? this.course.studentList.filter(s =>
          studentFullName(s).toLowerCase().includes(q)
          || s.email.toLowerCase().includes(q)
          || (s.studentNumber ?? '').includes(q)
          || this.accountStatusLabel(s).toLowerCase().includes(q)
        )
      : [...this.course.studentList];

    return list.sort((a, b) => {
      const cmp = this.sortValue(a).localeCompare(this.sortValue(b));
      return this.sortDir === 'asc' ? cmp : -cmp;
    });
  }

  setSort(field: SortField): void {
    if (this.sortField === field) {
      this.sortDir = this.sortDir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sortField = field;
      this.sortDir = 'asc';
    }
  }

  requestRemoveStudent(student: Student): void {
    if (student.source === 'canvas') return;
    this.pendingRemoval = student;
    this.removeError = '';
  }

  canPromote(student: Student): boolean {
    return this.isOwner && student.active && student.accountStatus === 'linked' && student.source !== 'canvas';
  }

  requestPromoteStudent(student: Student): void {
    if (!this.canPromote(student)) return;
    this.pendingPromotion = student;
    this.promoteError = '';
  }

  accountStatusLabel(student: Student): string {
    if (!student.active) return 'Removed from Canvas';
    if (student.accountStatus === 'linked') return 'Linked account';
    if (this.course.source !== 'canvas') return 'Pending account';
    return student.invitedAt ? 'Invitation sent' : 'Not invited';
  }

  syncRoster(): void {
    if (this.syncingRoster) return;
    this.syncingRoster = true;
    this.canvasService.syncRoster(this.course.id).subscribe({
      next: result => {
        this.syncingRoster = false;
        this.notifications.showToast('Canvas roster synced', this.syncSummary(result));
        this.rosterChanged.emit(result);
        this.cdr.markForCheck();
      },
      error: error => {
        this.syncingRoster = false;
        this.notifications.showToast(
          'Canvas roster sync failed',
          extractApiErrorMessage(error, 'The Canvas roster could not be synchronized.'),
          'error',
        );
        this.cdr.markForCheck();
      },
    });
  }

  inviteStudent(student: Student): void {
    if (this.invitingStudentId || !student.active || student.accountStatus !== 'pending' || student.invitedAt) return;
    this.invitingStudentId = student.id;
    this.canvasService.inviteStudent(this.course.id, student.id).subscribe({
      next: result => {
        this.invitingStudentId = null;
        if (result.failed) {
          this.notifications.showToast(
            'Canvas invitation failed',
            `The invitation to ${studentFullName(student)} could not be sent.`,
            'error',
          );
        } else {
          this.notifications.showToast(
            result.sent ? 'Canvas invitation sent' : 'Canvas invitation not needed',
            result.sent
              ? `Invitation sent to ${studentFullName(student)}.`
              : `${studentFullName(student)} no longer needs an invitation.`,
          );
          this.rosterChanged.emit(null);
        }
        this.cdr.markForCheck();
      },
      error: error => {
        this.invitingStudentId = null;
        this.notifications.showToast(
          'Canvas invitation failed',
          extractApiErrorMessage(error, 'The invitation could not be sent.'),
          'error',
        );
        this.cdr.markForCheck();
      },
    });
  }

  requestInviteAll(): void {
    if (this.pendingInvitationCount && !this.invitingAll) {
      this.confirmingInviteAll = true;
    }
  }

  cancelInviteAll(): void {
    if (!this.invitingAll) this.confirmingInviteAll = false;
  }

  inviteAll(): void {
    if (!this.confirmingInviteAll || this.invitingAll) return;
    this.invitingAll = true;
    this.canvasService.invitePendingStudents(this.course.id).subscribe({
      next: result => {
        this.invitingAll = false;
        this.confirmingInviteAll = false;
        this.notifications.showToast(
          result.failed ? 'Some Canvas invitations failed' : 'Canvas invitations sent',
          result.failed
            ? `${result.sent} sent, ${result.failed} failed. Retry the remaining invitations.`
            : `${result.sent} invitation${result.sent === 1 ? '' : 's'} sent.`,
          result.failed ? 'error' : 'info',
        );
        this.rosterChanged.emit(null);
        this.cdr.markForCheck();
      },
      error: error => {
        this.invitingAll = false;
        this.notifications.showToast(
          'Canvas invitations failed',
          extractApiErrorMessage(error, 'The invitations could not be sent.'),
          'error',
        );
        this.cdr.markForCheck();
      },
    });
  }

  cancelRemoveStudent(): void {
    if (this.removingStudentId) return;
    this.pendingRemoval = null;
  }

  confirmRemoveStudent(): void {
    const student = this.pendingRemoval;
    if (!student) return;

    this.removingStudentId = student.id;
    this.removeError = '';
    this.courseService.unenrollStudent(this.course.id, student.id).subscribe({
      next: () => {
        this.studentRemoved.emit(student);
        this.pendingRemoval = null;
        this.removingStudentId = null;
        this.cdr.markForCheck();
      },
      error: () => {
        this.removeError = 'Unable to remove this student. Please try again.';
        this.removingStudentId = null;
        this.cdr.markForCheck();
      },
    });
  }

  cancelPromoteStudent(): void {
    if (this.promotingStudentId) return;
    this.pendingPromotion = null;
  }

  confirmPromoteStudent(): void {
    const student = this.pendingPromotion;
    if (!student) return;

    this.promotingStudentId = student.id;
    this.promoteError = '';
    this.courseService.promoteStudent(this.course.id, student.id).subscribe({
      next: () => {
        this.studentPromoted.emit(student);
        this.pendingPromotion = null;
        this.promotingStudentId = null;
        this.cdr.markForCheck();
      },
      error: () => {
        this.promoteError = 'Unable to promote this student. Please try again.';
        this.promotingStudentId = null;
        this.cdr.markForCheck();
      },
    });
  }

  private sortValue(student: Student): string {
    return this.sortField === 'name' ? studentFullName(student) : (student.studentNumber ?? '');
  }

  private syncSummary(result: CanvasRosterSync): string {
    if (!result.added && !result.updated && !result.removed && !result.skipped) {
      return 'Canvas roster is already up to date.';
    }
    const changes = [
      `${result.added} added`,
      `${result.updated} updated`,
      `${result.removed} removed`,
    ];
    if (result.skipped) {
      changes.push(`${result.skipped} skipped (${canvasRosterSkipSummary(result.skip_reasons)})`);
    }
    return `${changes.join(', ')}.`;
  }
}
