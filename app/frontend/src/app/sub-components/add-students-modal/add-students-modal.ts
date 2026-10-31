import { ChangeDetectorRef, Component, EventEmitter, inject, Input, OnDestroy, OnInit, Output } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Course, Student, studentFullName } from '../../models/course.model';
import { CourseService, CsvUploadResult, InviteResendResult } from '../../services/course.service';

type Tab = 'manual' | 'link' | 'csv';

@Component({
  selector: 'app-add-students-modal',
  imports: [FormsModule],
  templateUrl: './add-students-modal.html',
  styleUrl: './add-students-modal.css',
})
export class AddStudentsModal implements OnInit, OnDestroy {
  private courseService = inject(CourseService);
  private cdr = inject(ChangeDetectorRef);
  private copyFeedbackTimer: ReturnType<typeof setTimeout> | null = null;
  private expiryRefreshTimer: ReturnType<typeof setInterval> | null = null;
  private currentTime = Date.now();

  @Input() course!: Course;
  @Output() close = new EventEmitter<void>();
  @Output() studentsAdded = new EventEmitter<number>();

  activeTab: Tab = 'manual';
  firstName = '';
  lastName = '';
  email = '';
  studentNumber = '';
  isAdding = false;
  addError = '';
  addedStudent: Student | null = null;

  inviteLink = '';
  inviteLinkExpiresAt: string | null = null;
  copied = false;
  isRegenerating = false;
  regenerateError = '';

  csvFile: File | null = null;
  isUploading = false;
  uploadResult: CsvUploadResult | null = null;
  uploadError = '';

  isResending = false;
  resendResult: InviteResendResult | null = null;
  resendError = '';

  ngOnInit(): void {
    this.inviteLink = this.course.inviteLink ?? '';
    this.inviteLinkExpiresAt = this.course.inviteLinkExpiresAt ?? null;
    this.expiryRefreshTimer = setInterval(() => {
      this.currentTime = Date.now();
      this.cdr.markForCheck();
    }, 60_000);
  }

  ngOnDestroy(): void {
    if (this.copyFeedbackTimer) clearTimeout(this.copyFeedbackTimer);
    if (this.expiryRefreshTimer) clearInterval(this.expiryRefreshTimer);
  }

  selectTab(tab: Tab): void {
    this.activeTab = tab;
  }

  get joinUrl(): string {
    return this.inviteLink ? `${window.location.origin}/join/${this.inviteLink}` : '';
  }

  get inviteExpired(): boolean {
    const expiry = this.inviteExpiry;
    return expiry ? expiry.getTime() <= this.currentTime : false;
  }

  get canCopyInviteLink(): boolean {
    return Boolean(this.joinUrl) && !this.inviteExpired;
  }

  get inviteExpiryStatus(): string {
    const expiry = this.inviteExpiry;
    if (!expiry) return 'Expiration unavailable';
    if (this.inviteExpired) return 'Invite link expired';

    const remainingMinutes = Math.max(
      1,
      Math.ceil((expiry.getTime() - this.currentTime) / 60_000),
    );
    if (remainingMinutes >= 24 * 60) {
      const days = Math.ceil(remainingMinutes / (24 * 60));
      return `Expires in ${days} day${days === 1 ? '' : 's'}`;
    }
    if (remainingMinutes >= 60) {
      const hours = Math.ceil(remainingMinutes / 60);
      return `Expires in ${hours} hour${hours === 1 ? '' : 's'}`;
    }
    return `Expires in ${remainingMinutes} minute${remainingMinutes === 1 ? '' : 's'}`;
  }

  get inviteExpiryDetail(): string {
    const expiry = this.inviteExpiry;
    if (!expiry) {
      return 'Regenerate the link to create a new expiration window.';
    }
    const formatted = new Intl.DateTimeFormat(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZoneName: 'short',
    }).format(expiry);
    return `${this.inviteExpired ? 'Expired' : 'Valid until'} ${formatted}`;
  }

  copyLink(): void {
    if (!this.canCopyInviteLink) return;
    navigator.clipboard.writeText(this.joinUrl).then(() => {
      this.copied = true;
      this.cdr.detectChanges();
      if (this.copyFeedbackTimer) clearTimeout(this.copyFeedbackTimer);
      this.copyFeedbackTimer = setTimeout(() => {
        this.copied = false;
        this.copyFeedbackTimer = null;
        this.cdr.detectChanges();
      }, 2000);
    });
  }

  regenerateLink(): void {
    this.isRegenerating = true;
    this.regenerateError = '';
    this.courseService.regenerateInviteLink(this.course.id).subscribe({
      next: (res) => {
        this.inviteLink = res.invite_link;
        this.inviteLinkExpiresAt = res.invite_link_expires_at;
        this.course.inviteLink = res.invite_link;
        this.course.inviteLinkExpiresAt = res.invite_link_expires_at;
        this.currentTime = Date.now();
        this.isRegenerating = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.regenerateError = 'Failed to regenerate link. Please try again.';
        this.isRegenerating = false;
        this.cdr.markForCheck();
      },
    });
  }

  onFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    this.csvFile = input.files?.[0] ?? null;
    this.uploadResult = null;
    this.uploadError = '';
  }

  uploadCsv(): void {
    if (!this.csvFile) return;
    this.isUploading = true;
    this.uploadResult = null;
    this.uploadError = '';
    this.courseService.uploadStudentsCsv(this.course.id, this.csvFile).subscribe({
      next: (result) => {
        this.uploadResult = result;
        this.isUploading = false;
        if (result.enrolled > 0) {
          this.studentsAdded.emit(result.enrolled);
        }
        this.cdr.markForCheck();
      },
      error: () => {
        this.uploadError = 'Upload failed. Please check your file and try again.';
        this.isUploading = false;
        this.cdr.markForCheck();
      },
    });
  }

  clearFile(): void {
    this.csvFile = null;
    this.uploadResult = null;
    this.uploadError = '';
  }

  resendInvites(): void {
    this.isResending = true;
    this.resendResult = null;
    this.resendError = '';
    this.courseService.resendInvites(this.course.id).subscribe({
      next: (result) => {
        this.resendResult = result;
        this.isResending = false;
        this.cdr.markForCheck();
      },
      error: () => {
        this.resendError = 'Unable to resend invitations. Please try again.';
        this.isResending = false;
        this.cdr.markForCheck();
      },
    });
  }

  addStudent(): void {
    const firstName = this.firstName.trim();
    const lastName = this.lastName.trim();
    const email = this.email.trim().toLowerCase();
    const studentNumber = this.studentNumber.trim();

    this.addError = '';
    this.addedStudent = null;

    if (!firstName || !lastName || !email || !studentNumber) {
      this.addError = 'Please fill in all student fields.';
      return;
    }

    if (!/^\d{8}$/.test(studentNumber)) {
      this.addError = 'Student number must be exactly 8 digits.';
      return;
    }

    this.isAdding = true;
    this.courseService.addStudent(this.course.id, {
      first_name: firstName,
      last_name: lastName,
      email,
      student_number: studentNumber,
    }).subscribe({
      next: (student) => {
        this.addedStudent = student;
        this.isAdding = false;
        this.resetManualForm();
        this.studentsAdded.emit(1);
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.addError = this.formatAddError(err);
        this.isAdding = false;
        this.cdr.markForCheck();
      },
    });
  }

  clearManualResult(): void {
    this.addError = '';
    this.addedStudent = null;
  }

  addedStudentName(): string {
    return this.addedStudent ? studentFullName(this.addedStudent) : '';
  }

  addedStudentStatus(): string {
    if (!this.addedStudent) return '';
    return this.addedStudent.accountStatus === 'linked'
      ? 'Existing account linked and enrolled'
      : 'Pending account activation';
  }

  private get inviteExpiry(): Date | null {
    if (!this.inviteLinkExpiresAt) return null;
    const timestamp = Date.parse(this.inviteLinkExpiresAt);
    return Number.isNaN(timestamp) ? null : new Date(timestamp);
  }

  private resetManualForm(): void {
    this.firstName = '';
    this.lastName = '';
    this.email = '';
    this.studentNumber = '';
  }

  private formatAddError(err: any): string {
    const error = err?.error?.error;
    if (error?.code === 'student_already_enrolled') {
      return 'This student is already on the course roster.';
    }
    if (error?.code === 'user_not_student') {
      return 'An account with that email exists, but it is not a student account.';
    }
    if (error?.code === 'student_number_mismatch') {
      return 'The student number does not match the account for that email.';
    }
    if (error?.message) {
      return error.message;
    }
    return 'Unable to add this student. Please check the details and try again.';
  }
}
