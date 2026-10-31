import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { AuthService } from '../../services/auth.service';
import { SiteIdentity } from '../../sub-components/site-identity/site-identity';

@Component({
  selector: 'app-forgot-password',
  imports: [FormsModule, SiteIdentity],
  templateUrl: './forgot-password.html',
  styleUrl: './forgot-password.css',
})
export class ForgotPassword {
  private router = inject(Router);
  private authService = inject(AuthService);

  isLoading = signal(false);
  isSubmitted = signal(false);
  submittedEmail = signal('');
  errorMessage = signal('');

  email = '';

  requestReset(event?: Event) {
    event?.preventDefault();

    if (this.isLoading()) {
      return;
    }

    this.errorMessage.set('');
    const normalizedEmail = this.email.trim().toLowerCase();

    if (!normalizedEmail) {
      this.errorMessage.set('Please enter your email address.');
      return;
    }

    if (!this.isValidEmail(normalizedEmail)) {
      this.errorMessage.set('Please enter a valid email address.');
      return;
    }

    this.isLoading.set(true);
    this.authService.requestPasswordReset(normalizedEmail).pipe(
      finalize(() => { this.isLoading.set(false); })
    ).subscribe({
      // The backend returns the same response whether or not the account
      // exists, so we always show the same confirmation.
      next: () => {
        this.submittedEmail.set(normalizedEmail);
        this.isSubmitted.set(true);
      },
      error: (err) => {
        if (err.status === 429) {
          this.errorMessage.set('Too many requests. Please wait a moment and try again.');
        } else {
          this.errorMessage.set('Unable to send the reset link. Please try again.');
        }
      },
    });
  }

  goToLogin() {
    this.router.navigate(['/login']);
  }

  clearError() {
    this.errorMessage.set('');
  }

  private isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }
}
