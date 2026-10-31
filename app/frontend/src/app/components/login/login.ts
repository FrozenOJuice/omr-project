import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { AuthService } from '../../services/auth.service';
import { extractApiErrorMessage } from '../../utils/api-error';
import { SiteIdentity } from '../../sub-components/site-identity/site-identity';

@Component({
  selector: 'app-login',
  imports: [FormsModule, SiteIdentity],
  templateUrl: './login.html',
  styleUrl: './login.css',
})
export class Login {
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private authService = inject(AuthService);
  private readonly returnUrlStorageKey = 'auth.returnUrl';

  isLoading = signal(false);
  errorMessage = signal('');

  email = '';
  password = '';
  showPassword = signal(false);
  rememberMe = false;

  navigateToRegistration() {
    const returnUrl = this.returnUrl();
    this.router.navigate(['/registration'], {
      queryParams: returnUrl ? { returnUrl } : undefined,
    });
  }

  navigateToForgotPassword() {
    this.router.navigate(['/forgot-password']);
  }

  signIn(event: Event) {
    event.preventDefault();
    this.errorMessage.set('');

    if (!this.email || !this.password) {
      this.errorMessage.set('Please fill in all fields.');
      return;
    }

    if (!this.isValidEmail(this.email)) {
      this.errorMessage.set('Please enter a valid email address.');
      return;
    }

    this.isLoading.set(true);
    this.authService.login(this.email.trim().toLowerCase(), this.password, this.rememberMe).pipe(
      finalize(() => { this.isLoading.set(false); })
    ).subscribe({
      next: () => this.navigateAfterAuth(),
      error: (err) => {
        if (err.status === 401 && err.error?.error?.code === 'account_disabled') {
          // The backend only reveals this once the password has already been
          // verified, so this can't be used to enumerate disabled accounts.
          this.errorMessage.set('Your account has been disabled. Contact an administrator for help.');
        } else if (err.status === 401) {
          // Deliberately generic: a specific "no such account" message would
          // let an attacker enumerate valid emails.
          this.errorMessage.set('Invalid email or password.');
        } else if (err.status === 429) {
          this.errorMessage.set('Too many sign-in attempts. Please wait a few minutes and try again.');
        } else {
          this.errorMessage.set(extractApiErrorMessage(err, 'Unable to sign in. Please try again.'));
        }
      },
    });
  }

  private isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  clearError() {
    this.errorMessage.set('');
  }

  private returnUrl(): string {
    const value = this.route.snapshot.queryParamMap.get('returnUrl')
      ?? this.storedReturnUrl()
      ?? '';
    return value.startsWith('/') && !value.startsWith('//') ? value : '';
  }

  private navigateAfterAuth(): void {
    const returnUrl = this.returnUrl();
    this.clearReturnUrl();
    this.router.navigateByUrl(returnUrl || '/courses');
  }

  private storedReturnUrl(): string | null {
    return typeof sessionStorage === 'undefined'
      ? null
      : sessionStorage.getItem(this.returnUrlStorageKey);
  }

  private clearReturnUrl(): void {
    if (typeof sessionStorage !== 'undefined') {
      sessionStorage.removeItem(this.returnUrlStorageKey);
    }
  }
}
