import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { ResetPassword } from './reset-password';
import { AuthService } from '../../services/auth.service';

const VALID_TOKEN = 'valid-reset-token-0123456789abcdef0123';
const VALID_PASSWORD = 'ValidPass123!';

describe('ResetPassword', () => {
  let fixture: ComponentFixture<ResetPassword>;
  let component: ResetPassword;
  let confirmPasswordReset: ReturnType<typeof vi.fn>;
  let navigate: ReturnType<typeof vi.fn>;
  let queryParams: Record<string, string>;

  // Component reads the token at construction, so create lazily per test
  // after any per-test override of queryParams.
  function createComponent() {
    fixture = TestBed.createComponent(ResetPassword);
    component = fixture.componentInstance;
  }

  beforeEach(async () => {
    queryParams = { token: VALID_TOKEN };
    confirmPasswordReset = vi.fn(() => of(void 0));
    navigate = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ResetPassword, FormsModule],
      providers: [
        { provide: AuthService, useValue: { confirmPasswordReset } },
        { provide: Router, useValue: { navigate } },
        {
          provide: ActivatedRoute,
          useValue: {
            snapshot: {
              get queryParamMap() {
                return convertToParamMap(queryParams);
              },
            },
          },
        },
      ],
    }).compileComponents();
  });

  it('should create', () => {
    createComponent();
    expect(component).toBeTruthy();
  });

  it('should render the Reset Password title', async () => {
    createComponent();
    fixture.detectChanges();
    await fixture.whenStable();

    const title = fixture.nativeElement.querySelector('#formTitle');
    expect(title.textContent).toContain('Reset Password');
  });

  it('should flag a present token', () => {
    createComponent();
    expect(component.hasToken()).toBe(true);
  });

  it('should show the invalid-link state when the token is missing', async () => {
    queryParams = {};
    createComponent();
    fixture.detectChanges();
    await fixture.whenStable();

    expect(component.hasToken()).toBe(false);
    expect(fixture.nativeElement.querySelector('#password')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('invalid');
  });

  it('should set errorMessage when fields are empty', () => {
    createComponent();
    component.resetPassword(new MouseEvent('click'));
    expect(component.errorMessage()).toBe('Please fill in all fields.');
  });

  it('should set errorMessage when the password is too weak', () => {
    createComponent();
    component.password = 'weakpass';
    component.confirmPassword = 'weakpass';

    component.resetPassword(new MouseEvent('click'));
    expect(component.errorMessage()).toBe(
      'Password must be at least 12 characters and contain an uppercase letter, lowercase letter, number, and special character.'
    );
  });

  it('should set errorMessage when passwords do not match', () => {
    createComponent();
    component.password = VALID_PASSWORD;
    component.confirmPassword = 'Different123!';

    component.resetPassword(new MouseEvent('click'));
    expect(component.errorMessage()).toBe('Passwords do not match.');
  });

  it('should call confirmPasswordReset and show success on a valid submit', () => {
    createComponent();
    component.password = VALID_PASSWORD;
    component.confirmPassword = VALID_PASSWORD;

    component.resetPassword(new MouseEvent('click'));

    expect(confirmPasswordReset).toHaveBeenCalledWith(VALID_TOKEN, VALID_PASSWORD);
    expect(component.isSuccess()).toBe(true);
    expect(component.errorMessage()).toBe('');
  });

  it('should show an expired-link message on a 400 invalid_reset_token error', () => {
    confirmPasswordReset.mockReturnValue(
      throwError(() => ({ status: 400, error: { error: { code: 'invalid_reset_token' } } }))
    );
    createComponent();
    component.password = VALID_PASSWORD;
    component.confirmPassword = VALID_PASSWORD;

    component.resetPassword(new MouseEvent('click'));

    expect(component.isSuccess()).toBe(false);
    expect(component.errorMessage()).toBe(
      'This reset link is invalid or has expired. Please request a new one.'
    );
  });

  it('should show a reuse message on a 400 password_reuse error', () => {
    confirmPasswordReset.mockReturnValue(
      throwError(() => ({ status: 400, error: { error: { code: 'password_reuse' } } }))
    );
    createComponent();
    component.password = VALID_PASSWORD;
    component.confirmPassword = VALID_PASSWORD;

    component.resetPassword(new MouseEvent('click'));

    expect(component.errorMessage()).toBe(
      'Your new password must be different from your current password.'
    );
  });

  it('should navigate to login when goToLogin is called', () => {
    createComponent();
    component.goToLogin();
    expect(navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should clear the error message', () => {
    createComponent();
    component.errorMessage.set('Some error');
    component.clearError();
    expect(component.errorMessage()).toBe('');
  });
});
