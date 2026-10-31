import { Component, EventEmitter, Input, OnChanges, Output, SimpleChanges } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { AdminUser, ApiAccountStatus, UserRole } from '../../models/admin.model';

@Component({
  selector: 'app-admin-user-row',
  imports: [FormsModule],
  templateUrl: './admin-user-row.html',
  styleUrl: './admin-user-row.css',
})
export class AdminUserRow implements OnChanges {
  @Input() user!: AdminUser;
  @Input() busy = false;
  @Output() saveUser = new EventEmitter<{
    userId: string;
    firstName: string;
    lastName: string;
    email: string;
    role: UserRole;
    status: ApiAccountStatus;
    studentNumber: string | null;
  }>();
  @Output() forceLogout = new EventEmitter<string>();
  @Output() deleteUser = new EventEmitter<AdminUser>();
  @Output() resendSetupEmail = new EventEmitter<AdminUser>();

  selectedFirstName = '';
  selectedLastName = '';
  selectedEmail = '';
  selectedRole: UserRole = 'Student';
  selectedStatus: ApiAccountStatus = 'active';
  selectedStudentNumber = '';
  pendingAction: 'save' | 'delete' | null = null;
  private readonly allRoles: UserRole[] = ['Admin', 'Professor', 'Student'];
  readonly statuses: ApiAccountStatus[] = ['active', 'disabled'];

  ngOnChanges(changes: SimpleChanges): void {
    if (changes['user'] && this.user) {
      this.selectedFirstName = this.user.firstName;
      this.selectedLastName = this.user.lastName;
      this.selectedEmail = this.user.email;
      this.selectedRole = this.user.role;
      this.selectedStatus = this.user.status;
      this.selectedStudentNumber = this.user.studentNumber ?? '';
    }
  }

  saveChanges(): void {
    if (this.busy || !this.hasChanges) return;
    if (this.roleChanged || this.disablingAccount) {
      this.pendingAction = 'save';
      return;
    }
    this.emitSave();
  }

  requestDelete(): void {
    if (!this.busy) {
      this.pendingAction = 'delete';
    }
  }

  cancelPendingAction(): void {
    if (!this.busy) {
      this.pendingAction = null;
    }
  }

  confirmPendingAction(): void {
    if (this.busy) return;
    const action = this.pendingAction;
    this.pendingAction = null;
    if (action === 'save') {
      this.emitSave();
    } else if (action === 'delete') {
      this.deleteUser.emit(this.user);
    }
  }

  private emitSave(): void {
    this.saveUser.emit({
      userId: this.user.id,
      firstName: this.selectedFirstName.trim(),
      lastName: this.selectedLastName.trim(),
      email: this.selectedEmail.trim().toLowerCase(),
      role: this.selectedRole,
      status: this.selectedStatus,
      studentNumber: this.selectedRole === 'Student' ? this.selectedStudentNumber.trim() || null : null,
    });
  }

  // Student accounts can be promoted to professor. The reverse direction is
  // still hidden because creating a student requires a student number, which
  // the role-only endpoint cannot supply.
  get roles(): UserRole[] {
    return this.user.role === 'Professor'
      ? this.allRoles.filter(role => role !== 'Student')
      : this.allRoles;
  }

  get statusLabel(): string {
    return this.user.status === 'active' ? 'Active' : 'Disabled';
  }

  get sessionLabel(): string {
    return this.user.activeSession ? 'Online' : 'Offline';
  }

  get isStudent(): boolean {
    return this.selectedRole === 'Student';
  }

  get roleChanged(): boolean {
    return this.selectedRole !== this.user.role;
  }

  get disablingAccount(): boolean {
    return this.user.status === 'active' && this.selectedStatus === 'disabled';
  }

  get hasChanges(): boolean {
    return (
      this.selectedFirstName.trim() !== this.user.firstName ||
      this.selectedLastName.trim() !== this.user.lastName ||
      this.selectedEmail.trim().toLowerCase() !== this.user.email.toLowerCase() ||
      this.selectedRole !== this.user.role ||
      this.selectedStatus !== this.user.status ||
      (this.isStudent && this.selectedStudentNumber.trim() !== (this.user.studentNumber ?? ''))
    );
  }

  get createdDate(): string {
    return new Date(this.user.createdAt).toLocaleDateString();
  }
}
