import { HttpErrorResponse, HttpHandlerFn, HttpInterceptorFn, HttpRequest } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, finalize, Observable, shareReplay, switchMap, throwError } from 'rxjs';
import { HttpClient } from '@angular/common/http';
import { TokenResponse } from '../models/auth.model';
import { UserService } from '../services/user.service';
import { AuthService } from '../services/auth.service';

// Routes reachable without a session. A 401 surfacing here (e.g. from a
// stray background request racing an unrelated navigation) must not yank
// the user out of a form they're actively filling in on one of these pages.
const PUBLIC_ROUTES = ['/login', '/registration', '/forgot-password', '/reset-password', '/canvas/results'];

function addBearer(req: HttpRequest<unknown>, token: string): HttpRequest<unknown> {
  return req.clone({ setHeaders: { Authorization: `Bearer ${token}` } });
}

const REFRESH_URL = '/api/auth/refresh';
const LOGIN_URL = '/api/auth/login';
const REGISTER_URL = '/api/auth/register';
const CANVAS_STUDENT_RESULTS_URL = '/api/canvas/student-results';

// Refresh tokens are single-use on the backend (see services/auth_sessions.py:
// each refresh revokes the token it was given and issues a new one, and reusing
// an already-revoked token is treated as replay and revokes the whole session).
// Several requests can 401 in the same tick (e.g. NotificationService fires two
// endpoints per poll), so without this dedup each would read the same refresh
// token from localStorage and race to redeem it — the loser's "reuse" of an
// already-consumed token would nuke the user's session. Sharing one in-flight
// refresh call across all concurrent 401s means they all redeem it exactly once.
let refreshInFlight$: Observable<TokenResponse> | null = null;

function refreshTokens(http: HttpClient, refreshToken: string): Observable<TokenResponse> {
  if (!refreshInFlight$) {
    refreshInFlight$ = http.post<TokenResponse>(REFRESH_URL, { refresh_token: refreshToken }).pipe(
      finalize(() => { refreshInFlight$ = null; }),
      shareReplay(1),
    );
  }
  return refreshInFlight$;
}

// Automatically attaches Authorization: Bearer <token> to every outgoing request
// On a 401, attempts to refresh using the refresh token
// If refresh succeeds, retries the original request with the new token
// If refresh fails (no refresh token or refresh also 401s), clears localStorage and redirects to login

// Note, any future services do not need manual auth header logic

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const router = inject(Router);
  const http = inject(HttpClient);
  const userService = inject(UserService);
  const authService = inject(AuthService);

  // The refresh call itself goes through this same interceptor (there's only one
  // HttpClient in the app). Without this guard, a 401 on /api/auth/refresh would
  // trigger another refresh attempt with the same (invalid) refresh token,
  // recursing indefinitely until the server's rate limiter cuts it off.
  const isRefreshCall = req.url.includes(REFRESH_URL);

  // A 401 from login/register is a direct answer to that request (bad
  // credentials, disabled account, etc.), not an expired session — it must
  // not be swallowed by the refresh-and-retry flow below, which discards the
  // real error body and rethrows a generic "Session expired" Error.
  const isAuthEntryCall = req.url.includes(LOGIN_URL) || req.url.includes(REGISTER_URL);
  const isCanvasStudentResultCall = req.url.includes(CANVAS_STUDENT_RESULTS_URL);

  const token = authService.getAccessToken();
  const authedReq = token && !isRefreshCall && !isCanvasStudentResultCall ? addBearer(req, token) : req;

  return next(authedReq).pipe(
    catchError((err: HttpErrorResponse) => {
      if (err.status !== 401) return throwError(() => err);
      if (isRefreshCall || isAuthEntryCall || isCanvasStudentResultCall) {
        return throwError(() => err);
      }

      const refreshToken = authService.getRefreshToken();
      if (!refreshToken) return redirectToLogin(router, userService, authService);

      return refreshTokens(http, refreshToken).pipe(
        switchMap((tokens) => {
          authService.updateStoredTokens(tokens);
          return next(addBearer(req, tokens.access_token));
        }),
        catchError(() => redirectToLogin(router, userService, authService)),
      );
    }),
  );
};

function redirectToLogin(router: Router, userService: UserService, authService: AuthService) {
  authService.clearTokens();
  userService.clear();
  // Don't force-navigate someone who's already on a public page (e.g.
  // mid-registration) away from what they're doing just because an
  // unrelated background request 401'd.
  const onPublicRoute = PUBLIC_ROUTES.some((route) => router.url.startsWith(route));
  if (!onPublicRoute) router.navigate(['/login']);
  return throwError(() => new Error('Session expired'));
}
