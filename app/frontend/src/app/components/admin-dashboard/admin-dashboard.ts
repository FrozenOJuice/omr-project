import { ChangeDetectorRef, Component, AfterViewInit, OnDestroy, OnInit, ViewChild, ElementRef, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Chart, registerables, type ChartConfiguration } from 'chart.js';
import { AdminUserTable } from '../../sub-components/admin-user-table/admin-user-table';
import { AdminSessionsTable } from '../../sub-components/admin-sessions-table/admin-sessions-table';
import { catchError, finalize, forkJoin, Observable, of } from 'rxjs';
import { AdminService } from '../../services/admin.service';
import {
  AdminSummary,
  AdminUser,
  ActiveSession,
  ApiAccountStatus,
  ApiAdminUser,
  UserRole,
  apiAdminUserToAdminUser,
  userRoleToApiRole,
} from '../../models/admin.model';
import { extractApiErrorMessage } from '../../utils/api-error';
import { AcademicTermManager } from '../../sub-components/academic-term-manager/academic-term-manager';
import { SiteBrandingService } from '../../services/site-branding.service';
import {
  MAX_SITE_LOGO_BYTES,
  SITE_LOGO_ACCEPT,
  SITE_LOGO_TYPES,
} from '../../models/site-branding.model';

Chart.register(...registerables);

function cssVar(name: string): string {
  return getComputedStyle(document.body).getPropertyValue(name).trim();
}

@Component({
  selector: 'app-admin-dashboard',
  imports: [AdminUserTable, AdminSessionsTable, FormsModule, AcademicTermManager],
  templateUrl: './admin-dashboard.html',
  styleUrl: './admin-dashboard.css',
})
export class AdminDashboard implements OnInit, AfterViewInit, OnDestroy {
  @ViewChild('loginsChart') loginsCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('roleDistChart') roleDistCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('sessionActivityChart') sessionActivityCanvas!: ElementRef<HTMLCanvasElement>;
  @ViewChild('siteLogoInput') siteLogoInput?: ElementRef<HTMLInputElement>;

  private adminService = inject(AdminService);
  private siteBrandingService = inject(SiteBrandingService);
  private cdr = inject(ChangeDetectorRef);

  private loginsChart?: Chart<'line'>;
  private roleDistChart?: Chart<'bar'>;
  private sessionActivityChart?: Chart<'doughnut'>;
  private darkModeObserver?: MutationObserver;

  users: AdminUser[] = [];
  sessions: ActiveSession[] = [];
  isLoading = true;
  // Distinct from isLoading: isLoading also flips true/false on every
  // filter-driven reload, which must not unmount the table (see
  // admin-dashboard.html) since that would destroy the search input the
  // user is actively typing in and drop its focus.
  hasLoadedOnce = false;
  isSavingUser = false;
  errorMessage = '';
  userFormError = '';
  userNotice = '';
  busyUserId: string | null = null;
  siteBranding = this.siteBrandingService.branding;
  siteLogoAccept = SITE_LOGO_ACCEPT;
  selectedLogoFile: File | null = null;
  isSavingLogo = false;
  logoError = '';
  logoNotice = '';
  summary: AdminSummary | null = null;
  tableTotal = 0;
  tableLimit = 25;
  tableOffset = 0;
  userSearch = '';
  roleFilter: UserRole | '' = '';
  statusFilter: ApiAccountStatus | '' = '';
  isUserModalOpen = false;
  editingUser: AdminUser | null = null;
  userForm = {
    firstName: '',
    lastName: '',
    email: '',
    password: '',
    role: 'Student' as UserRole,
    status: 'active' as ApiAccountStatus,
    studentNumber: '',
  };

  get totalUsers()      { return this.summary?.total_users ?? this.users.length; }
  get totalAdmins()     { return this.summary?.admins ?? 0; }
  get totalProfessors() { return this.summary?.professors ?? 0; }
  get totalStudents()   { return this.summary?.students ?? 0; }
  get activeSessionsCount() { return this.summary?.active_sessions ?? 0; }
  get offlineUsersCount() { return Math.max(this.totalUsers - this.activeSessionsCount, 0); }

  ngOnInit(): void {
    this.loadDashboard();
  }

  onLogoFileSelected(event: Event): void {
    const input = event.target as HTMLInputElement;
    const file = input.files?.[0] ?? null;
    this.selectedLogoFile = null;
    this.logoError = '';
    this.logoNotice = '';

    if (!file) return;

    if (!(SITE_LOGO_TYPES as readonly string[]).includes(file.type)) {
      this.logoError = 'Choose a PNG, JPEG, or WebP image.';
      input.value = '';
      return;
    }

    if (file.size > MAX_SITE_LOGO_BYTES) {
      this.logoError = 'Logo images must be 2 MB or smaller.';
      input.value = '';
      return;
    }

    this.selectedLogoFile = file;
  }

  uploadSiteLogo(): void {
    if (!this.selectedLogoFile || this.isSavingLogo) return;
    this.runLogoRequest(
      this.siteBrandingService.uploadLogo(this.selectedLogoFile),
      'Logo updated',
      'Unable to update the site logo.',
    );
  }

  resetSiteLogo(): void {
    if (this.isSavingLogo) return;

    this.runLogoRequest(
      this.siteBrandingService.resetLogo(),
      'Default restored',
      'Unable to restore the default site logo.',
    );
  }

  private runLogoRequest(
    request: Observable<unknown>,
    successMessage: string,
    failureMessage: string,
  ): void {
    this.isSavingLogo = true;
    this.logoError = '';
    this.logoNotice = '';
    request.pipe(
      finalize(() => {
        this.isSavingLogo = false;
        this.cdr.detectChanges();
      }),
    ).subscribe({
      next: () => {
        this.selectedLogoFile = null;
        if (this.siteLogoInput) this.siteLogoInput.nativeElement.value = '';
        this.logoNotice = successMessage;
      },
      error: (err) => {
        this.logoError = extractApiErrorMessage(err, failureMessage);
      },
    });
  }

  ngAfterViewInit(): void {
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    this.loginsChart = this.createLoginsChart();
    this.roleDistChart = this.createRoleDistChart();
    this.sessionActivityChart = this.createSessionActivityChart();

    this.darkModeObserver = new MutationObserver(() => setTimeout(() => this.refreshCharts()));
    this.darkModeObserver.observe(document.body, { attributes: true, attributeFilter: ['class'] });
  }

  ngOnDestroy(): void {
    this.darkModeObserver?.disconnect();
    this.destroyCharts();
  }

  loadDashboard(): void {
    this.isLoading = true;
    this.errorMessage = '';

    forkJoin({
      summary: this.adminService.getSummary().pipe(catchError(() => of(null))),
      users: this.adminService.listUsers({
        limit: this.tableLimit,
        offset: this.tableOffset,
        search: this.userSearch || undefined,
        role: this.roleFilter ? userRoleToApiRole(this.roleFilter) : undefined,
        status: this.statusFilter || undefined,
      }),
    }).subscribe({
      next: ({ summary, users }) => {
        this.summary = summary ?? this.buildSummaryFromUsers(users.items);
        this.users = users.items.map(apiAdminUserToAdminUser);
        this.tableTotal = users.total;
        this.tableLimit = users.limit;
        this.tableOffset = users.offset;
        this.sessions = [];
        this.isLoading = false;
        this.hasLoadedOnce = true;
        this.cdr.detectChanges();
        this.updateRoleDistChart();
        this.updateSessionActivityChart();
      },
      error: () => {
        this.isLoading = false;
        this.hasLoadedOnce = true;
        this.errorMessage = 'Unable to load admin dashboard data.';
        this.cdr.detectChanges();
      },
    });
  }

  onUserFiltersChange(filters: {
    search: string;
    role: UserRole | '';
    status: ApiAccountStatus | '';
  }): void {
    this.userSearch = filters.search;
    this.roleFilter = filters.role;
    this.statusFilter = filters.status;
    this.tableOffset = 0;
    this.loadDashboard();
  }

  onUserPageChange(offset: number): void {
    this.tableOffset = offset;
    this.loadDashboard();
  }

  openCreateUser(): void {
    this.editingUser = null;
    this.userFormError = '';
    this.userNotice = '';
    this.userForm = {
      firstName: '',
      lastName: '',
      email: '',
      password: '',
      role: 'Student',
      status: 'active',
      studentNumber: '',
    };
    this.isUserModalOpen = true;
  }

  closeUserModal(): void {
    if (this.isSavingUser) {
      return;
    }

    this.isUserModalOpen = false;
    this.editingUser = null;
    this.userFormError = '';
  }

  submitUserForm(): void {
    const firstName = this.userForm.firstName.trim();
    const lastName = this.userForm.lastName.trim();
    const email = this.userForm.email.trim().toLowerCase();
    const password = this.userForm.password;
    const studentNumber = this.userForm.studentNumber.trim();

    if (!firstName || !lastName || !email) {
      this.userFormError = 'First name, last name, and email are required.';
      return;
    }

    if (!this.editingUser && !password) {
      this.userFormError = 'Password is required for new users.';
      return;
    }

    if (!this.editingUser && this.userForm.role === 'Student' && !studentNumber) {
      this.userFormError = 'Student number is required for student accounts.';
      return;
    }

    this.isSavingUser = true;
    this.userFormError = '';

    const request = this.editingUser
      ? this.adminService.updateUser(this.editingUser.id, { first_name: firstName, last_name: lastName, email })
      : this.adminService.createUser({
          first_name: firstName,
          last_name: lastName,
          email,
          password,
          role: userRoleToApiRole(this.userForm.role),
          status: this.userForm.status,
          student_number: this.userForm.role === 'Student' ? studentNumber : null,
        });

    const createdStatus = this.userForm.status;

    request.subscribe({
      next: () => {
        const wasCreate = !this.editingUser;
        this.isSavingUser = false;
        this.isUserModalOpen = false;
        this.editingUser = null;
        // Delivery is asynchronous and best-effort, so we can only say the
        // email was queued, not that it arrived. Disabled accounts get no
        // setup email (the link would be unusable), so don't claim one.
        if (!wasCreate) {
          this.userNotice = '';
        } else if (createdStatus === 'active') {
          this.userNotice = `Account created. A set-password email has been queued for ${email}.`;
        } else {
          this.userNotice = 'Account created.';
        }
        this.loadDashboard();
      },
      error: (err) => {
        this.isSavingUser = false;
        this.userFormError = extractApiErrorMessage(
          err,
          this.editingUser ? 'Unable to update user.' : 'Unable to create user.',
        );
        this.cdr.detectChanges();
      },
    });
  }

  private buildSummaryFromUsers(users: ApiAdminUser[]): AdminSummary {
    return {
      total_users: users.length,
      active_users: users.filter(user => user.status === 'active').length,
      disabled_users: users.filter(user => user.status === 'disabled').length,
      admins: users.filter(user => user.role === 'admin').length,
      professors: users.filter(user => user.role === 'professor').length,
      students: users.filter(user => user.role === 'student').length,
      active_sessions: 0,
    };
  }

  onSaveUser(event: {
    userId: string;
    firstName: string;
    lastName: string;
    email: string;
    role: UserRole;
    status: ApiAccountStatus;
    studentNumber: string | null;
  }): void {
    // Mirror onDeleteUser: only one user mutation is in flight at a time, so a
    // save on another row can't leave the busy row's controls out of sync.
    if (this.busyUserId) {
      return;
    }

    const user = this.users.find(u => u.id === event.userId);

    if (!user) {
      return;
    }

    if (!event.firstName || !event.lastName || !event.email) {
      this.errorMessage = 'First name, last name, and email are required.';
      this.cdr.detectChanges();
      return;
    }

    const requests = [];
    const studentNumberChanged = event.role === 'Student'
      && event.studentNumber !== user.studentNumber;

    if (
      event.firstName !== user.firstName ||
      event.lastName !== user.lastName ||
      event.email.toLowerCase() !== user.email.toLowerCase() ||
      studentNumberChanged
    ) {
      requests.push(
        this.adminService.updateUser(event.userId, {
          first_name: event.firstName,
          last_name: event.lastName,
          email: event.email,
          student_number: event.studentNumber,
        }),
      );
    }

    if (event.role !== user.role) {
      requests.push(
        this.adminService.updateUserRole(event.userId, userRoleToApiRole(event.role)),
      );
    }

    if (event.status !== user.status) {
      requests.push(this.adminService.updateUserStatus(event.userId, event.status));
    }

    if (requests.length === 0) {
      return;
    }

    this.busyUserId = user.id;
    this.userNotice = '';
    forkJoin(requests).subscribe({
      next: () => {
        this.busyUserId = null;
        this.userNotice = `Changes saved for ${user.fullName}.`;
        this.loadDashboard();
      },
      error: (err) => {
        this.busyUserId = null;
        this.errorMessage = extractApiErrorMessage(err, 'Unable to save user changes.');
        this.cdr.detectChanges();
      },
    });
  }

  onForceLogout(userId: string): void {
    this.adminService.logoutUser(userId).subscribe({
      next: () => this.loadDashboard(),
      error: () => {
        this.errorMessage = 'Unable to force logout user.';
        this.cdr.detectChanges();
      },
    });
  }

  onResendSetupEmail(user: AdminUser): void {
    this.adminService.resendSetupEmail(user.id).subscribe({
      next: () => {
        this.userNotice = `A set-password email has been queued for ${user.email}.`;
        this.cdr.detectChanges();
      },
      error: () => {
        this.errorMessage = 'Unable to resend the setup email.';
        this.cdr.detectChanges();
      },
    });
  }

  onDeleteUser(user: AdminUser): void {
    if (this.busyUserId) return;
    this.busyUserId = user.id;
    this.userNotice = '';
    this.adminService.deleteUser(user.id).subscribe({
      next: () => {
        this.busyUserId = null;
        if (this.users.length === 1 && this.tableOffset > 0) {
          this.tableOffset = Math.max(this.tableOffset - this.tableLimit, 0);
        }

        this.userNotice = `${user.fullName} was deleted.`;
        this.loadDashboard();
      },
      error: () => {
        this.busyUserId = null;
        this.errorMessage = 'Unable to delete user. Users with academic records cannot be deleted.';
        this.cdr.detectChanges();
      },
    });
  }

  private createLoginsChart(): Chart<'line'> {
    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
        datasets: [{
          data: [0, 0, 0, 0, 0, 0, 0],
          borderColor: cssVar('--highlight2'),
          backgroundColor: `${cssVar('--highlight2')}33`,
          borderWidth: 2,
          pointRadius: 3,
          fill: true,
          tension: 0.3,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar('--color-text') },
          },
          y: {
            grid: { color: `${cssVar('--color-text')}22` },
            border: { display: false },
            ticks: { color: cssVar('--color-text') },
          }
        }
      }
    };
    return new Chart(this.loginsCanvas.nativeElement, config);
  }

  private createRoleDistChart(): Chart<'bar'> {
    const config: ChartConfiguration<'bar'> = {
      type: 'bar',
      data: {
        labels: ['Admin', 'Professor', 'Student'],
        datasets: [{
          data: [this.totalAdmins, this.totalProfessors, this.totalStudents],
          backgroundColor: [
            cssVar('--highlight2'),
            cssVar('--highlight3'),
            cssVar('--primary-darkened'),
          ],
          borderRadius: 4,
          borderWidth: 0,
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: { legend: { display: false }, tooltip: { enabled: true } },
        scales: {
          x: {
            grid: { display: false },
            border: { display: false },
            ticks: { color: cssVar('--color-text') },
          },
          y: { display: false }
        }
      }
    };
    return new Chart(this.roleDistCanvas.nativeElement, config);
  }

  private createSessionActivityChart(): Chart<'doughnut'> {
    const config: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        labels: ['Active', 'Inactive'],
        datasets: [{
          data: [this.activeSessionsCount, this.offlineUsersCount],
          backgroundColor: [cssVar('--highlight2'), cssVar('--primary-darkened')],
          borderWidth: 0,
        }]
      },
      options: {
        cutout: '75%',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: { enabled: false },
        }
      }
    };
    return new Chart(this.sessionActivityCanvas.nativeElement, config);
  }

  private updateRoleDistChart(): void {
    if (!this.roleDistChart) {
      return;
    }

    this.roleDistChart.data.datasets[0].data = [
      this.totalAdmins,
      this.totalProfessors,
      this.totalStudents,
    ];

    this.roleDistChart.update();
  }

  private updateSessionActivityChart(): void {
    if (!this.sessionActivityChart) {
      return;
    }

    this.sessionActivityChart.data.datasets[0].data = [
      this.activeSessionsCount,
      this.offlineUsersCount,
    ];

    this.sessionActivityChart.update();
  }

  private refreshCharts(): void {
    this.destroyCharts();
    this.loginsChart = this.createLoginsChart();
    this.roleDistChart = this.createRoleDistChart();
    this.sessionActivityChart = this.createSessionActivityChart();
  }

  private destroyCharts(): void {
    this.loginsChart?.destroy();
    this.roleDistChart?.destroy();
    this.sessionActivityChart?.destroy();

    this.loginsChart = undefined;
    this.roleDistChart = undefined;
    this.sessionActivityChart = undefined;
  }
}
