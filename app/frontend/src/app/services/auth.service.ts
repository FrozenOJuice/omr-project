import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { tap, finalize } from 'rxjs/operators';
import { Observable } from 'rxjs';
import { TokenResponse } from '../models/auth.model';
import { UserService } from './user.service';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private http = inject(HttpClient);
  private userService = inject(UserService);

  register(
    firstName: string,
    lastName: string,
    email: string,
    password: string,
    role: string,
    studentNumber?: string,
  ): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/auth/register', {
      first_name: firstName,
      last_name: lastName,
      email,
      password,
      role,
      student_number: studentNumber || null,
    }).pipe(
      tap(tokens => this.storeTokens(tokens, true))
    );
  }

  // rememberMe controls where the tokens are persisted: localStorage survives
  // browser restarts, sessionStorage is wiped when the browser/tab closes.
  login(email: string, password: string, rememberMe = false): Observable<TokenResponse> {
    return this.http.post<TokenResponse>('/api/auth/login', { email, password }).pipe(
      tap(tokens => this.storeTokens(tokens, rememberMe))
    );
  }

  logoutAll(): Observable<void> {
    const refresh_token = this.getRefreshToken() ?? '';
    return this.http.post<void>('/api/auth/logout-all', { refresh_token }).pipe(
      finalize(() => {
        this.clearTokens();
        this.userService.clear();
      })
    );
  }

  logout(): Observable<void> {
    const refresh_token = this.getRefreshToken() ?? '';
    return this.http.post<void>('/api/auth/logout', { refresh_token }).pipe(
      finalize(() => {
        this.clearTokens();
        this.userService.clear();
      })
    );
  }

  isLoggedIn(): boolean {
    return !!this.getAccessToken();
  }

  getAccessToken(): string | null {
    return localStorage.getItem('access_token') ?? sessionStorage.getItem('access_token');
  }

  getRefreshToken(): string | null {
    return localStorage.getItem('refresh_token') ?? sessionStorage.getItem('refresh_token');
  }

  // Used when refreshing an already-stored access token: keeps the new tokens
  // in whichever storage (local vs session) the session was originally started in.
  updateStoredTokens(tokens: TokenResponse): void {
    const storage = localStorage.getItem('refresh_token') ? localStorage : sessionStorage;
    storage.setItem('access_token', tokens.access_token);
    storage.setItem('refresh_token', tokens.refresh_token);
  }

  clearTokens(): void {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    sessionStorage.removeItem('access_token');
    sessionStorage.removeItem('refresh_token');
  }

  // Requests a password reset email. The backend responds the same way whether
  // or not the account exists, so callers must not branch on the result.
  requestPasswordReset(email: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>('/api/auth/password-reset/request', { email });
  }

  // Confirms a password reset using the token from the reset email.
  // Does not store tokens: a reset does not log the user in.
  confirmPasswordReset(token: string, newPassword: string): Observable<void> {
    return this.http.post<void>('/api/auth/password-reset/confirm', {
      token,
      new_password: newPassword,
    });
  }

  private storeTokens(tokens: TokenResponse, rememberMe = false): void {
    this.clearTokens();
    const storage = rememberMe ? localStorage : sessionStorage;
    storage.setItem('access_token', tokens.access_token);
    storage.setItem('refresh_token', tokens.refresh_token);
  }
}
