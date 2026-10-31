import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { FormsModule } from '@angular/forms';
import { of, throwError } from 'rxjs';
import { vi } from 'vitest';
import { ForgotPassword } from './forgot-password';
import { AuthService } from '../../services/auth.service';

describe('ForgotPassword', () => {
  let fixture: ComponentFixture<ForgotPassword>;
  let component: ForgotPassword;
  let requestPasswordReset: ReturnType<typeof vi.fn>;
  let navigate: ReturnType<typeof vi.fn>;

  beforeEach(async () => {
    requestPasswordReset = vi.fn(() => of({ message: 'ok' }));
    navigate = vi.fn();

    await TestBed.configureTestingModule({
      imports: [ForgotPassword, FormsModule],
      providers: [
        { provide: AuthService, useValue: { requestPasswordReset } },
        { provide: Router, useValue: { navigate } },
      ],
    }).compileComponents();

    fixture = TestBed.createComponent(ForgotPassword);
    component = fixture.componentInstance;
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should render the Forgot Password title', async () => {
    fixture.detectChanges();
    await fixture.whenStable();

    const title = fixture.nativeElement.querySelector('#formTitle');
    expect(title.textContent).toContain('Forgot Password');
  });

  it('should set errorMessage when the email is empty', () => {
    component.requestReset();
    expect(component.errorMessage()).toBe('Please enter your email address.');
  });

  it('should set errorMessage when the email is only whitespace', () => {
    component.email = '   ';
    component.requestReset();
    expect(component.errorMessage()).toBe('Please enter your email address.');
  });

  it('should set errorMessage when the email is invalid', () => {
    component.email = 'not-an-email';
    component.requestReset();
    expect(component.errorMessage()).toBe('Please enter a valid email address.');
  });

  it('should call requestPasswordReset and show the confirmation on a valid email', () => {
    component.email = 'user@example.com';
    component.requestReset();

    expect(requestPasswordReset).toHaveBeenCalledWith('user@example.com');
    expect(component.isSubmitted()).toBe(true);
    expect(component.submittedEmail()).toBe('user@example.com');
    expect(component.errorMessage()).toBe('');
  });

  it('should normalize the email before sending', () => {
    component.email = '  User@Example.COM  ';
    component.requestReset();
    expect(requestPasswordReset).toHaveBeenCalledWith('user@example.com');
    expect(component.submittedEmail()).toBe('user@example.com');
  });

  it('should show a rate-limit message on a 429 error', () => {
    requestPasswordReset.mockReturnValue(throwError(() => ({ status: 429 })));
    component.email = 'user@example.com';
    component.requestReset();

    expect(component.isSubmitted()).toBe(false);
    expect(component.errorMessage()).toBe('Too many requests. Please wait a moment and try again.');
  });

  it('should show a generic message on non-429 errors', () => {
    requestPasswordReset.mockReturnValue(throwError(() => ({ status: 500 })));
    component.email = 'user@example.com';
    component.requestReset();

    expect(component.isSubmitted()).toBe(false);
    expect(component.errorMessage()).toBe('Unable to send the reset link. Please try again.');
  });

  it('should navigate to login when goToLogin is called', () => {
    component.goToLogin();
    expect(navigate).toHaveBeenCalledWith(['/login']);
  });

  it('should clear the error message', () => {
    component.errorMessage.set('Some error');
    component.clearError();
    expect(component.errorMessage()).toBe('');
  });
});
