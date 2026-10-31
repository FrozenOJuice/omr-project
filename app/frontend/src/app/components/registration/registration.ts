import { Component, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { finalize } from 'rxjs/operators';
import { AuthService } from '../../services/auth.service';
import { SiteIdentity } from '../../sub-components/site-identity/site-identity';

@Component({
  selector: 'app-registration',
  imports: [FormsModule, SiteIdentity],
  templateUrl: './registration.html',
  styleUrl: './registration.css',
})
export class Registration {
  private router = inject(Router);
  private route = inject(ActivatedRoute);
  private authService = inject(AuthService);
  private readonly returnUrlStorageKey = 'auth.returnUrl';

  isLoading = signal(false);
  errorMessage = signal('');
  showPasswords = signal(false);

  firstName = '';
  lastName = '';
  email = '';
  password = '';
  confirmPassword = '';
  role = 'student';
  studentNumber = '';

  navigateToLogin() {
    const returnUrl = this.returnUrl();
    this.router.navigate(['/login'], {
      queryParams: returnUrl ? { returnUrl } : undefined,
    });
  }

  createAccount(event: Event) {
    event.preventDefault();
    this.errorMessage.set('');

    if (!this.firstName || !this.lastName || !this.email || !this.password || !this.confirmPassword) {
      this.errorMessage.set('Please fill in all fields.');
      return;
    }

    if (!this.isValidPassword(this.password)) {
      this.errorMessage.set('Password must be at least 12 characters and contain an uppercase letter, lowercase letter, number, and special character.');
      return;
    }

    if (!this.isValidEmail(this.email)) {
      this.errorMessage.set('Please enter a valid email address.');
      return;
    }

    if (this.password !== this.confirmPassword) {
      this.errorMessage.set('Passwords do not match.');
      return;
    }

    if (this.role === 'student' && !this.isValidStudentNumber(this.studentNumber)) {
      this.errorMessage.set('Student number must be exactly 8 digits.');
      return;
    }

    this.isLoading.set(true);
    this.authService.register(
      this.firstName.trim(),
      this.lastName.trim(),
      this.email.trim().toLowerCase(),
      this.password,
      this.role,
      this.role === 'student' ? this.studentNumber.trim() : undefined,
    ).pipe(
      finalize(() => { this.isLoading.set(false); })
    ).subscribe({
      next: () => this.navigateAfterAuth(),
      error: (err) => {
        const errorCode = err.error?.error?.code;

        if (err.status === 409 && errorCode === 'student_number_exists') {
          this.errorMessage.set('An account with this student number already exists.');
        } else if (err.status === 409) {
          this.errorMessage.set('An account with this email already exists.');
        } else if (err.status === 429) {
          this.errorMessage.set('Too many account creation attempts. Please wait a few minutes and try again.');
        } else if (err.status === 422) {
          this.errorMessage.set('Please check your inputs and try again.');
        } else {
          this.errorMessage.set('Unable to create account. Please try again.');
        }
      },
    });
  }

  private isValidPassword(password: string): boolean {
    return (
      password.length >= 8 &&
      /[A-Z]/.test(password) &&
      /[a-z]/.test(password) &&
      /[0-9]/.test(password) &&
      /[!@#$%^&*()_+\-=\[\]{};':"\\|,.<>\/?]/.test(password)
    );
  }

  private isValidEmail(email: string): boolean {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
  }

  private isValidStudentNumber(studentNumber: string): boolean {
    return /^\d{8}$/.test(studentNumber.trim());
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
