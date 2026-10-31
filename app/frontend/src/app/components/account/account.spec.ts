import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule } from '@angular/forms';
import { provideRouter, Router } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { Account } from './account';
import { AuthService } from '../../services/auth.service';
import { Accounts } from '../../services/accounts';
import { CanvasService } from '../../services/canvas.service';
import { UserService } from '../../services/user.service';
import { CurrentUser } from '../../models/auth.model';
import { AcademicTermService } from '../../services/academic-term.service';

const mockUser: CurrentUser = {
  id: '00000000-0000-0000-0000-000000000001',
  first_name: 'Erin',
  last_name: 'Lee',
  email: 'elee@university.edu',
  role: 'professor',
  status: 'active',
  student_number: null,
  password_changed_at: new Date().toISOString(),
  email_notifications_enabled: true,
  regrade_alerts_enabled: true,
  batch_job_complete_enabled: true,
  institution: 'ubc',
};

describe('Account', () => {
  let component: Account;
  let fixture: ComponentFixture<Account>;
  let navigateSpy: ReturnType<typeof vi.spyOn>;

  const mockAuthService = {
    logoutAll: vi.fn(() => of(undefined as void)),
    clearTokens: vi.fn(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    }),
  };

  const mockAccountsService = {
    getMe: vi.fn(() => of(mockUser)),
    changePassword: vi.fn(() => of(undefined as void)),
    updateMe: vi.fn(() => of(mockUser)),
    updateNotificationPreferences: vi.fn(() => of(mockUser)),
  };

  const mockCanvasService = {
    getCapabilities: vi.fn(() => of({ configured: true, instructor_only: true, settings_url: 'http://localhost:6700/profile/settings' as string | null })),
    getConnection: vi.fn(() => of({
      connected: false,
      user_name: null,
      login_id: null,
      connected_at: null,
      last_verified_at: null,
    })),
    connect: vi.fn(),
    disconnect: vi.fn(() => of(undefined as void)),
    getCourses: vi.fn(() => of([])),
    getRoster: vi.fn(() => of({ course_id: 1, students: [] })),
  };

  const mockAcademicTermService = {
    listTerms: vi.fn(() => of([])),
    createTerm: vi.fn(),
    updateTerm: vi.fn(),
    deleteTerm: vi.fn(),
  };

  beforeEach(async () => {
    mockAuthService.logoutAll.mockReturnValue(of(undefined as void));
    mockAccountsService.getMe.mockReturnValue(of(mockUser));
    mockAccountsService.changePassword.mockReturnValue(of(undefined as void));
    mockAccountsService.updateMe.mockReturnValue(of(mockUser));
    mockAccountsService.updateNotificationPreferences.mockReturnValue(of(mockUser));
    mockCanvasService.getConnection.mockReturnValue(of({
      connected: false,
      user_name: null,
      login_id: null,
      connected_at: null,
      last_verified_at: null,
    }));
    mockCanvasService.getCapabilities.mockReturnValue(of({ configured: true, instructor_only: true, settings_url: 'http://localhost:6700/profile/settings' }));
    mockCanvasService.disconnect.mockReturnValue(of(undefined as void));
    mockCanvasService.getCourses.mockReturnValue(of([]));
    mockCanvasService.getRoster.mockReturnValue(of({ course_id: 1, students: [] }));

    localStorage.removeItem('theme:activeScheme');
    document.body.classList.remove('dark-mode', 'scheme-ugly');

    await TestBed.configureTestingModule({
      imports: [Account, FormsModule],
      providers: [
        provideRouter([]),
        { provide: AuthService, useValue: mockAuthService },
        { provide: Accounts, useValue: mockAccountsService },
        { provide: CanvasService, useValue: mockCanvasService },
        { provide: AcademicTermService, useValue: mockAcademicTermService },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(Account);
    component = fixture.componentInstance;
    navigateSpy = vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture.detectChanges();
    await fixture.whenStable();
  });

  afterEach(() => {
    localStorage.removeItem('theme:activeScheme');
    document.body.classList.remove('dark-mode', 'scheme-ugly');
    vi.restoreAllMocks();
  });

  // Creation

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  // ngOnInit — load user from server

  it('should load user data from the server on init', () => {
    expect(component.firstName).toBe('Erin');
    expect(component.lastName).toBe('Lee');
    expect(component.email).toBe('elee@university.edu');
    expect(component.role).toBe('professor');
    expect(component.status).toBe('active');
    expect(component.institution).toBe('ubc');
  });

  it('shows custom-term management for professors', () => {
    expect(fixture.nativeElement.querySelector('app-academic-term-manager')).not.toBeNull();
  });

  it('places custom-term management directly below the account details card', () => {
    const leftColumn = fixture.nativeElement.querySelector('.left-col');
    const profile = fixture.nativeElement.querySelector('.profile-card');
    const terms = fixture.nativeElement.querySelector('app-academic-term-manager');

    expect(leftColumn.contains(terms)).toBe(true);
    expect(profile.compareDocumentPosition(terms) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('hides custom-term management from students', async () => {
    mockAccountsService.getMe.mockReturnValue(of({
      ...mockUser,
      role: 'student',
      student_number: '12345678',
    }));
    const studentFixture = TestBed.createComponent(Account);
    studentFixture.detectChanges();
    await studentFixture.whenStable();

    expect(studentFixture.nativeElement.querySelector('app-academic-term-manager')).toBeNull();
  });

  it('hides Canvas controls when the integration is not configured', async () => {
    mockCanvasService.getCapabilities.mockReturnValue(of({ configured: false, instructor_only: true, settings_url: null }));
    const unavailableFixture = TestBed.createComponent(Account);
    unavailableFixture.detectChanges();
    await unavailableFixture.whenStable();

    expect(unavailableFixture.nativeElement.querySelector('app-canvas-account')).toBeNull();
  });

  it('should call getMe on init', () => {
    expect(mockAccountsService.getMe).toHaveBeenCalled();
  });

  it('does not show inactive avatar photo controls', () => {
    expect(fixture.nativeElement.textContent).not.toContain('Change photo');
    expect(fixture.nativeElement.textContent).not.toContain('Remove');
  });

  it('should set loadError to true when getMe fails', async () => {
    mockAccountsService.getMe.mockReturnValue(throwError(() => ({ status: 500 })));
    const errorFixture = TestBed.createComponent(Account);
    errorFixture.detectChanges();
    await errorFixture.whenStable();
    expect(errorFixture.componentInstance.loadError).toBe(true);
  });

  it('should display an error toast when getMe fails', async () => {
    mockAccountsService.getMe.mockReturnValue(throwError(() => ({ status: 500 })));
    const errorFixture = TestBed.createComponent(Account);
    errorFixture.detectChanges();
    await errorFixture.whenStable();
    const toast = errorFixture.nativeElement.querySelector('.error-toast-message');
    expect(toast).not.toBeNull();
    expect(toast.textContent).toContain('Failed to load account information');
  });

  // getInitials()

  it('should return initials from first and last name', () => {
    component.firstName = 'Erin';
    component.lastName = 'Lee';
    expect(component.getInitials()).toBe('EL');
  });

  it('should only use the first character of a multi-word first name', () => {
    component.firstName = 'Mary Jane';
    component.lastName = 'Watson';
    expect(component.getInitials()).toBe('MW');
  });

  it('should return a single initial when last name is empty', () => {
    component.firstName = 'Erin';
    component.lastName = '';
    expect(component.getInitials()).toBe('E');
  });

  it('should return uppercase initials', () => {
    component.firstName = 'john';
    component.lastName = 'doe';
    expect(component.getInitials()).toBe('JD');
  });

  it('should render initials in the avatar element', () => {
    fixture.detectChanges();
    const avatar = fixture.nativeElement.querySelector('.avatar-initials');
    expect(avatar.textContent.trim()).toBe('EL');
  });

  // Profile view mode

  it('should start in view mode', () => {
    expect(component.isEditingProfile).toBe(false);
  });

  it('should display the profile name in view mode', () => {
    const el = fixture.nativeElement.querySelector('.profile-name');
    expect(el.textContent.trim()).toBe('Erin Lee');
  });

  it('should show an Edit button in view mode', () => {
    const buttons: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    const editBtn = buttons.find(b => b.textContent?.trim() === 'Edit');
    expect(editBtn).toBeDefined();
  });

  // startEditProfile()

  it('should enter edit mode and copy current values to drafts', () => {
    component.startEditProfile();
    expect(component.isEditingProfile).toBe(true);
    expect(component.draftFirstName).toBe('Erin');
    expect(component.draftLastName).toBe('Lee');
    expect(component.draftEmail).toBe('elee@university.edu');
    expect(component.draftInstitution).toBe('ubc');
  });

  it('should offer University of British Columbia and None institution options', async () => {
    component.startEditProfile();
    fixture.detectChanges();
    await fixture.whenStable();

    const options: HTMLOptionElement[] = Array.from(
      fixture.nativeElement.querySelectorAll('#institution option'),
    );

    expect(options.map(option => option.value)).toEqual(['ubc', 'generic']);
    expect(options.map(option => option.textContent?.trim())).toEqual([
      'University of British Columbia',
      'None',
    ]);
  });

  // cancelEditProfile()

  it('should exit edit mode without modifying the saved values', () => {
    component.startEditProfile();
    component.draftFirstName = 'Changed';
    component.cancelEditProfile();
    expect(component.isEditingProfile).toBe(false);
    expect(component.firstName).toBe('Erin');
  });

  // saveProfile()

  it('should call updateMe with draft values', () => {
    component.startEditProfile();
    component.draftFirstName = 'Jane';
    component.draftLastName = 'Doe';
    component.draftEmail = 'jane@example.com';
    component.saveProfile();
    expect(mockAccountsService.updateMe).toHaveBeenCalledWith('Jane', 'Doe', 'jane@example.com', undefined, 'ubc');
  });

  it('should commit server response values and exit edit mode on success', () => {
    const updatedUser = { ...mockUser, first_name: 'Jane', last_name: 'Doe', email: 'jane@example.com' };
    mockAccountsService.updateMe.mockReturnValue(of(updatedUser));
    component.startEditProfile();
    component.draftFirstName = 'Jane';
    component.draftLastName = 'Doe';
    component.draftEmail = 'jane@example.com';
    component.saveProfile();
    expect(component.isEditingProfile).toBe(false);
    expect(component.firstName).toBe('Jane');
    expect(component.lastName).toBe('Doe');
    expect(component.email).toBe('jane@example.com');
  });

  it('should save the institution and update shared navigation state', () => {
    const updatedUser = { ...mockUser, institution: 'generic' as const };
    mockAccountsService.updateMe.mockReturnValue(of(updatedUser));
    component.startEditProfile();
    component.draftInstitution = 'generic';
    component.saveProfile();

    expect(mockAccountsService.updateMe).toHaveBeenCalledWith(
      'Erin',
      'Lee',
      'elee@university.edu',
      undefined,
      'generic',
    );
    expect(component.institution).toBe('generic');
    expect(TestBed.inject(UserService).currentUser()?.institution).toBe('generic');
  });

  it('should reflect saved name in the avatar after saving', () => {
    const updatedUser = { ...mockUser, first_name: 'Jane', last_name: 'Doe' };
    mockAccountsService.updateMe.mockReturnValue(of(updatedUser));
    component.startEditProfile();
    component.draftFirstName = 'Jane';
    component.draftLastName = 'Doe';
    component.saveProfile();
    fixture.detectChanges();
    const avatar = fixture.nativeElement.querySelector('.avatar-initials');
    expect(avatar.textContent.trim()).toBe('JD');
  });

  // Student number (only relevant for student accounts)

  it('should not include student number in the update when the account is not a student', () => {
    component.role = 'professor';
    component.startEditProfile();
    component.draftStudentNumber = '12345678';
    component.saveProfile();
    expect(mockAccountsService.updateMe).toHaveBeenCalledWith('Erin', 'Lee', 'elee@university.edu', undefined, 'ubc');
  });

  it('should include student number in the update for student accounts', () => {
    component.role = 'student';
    component.studentNumber = '11112222';
    component.startEditProfile();
    component.draftStudentNumber = '99998888';
    component.saveProfile();
    expect(mockAccountsService.updateMe).toHaveBeenCalledWith('Erin', 'Lee', 'elee@university.edu', '99998888', 'ubc');
  });

  it('should set profileError when updateMe fails', () => {
    mockAccountsService.updateMe.mockReturnValue(
      throwError(() => ({ error: { error: { message: 'Email already in use.' } } }))
    );
    component.startEditProfile();
    component.draftFirstName = 'Jane';
    component.draftEmail = 'taken@example.com';
    component.saveProfile();
    expect(component.profileError).toBe('Email already in use.');
    expect(component.isEditingProfile).toBe(true);
  });

  it('should set a generic profileError when updateMe fails with no detail', () => {
    mockAccountsService.updateMe.mockReturnValue(throwError(() => ({})));
    component.startEditProfile();
    component.saveProfile();
    expect(component.profileError).toBe('Failed to save profile. Please try again.');
  });

  it('should set isSavingProfile to true during a pending save', () => {
    const pending = new Subject<typeof mockUser>();
    mockAccountsService.updateMe.mockReturnValue(pending.asObservable());
    component.startEditProfile();
    component.saveProfile();
    expect(component.isSavingProfile).toBe(true);
  });

  // Colour scheme

  it('should default the active scheme to ubc when nothing is stored', () => {
    expect(component.themeService.activeSchemeId()).toBe('ubc');
  });

  it('should list the ubc, ugly, dark, ocean, slate and amethyst schemes', () => {
    const ids = component.schemes.map((s) => s.id);
    expect(ids).toEqual(['ubc', 'ugly', 'dark', 'ocean', 'slate', 'amethyst']);
    expect(component.schemes.find((s) => s.id === 'ocean')?.disabled).toBeFalsy();
    expect(component.schemes.find((s) => s.id === 'slate')?.disabled).toBeFalsy();
    expect(component.schemes.find((s) => s.id === 'amethyst')?.disabled).toBeFalsy();
    expect(component.schemes.find((s) => s.id === 'ubc')?.disabled).toBeFalsy();
  });

  it('should add the dark-mode class to body and persist the choice when selecting Dark', () => {
    component.onSchemeChange('dark');
    expect(component.themeService.activeSchemeId()).toBe('dark');
    expect(document.body.classList.contains('dark-mode')).toBe(true);
    expect(localStorage.getItem('theme:activeScheme')).toBe('dark');
  });

  it('should add the scheme-ocean class to body when selecting Ocean Depth', () => {
    component.onSchemeChange('ocean');
    expect(component.themeService.activeSchemeId()).toBe('ocean');
    expect(document.body.classList.contains('scheme-ocean')).toBe(true);
  });

  it('should remove the dark-mode class from body and apply scheme-ugly when switching back to ugly', () => {
    component.onSchemeChange('dark');
    component.onSchemeChange('ugly');
    expect(document.body.classList.contains('dark-mode')).toBe(false);
    expect(document.body.classList.contains('scheme-ugly')).toBe(true);
  });

  it('should ignore attempts to select an unknown scheme id', () => {
    component.onSchemeChange('not-a-real-scheme');
    expect(component.themeService.activeSchemeId()).toBe('ubc');
  });

  it('should reflect the active scheme in the rendered select element', async () => {
    fixture.detectChanges();
    const select: HTMLSelectElement = fixture.nativeElement.querySelector('select.field-select');
    expect(select.value).toBe('ubc');

    component.onSchemeChange('dark');
    fixture.detectChanges();
    await fixture.whenStable();
    expect(select.value).toBe('dark');
  });

  // Notification preferences

  it('loads notification preferences and the password change status from the account response', () => {
    expect(component.emailNotifications).toBe(true);
    expect(component.regradeAlerts).toBe(true);
    expect(component.batchJobComplete).toBe(true);
    expect(component.passwordLastChangedLabel).toBe('Last changed today');
  });

  it('persists changed notification preferences', () => {
    component.emailNotifications = false;
    component.saveNotificationPreferences();

    expect(mockAccountsService.updateNotificationPreferences).toHaveBeenCalledWith({
      email_notifications_enabled: false,
      regrade_alerts_enabled: true,
      batch_job_complete_enabled: true,
    });
  });

  it('restores notification preferences and shows an error when saving fails', () => {
    mockAccountsService.updateNotificationPreferences.mockReturnValue(
      throwError(() => new Error('network error')),
    );
    component.emailNotifications = false;
    component.saveNotificationPreferences();

    expect(component.emailNotifications).toBe(true);
    expect(component.preferencesError).toContain('Failed to save notification preferences');
  });

  // Password modal

  it('should have showPasswordModal false by default', () => {
    expect(component.showPasswordModal).toBe(false);
  });

  it('should open the password modal when the Change button is clicked', async () => {
    const buttons: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('button'));
    const changeBtn = buttons.find(b => b.textContent?.trim() === 'Change') as HTMLElement;
    changeBtn.click();
    fixture.detectChanges();
    await fixture.whenStable();
    expect(component.showPasswordModal).toBe(true);
    expect(fixture.nativeElement.querySelector('.modal-card')).not.toBeNull();
  });

  it('should close the modal when Cancel is clicked', async () => {
    component.showPasswordModal = true;
    fixture.detectChanges();
    await fixture.whenStable();
    const buttons: HTMLElement[] = Array.from(fixture.nativeElement.querySelectorAll('.modal-footer button'));
    const cancelBtn = buttons.find(b => b.textContent?.trim() === 'Cancel') as HTMLElement;
    cancelBtn.click();
    fixture.detectChanges();
    expect(component.showPasswordModal).toBe(false);
  });

  it('should close the modal when the close icon button is clicked', async () => {
    component.showPasswordModal = true;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.nativeElement.querySelector('.icon-btn--danger').click();
    fixture.detectChanges();
    expect(component.showPasswordModal).toBe(false);
  });

  it('should close the modal when the overlay is clicked', async () => {
    component.showPasswordModal = true;
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.nativeElement.querySelector('.modal-overlay').click();
    fixture.detectChanges();
    expect(component.showPasswordModal).toBe(false);
  });

  // changePassword()

  it('should set passwordError when passwords do not match', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'NewPass1!';
    component.confirmPassword = 'Different1!';
    component.changePassword();
    expect(component.passwordError).toBe('New passwords do not match.');
    expect(mockAccountsService.changePassword).not.toHaveBeenCalled();
  });

  it('should reject a new password shorter than 12 characters', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'Short1!';
    component.confirmPassword = 'Short1!';
    component.changePassword();
    expect(component.passwordError).toBe('Password must be at least 12 characters.');
    expect(mockAccountsService.changePassword).not.toHaveBeenCalled();
  });

  it('should reject a new password missing an uppercase letter', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'alllowercase1!';
    component.confirmPassword = 'alllowercase1!';
    component.changePassword();
    expect(component.passwordError).toBe('Password must contain at least one uppercase letter.');
    expect(mockAccountsService.changePassword).not.toHaveBeenCalled();
  });

  it('should reject a new password missing a number', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'NoNumberHere!!';
    component.confirmPassword = 'NoNumberHere!!';
    component.changePassword();
    expect(component.passwordError).toBe('Password must contain at least one number.');
    expect(mockAccountsService.changePassword).not.toHaveBeenCalled();
  });

  it('should reject a new password missing a special character', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'NoSpecialChar1';
    component.confirmPassword = 'NoSpecialChar1';
    component.changePassword();
    expect(component.passwordError).toBe('Password must contain at least one special character.');
    expect(mockAccountsService.changePassword).not.toHaveBeenCalled();
  });

  it('should call changePassword service when passwords match', () => {
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(mockAccountsService.changePassword).toHaveBeenCalledWith('OldPass1!', 'ValidPass1!abc');
  });

  it('should clear tokens and navigate to login after successful password change', () => {
    localStorage.setItem('access_token', 'tok');
    localStorage.setItem('refresh_token', 'ref');
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(navigateSpy).toHaveBeenCalledWith(['/login']);
  });

  it('should set passwordError when the server rejects with a string detail', () => {
    mockAccountsService.changePassword.mockReturnValue(
      throwError(() => ({ error: { error: { message: 'Incorrect current password.' } } }))
    );
    component.currentPassword = 'WrongPass1!';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(component.passwordError).toBe('Incorrect current password.');
  });

  it('should extract a readable message from a Pydantic validation error array', () => {
    mockAccountsService.changePassword.mockReturnValue(
      throwError(() => ({
        error: {
          error: {
            message: 'Invalid request',
            details: [{ msg: 'Value error, Password must be different from the current password' }],
          },
        },
      }))
    );
    component.currentPassword = 'ValidPass1!abc';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(component.passwordError).toBe('Password must be different from the current password');
  });

  it('should show a generic error when the server returns no detail', () => {
    mockAccountsService.changePassword.mockReturnValue(
      throwError(() => ({}))
    );
    component.currentPassword = 'WrongPass1!';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(component.passwordError).toBe('Failed to change password. Please try again.');
  });

  it('should set isChangingPassword to true during a pending password change', () => {
    const pending = new Subject<void>();
    mockAccountsService.changePassword.mockReturnValue(pending.asObservable());
    component.currentPassword = 'OldPass1!';
    component.newPassword = 'ValidPass1!abc';
    component.confirmPassword = 'ValidPass1!abc';
    component.changePassword();
    expect(component.isChangingPassword).toBe(true);
  });

  // Logout all

  it('should set isLoggingOut to true when logoutAll is called', () => {
    const pending = new Subject<void>();
    mockAuthService.logoutAll.mockReturnValue(pending.asObservable());
    component.logoutAll();
    expect(component.isLoggingOut).toBe(true);
  });

  it('should disable the Sign Out All Devices button while logging out', () => {
    const pending = new Subject<void>();
    mockAuthService.logoutAll.mockReturnValue(pending.asObservable());
    component.logoutAll();
    fixture.detectChanges();
    const btn = fixture.nativeElement.querySelector('.action-btn--danger');
    expect(btn.disabled).toBe(true);
  });

  it('should show loading text on the logout button while logging out', () => {
    const pending = new Subject<void>();
    mockAuthService.logoutAll.mockReturnValue(pending.asObservable());
    component.logoutAll();
    fixture.detectChanges();
    const btn = fixture.nativeElement.querySelector('.action-btn--danger');
    expect(btn.textContent.trim()).toBe('Signing out...');
  });

  it('should navigate to login after successful logout', () => {
    mockAuthService.logoutAll.mockReturnValue(of(undefined as void));
    component.logoutAll();
    expect(navigateSpy).toHaveBeenCalledWith(['/login']);
  });

  it('should navigate to login even when logout errors', () => {
    mockAuthService.logoutAll.mockReturnValue(throwError(() => new Error('network error')));
    component.logoutAll();
    expect(navigateSpy).toHaveBeenCalledWith(['/login']);
  });
});
