import { ChangeDetectorRef, Component, inject, OnInit } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { AuthService } from '../../services/auth.service';
import { Accounts } from '../../services/accounts';
import { LoadingSpinner } from '../../sub-components/loading-spinner/loading-spinner';
import { ThemeService } from '../../services/theme.service';
import { UserService } from '../../services/user.service';
import { CanvasAccount } from '../../sub-components/canvas-account/canvas-account';
import { CanvasService } from '../../services/canvas.service';
import { CurrentUser, NotificationPreferences } from '../../models/auth.model';
import { InstitutionCode } from '../../models/institution.model';
import { getInstitutionBranding } from '../../models/institution.model';
import { INSTITUTION_OPTIONS } from '../../models/institution.model';
import { AcademicTermManager } from '../../sub-components/academic-term-manager/academic-term-manager';

@Component({
  selector: 'app-account',
  imports: [FormsModule, LoadingSpinner, CanvasAccount, AcademicTermManager],
  templateUrl: './account.html',
  styleUrl: './account.css',
})
export class Account implements OnInit {
  private authService = inject(AuthService);
  private accountsService = inject(Accounts);
  private userService = inject(UserService);
  private canvasService = inject(CanvasService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);
  themeService = inject(ThemeService);

  firstName = '';
  lastName = '';
  email = '';
  role = '';
  status = '';
  studentNumber: string | null = null;
  institution: InstitutionCode = 'ubc';
  readonly institutionOptions = INSTITUTION_OPTIONS;
  isLoading = true;
  loadError = false;
  canvasConfigured = false;
  canvasSettingsUrl: string | null = null;
  passwordChangedAt: string | null = null;

  isLoggingOut = false;

  get fullName(): string {
    return `${this.firstName} ${this.lastName}`.trim();
  }

  get isStudent(): boolean {
    return this.role === 'student';
  }

  get canConnectCanvas(): boolean {
    return this.canvasConfigured && (this.role === 'professor' || this.role === 'admin');
  }

  get canManageTerms(): boolean {
    return this.role === 'professor' || this.role === 'admin';
  }

  ngOnInit() {
    this.accountsService.getMe().subscribe({
      next: (user) => {
        this.firstName = user.first_name;
        this.lastName = user.last_name;
        this.email = user.email;
        this.role = user.role;
        this.status = user.status;
        this.studentNumber = user.student_number;
        this.passwordChangedAt = user.password_changed_at;
        this.applyNotificationPreferences(user);
        this.institution = user.institution ?? 'ubc';
        this.userService.currentUser.set(user);
        if (this.role === 'professor' || this.role === 'admin') {
          this.loadCanvasCapability();
        }
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.isLoading = false;
        this.loadError = true;
        this.cdr.detectChanges();
      },
    });
  }

  private loadCanvasCapability(): void {
    this.canvasService.getCapabilities().subscribe({
      next: capability => {
        this.canvasConfigured = capability.configured;
        this.canvasSettingsUrl = capability.settings_url;
        this.cdr.detectChanges();
      },
      error: () => {
        this.canvasConfigured = false;
        this.canvasSettingsUrl = null;
        this.cdr.detectChanges();
      },
    });
  }

  dismissError() {
    this.loadError = false;
  }

  logoutAll() {
    this.isLoggingOut = true;
    this.authService.logoutAll().subscribe({
      next: () => this.router.navigate(['/login']),
      error: () => this.router.navigate(['/login']),
    });
  }

  isEditingProfile = false;
  isSavingProfile = false;
  profileError = '';
  draftFirstName = '';
  draftLastName = '';
  draftEmail = '';
  draftStudentNumber = '';
  draftInstitution: InstitutionCode = 'ubc';

  get institutionName(): string {
    return getInstitutionBranding(this.institution).name;
  }

  startEditProfile() {
    this.draftFirstName = this.firstName;
    this.draftLastName = this.lastName;
    this.draftEmail = this.email;
    this.draftStudentNumber = this.studentNumber ?? '';
    this.draftInstitution = this.institution;
    this.profileError = '';
    this.isEditingProfile = true;
  }

  cancelEditProfile() {
    this.isEditingProfile = false;
    this.profileError = '';
  }

  saveProfile() {
    this.profileError = '';
    this.isSavingProfile = true;
    this.accountsService.updateMe(
      this.draftFirstName,
      this.draftLastName,
      this.draftEmail,
      this.isStudent ? this.draftStudentNumber : undefined,
      this.draftInstitution,
    ).subscribe({
      next: (user) => {
        this.firstName = user.first_name;
        this.lastName = user.last_name;
        this.email = user.email;
        this.studentNumber = user.student_number;
        this.institution = user.institution;
        this.userService.currentUser.set(user);
        this.isSavingProfile = false;
        this.isEditingProfile = false;
        this.cdr.detectChanges();
      },
      error: (err) => {
        this.isSavingProfile = false;
        if (err instanceof Error) return;
        // Backend error responses are wrapped as {"error": {"message","details",...}}
        // (see app/backend/errors/handler.py's _error_response) -- "details" is
        // the Pydantic validation-error array on a 422, "message" is a plain
        // string on any other AppError-raised 4xx.
        const apiError = err?.error?.error;
        const details = apiError?.details;
        if (Array.isArray(details)) {
          this.profileError = details[0]?.msg?.replace(/^Value error,\s*/i, '') ?? 'Failed to save profile. Please try again.';
        } else {
          this.profileError = apiError?.message ?? 'Failed to save profile. Please try again.';
        }
        this.cdr.detectChanges();
      },
    });
  }

  emailNotifications = true;
  regradeAlerts = true;
  batchJobComplete = true;
  isSavingPreferences = false;
  preferencesError = '';
  private savedNotificationPreferences: NotificationPreferences = {
    email_notifications_enabled: true,
    regrade_alerts_enabled: true,
    batch_job_complete_enabled: true,
  };

  schemes = this.themeService.schemes;

  onSchemeChange(id: string) {
    this.themeService.selectScheme(id);
  }

  saveNotificationPreferences(): void {
    if (this.isSavingPreferences) return;

    const preferences: NotificationPreferences = {
      email_notifications_enabled: this.emailNotifications,
      regrade_alerts_enabled: this.regradeAlerts,
      batch_job_complete_enabled: this.batchJobComplete,
    };
    this.preferencesError = '';
    this.isSavingPreferences = true;

    this.accountsService.updateNotificationPreferences(preferences).subscribe({
      next: (user) => {
        this.applyNotificationPreferences(user);
        this.isSavingPreferences = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.emailNotifications = this.savedNotificationPreferences.email_notifications_enabled;
        this.regradeAlerts = this.savedNotificationPreferences.regrade_alerts_enabled;
        this.batchJobComplete = this.savedNotificationPreferences.batch_job_complete_enabled;
        this.preferencesError = 'Failed to save notification preferences. Please try again.';
        this.isSavingPreferences = false;
        this.cdr.detectChanges();
      },
    });
  }

  get passwordLastChangedLabel(): string {
    if (!this.passwordChangedAt) return 'Last changed date unavailable';

    const changedAt = new Date(this.passwordChangedAt);
    if (Number.isNaN(changedAt.getTime())) return 'Last changed date unavailable';

    const elapsedDays = Math.max(0, Math.floor((Date.now() - changedAt.getTime()) / 86_400_000));
    if (elapsedDays === 0) return 'Last changed today';
    if (elapsedDays === 1) return 'Last changed yesterday';
    if (elapsedDays < 30) return `Last changed ${elapsedDays} days ago`;

    const elapsedMonths = Math.floor(elapsedDays / 30);
    if (elapsedMonths < 12) {
      return `Last changed ${elapsedMonths} month${elapsedMonths === 1 ? '' : 's'} ago`;
    }

    const elapsedYears = Math.floor(elapsedMonths / 12);
    return `Last changed ${elapsedYears} year${elapsedYears === 1 ? '' : 's'} ago`;
  }

  showPasswordModal = false;
  currentPassword = '';
  newPassword = '';
  confirmPassword = '';
  passwordError = '';
  isChangingPassword = false;

  getInitials(): string {
    return `${this.firstName[0] ?? ''}${this.lastName[0] ?? ''}`.toUpperCase();
  }

  changePassword() {
    this.passwordError = '';

    if (!this.currentPassword) {
      this.passwordError = 'Please enter your current password.';
      return;
    }

    if (this.newPassword !== this.confirmPassword) {
      this.passwordError = 'New passwords do not match.';
      return;
    }

    const strengthError = this.validatePasswordStrength(this.newPassword);
    if (strengthError) {
      this.passwordError = strengthError;
      return;
    }

    this.isChangingPassword = true;
    this.accountsService.changePassword(this.currentPassword, this.newPassword).subscribe({
      next: () => {
        this.authService.clearTokens();
        this.userService.clear();
        this.router.navigate(['/login']);
      },
      error: (err) => {
        this.isChangingPassword = false;
        if (err instanceof Error) return; // session expired, interceptor already redirected
        // See saveProfile()'s error handler above for the response shape.
        const apiError = err?.error?.error;
        const details = apiError?.details;
        if (Array.isArray(details)) {
          this.passwordError = details[0]?.msg?.replace(/^Value error,\s*/i, '') ?? 'Failed to change password. Please try again.';
        } else {
          this.passwordError = apiError?.message ?? 'Failed to change password. Please try again.';
        }
        this.cdr.detectChanges();
      },
    });
  }

  private validatePasswordStrength(password: string): string | null {
    if (password.length < 12) return 'Password must be at least 12 characters.';
    if (!/[A-Z]/.test(password)) return 'Password must contain at least one uppercase letter.';
    if (!/[a-z]/.test(password)) return 'Password must contain at least one lowercase letter.';
    if (!/[0-9]/.test(password)) return 'Password must contain at least one number.';
    if (!/[^A-Za-z0-9\s]/.test(password)) return 'Password must contain at least one special character.';
    return null;
  }

  private applyNotificationPreferences(user: CurrentUser): void {
    this.emailNotifications = user.email_notifications_enabled;
    this.regradeAlerts = user.regrade_alerts_enabled;
    this.batchJobComplete = user.batch_job_complete_enabled;
    this.savedNotificationPreferences = {
      email_notifications_enabled: user.email_notifications_enabled,
      regrade_alerts_enabled: user.regrade_alerts_enabled,
      batch_job_complete_enabled: user.batch_job_complete_enabled,
    };
  }
}
