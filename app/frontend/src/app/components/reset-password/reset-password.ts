import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { AuthService } from '../../services/auth.service';
import { SiteIdentity } from '../../sub-components/site-identity/site-identity';

@Component({
  selector: 'app-reset-password',
  imports: [FormsModule, SiteIdentity],
  templateUrl: './reset-password.html',
  styleUrl: './reset-password.css',
})
export class ResetPassword {
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private authService = inject(AuthService);

  // The reset email links here as /reset-password?token=...
  private token = this.route.snapshot.queryParamMap.get('token') ?? '';

  hasToken = signal(this.token.length > 0);
  isLoading = signal(false);
  isSuccess = signal(false);
  errorMessage = signal('');

  password = '';
  confirmPassword = '';

  resetPassword(event: Event) {
    event.preventDefault();
    this.errorMessage.set('');

    if (!this.password || !this.confirmPassword) {
      this.errorMessage.set('Please fill in all fields.');
      return;
    }

    if (!this.isValidPassword(this.password)) {
      this.errorMessage.set('Password must be at least 12 characters and contain an uppercase letter, lowercase letter, number, and special character.');
      return;
    }

    if (this.password !== this.confirmPassword) {
      this.errorMessage.set('Passwords do not match.');
      return;
    }

    this.isLoading.set(true);
    this.authService.confirmPasswordReset(this.token, this.password).pipe(
      finalize(() => { this.isLoading.set(false); })
    ).subscribe({
      next: () => this.isSuccess.set(true),
      error: (err) => this.errorMessage.set(this.messageForError(err)),
    });
  }

  goToLogin() {
    this.router.navigate(['/login']);
  }

  clearError() {
    this.errorMessage.set('');
  }

  private messageForError(err: { status?: number; error?: { error?: { code?: string } } }): string {
    const code = err?.error?.error?.code;

    if (err.status === 400 && code === 'password_reuse') {
      return 'Your new password must be different from your current password.';
    }
    if (err.status === 400) {
      return 'This reset link is invalid or has expired. Please request a new one.';
    }
    if (err.status === 422) {
      return 'Password does not meet the requirements. Please choose a stronger password.';
    }
    if (err.status === 429) {
      return 'Too many attempts. Please wait a moment and try again.';
    }
    return 'Unable to reset your password. Please try again.';
  }

  private isValidPassword(password: string): boolean {
    return (
      password.length >= 12 &&
      /[A-Z]/.test(password) &&
      /[a-z]/.test(password) &&
      /[0-9]/.test(password) &&
      /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)
    );
  }
}
