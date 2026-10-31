import { TestBed } from '@angular/core/testing';
import { HttpClient, provideHttpClient, withInterceptors } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { Router } from '@angular/router';
import { vi } from 'vitest';
import { authInterceptor } from './auth.interceptor';

describe('authInterceptor', () => {
  let http: HttpClient;
  let httpMock: HttpTestingController;
  let navigate: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    navigate = vi.fn();
    localStorage.clear();
    sessionStorage.clear();

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: Router, useValue: { navigate, url: '/courses' } },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  it('attaches the access token as a bearer header', () => {
    localStorage.setItem('access_token', 'access-1');

    http.get('/api/scans/exam/1').subscribe();

    const req = httpMock.expectOne('/api/scans/exam/1');
    expect(req.request.headers.get('Authorization')).toBe('Bearer access-1');
    req.flush({});
  });

  it('refreshes the token and retries the original request on a 401', () => {
    localStorage.setItem('access_token', 'expired-access');
    localStorage.setItem('refresh_token', 'refresh-1');

    let result: unknown;
    http.get('/api/scans/exam/1').subscribe((r) => (result = r));

    const first = httpMock.expectOne('/api/scans/exam/1');
    first.flush({ detail: 'expired' }, { status: 401, statusText: 'Unauthorized' });

    const refresh = httpMock.expectOne('/api/auth/refresh');
    expect(refresh.request.body).toEqual({ refresh_token: 'refresh-1' });
    refresh.flush({ access_token: 'new-access', refresh_token: 'new-refresh' });

    const retry = httpMock.expectOne('/api/scans/exam/1');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new-access');
    retry.flush([{ id: 'scan-1' }]);

    expect(result).toEqual([{ id: 'scan-1' }]);
    expect(localStorage.getItem('access_token')).toBe('new-access');
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('redirects to login without calling refresh when there is no refresh token', () => {
    localStorage.setItem('access_token', 'expired-access');

    let sawError = false;
    http.get('/api/scans/exam/1').subscribe({ error: () => (sawError = true) });

    const first = httpMock.expectOne('/api/scans/exam/1');
    first.flush({}, { status: 401, statusText: 'Unauthorized' });

    httpMock.expectNone('/api/auth/refresh');
    expect(sawError).toBe(true);
    expect(navigate).toHaveBeenCalledWith(['/login']);
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('redirects to login on a single attempt when the refresh call itself 401s, without recursing', () => {
    localStorage.setItem('access_token', 'expired-access');
    localStorage.setItem('refresh_token', 'invalid-refresh');

    let sawError = false;
    http.get('/api/scans/exam/1').subscribe({ error: () => (sawError = true) });

    const first = httpMock.expectOne('/api/scans/exam/1');
    first.flush({}, { status: 401, statusText: 'Unauthorized' });

    const refresh = httpMock.expectOne('/api/auth/refresh');
    refresh.flush({}, { status: 401, statusText: 'Unauthorized' });

    // The failed refresh call must not trigger another refresh attempt.
    httpMock.expectNone('/api/auth/refresh');
    expect(sawError).toBe(true);
    expect(navigate).toHaveBeenCalledWith(['/login']);
    expect(localStorage.getItem('refresh_token')).toBeNull();
  });

  it('shares a single refresh call across requests that 401 at the same time', () => {
    // Refresh tokens are single-use on the backend, so if two requests both
    // 401 concurrently (e.g. NotificationService's paired unread-count/recent
    // calls), each independently redeeming the same refresh token would have
    // the second one reuse an already-consumed token and blow up the session.
    localStorage.setItem('access_token', 'expired-access');
    localStorage.setItem('refresh_token', 'refresh-1');

    const results: unknown[] = [];
    http.get('/api/notifications/unread-count').subscribe((r) => results.push(r));
    http.get('/api/notifications').subscribe((r) => results.push(r));

    httpMock
      .expectOne('/api/notifications/unread-count')
      .flush({}, { status: 401, statusText: 'Unauthorized' });
    httpMock.expectOne('/api/notifications').flush({}, { status: 401, statusText: 'Unauthorized' });

    const refresh = httpMock.expectOne('/api/auth/refresh');
    httpMock.expectNone('/api/auth/refresh');
    refresh.flush({ access_token: 'new-access', refresh_token: 'new-refresh' });

    httpMock.expectOne('/api/notifications/unread-count').flush({ count: 1 });
    httpMock.expectOne('/api/notifications').flush({ items: [], total: 0 });

    expect(results).toEqual([{ count: 1 }, { items: [], total: 0 }]);
    expect(localStorage.getItem('access_token')).toBe('new-access');
  });

  it('passes through the original 401 body for a failed login without attempting refresh', () => {
    // Regression test: a 401 from /api/auth/login is the direct answer to the
    // login attempt (bad credentials, disabled account, etc.), not an expired
    // session. It must reach the caller with its real error body intact
    // instead of being replaced by a generic "Session expired" Error.
    localStorage.setItem('refresh_token', 'stale-refresh-from-a-previous-session');

    let caughtError: any;
    http.post('/api/auth/login', { email: 'a@example.com', password: 'wrong' }).subscribe({
      error: (err) => (caughtError = err),
    });

    const login = httpMock.expectOne('/api/auth/login');
    login.flush(
      { error: { code: 'account_disabled', message: 'Your account has been disabled' } },
      { status: 401, statusText: 'Unauthorized' },
    );

    httpMock.expectNone('/api/auth/refresh');
    expect(caughtError.error.error.code).toBe('account_disabled');
    expect(navigate).not.toHaveBeenCalled();
  });

  it('keeps Canvas student result access separate from the login session', () => {
    localStorage.setItem('access_token', 'normal-login-token');
    localStorage.setItem('refresh_token', 'normal-refresh-token');

    let caughtError: any;
    http
      .post('/api/canvas/student-results/access', { access_token: 'canvas-result-token' })
      .subscribe({ error: (err) => (caughtError = err) });

    const request = httpMock.expectOne('/api/canvas/student-results/access');
    expect(request.request.headers.has('Authorization')).toBe(false);
    request.flush(
      { error: { code: 'invalid_canvas_student_access' } },
      { status: 401, statusText: 'Unauthorized' },
    );

    httpMock.expectNone('/api/auth/refresh');
    expect(caughtError.error.error.code).toBe('invalid_canvas_student_access');
    expect(navigate).not.toHaveBeenCalled();
    expect(localStorage.getItem('access_token')).toBe('normal-login-token');
    expect(localStorage.getItem('refresh_token')).toBe('normal-refresh-token');
  });

  it('clears tokens but does not navigate when a stray 401 lands while already on a public route', () => {
    // Regression test: a background request (e.g. NotificationService's poll)
    // 401ing while the user is filling out the registration form must not
    // yank them off the page they're actively using.
    TestBed.resetTestingModule();
    navigate = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(withInterceptors([authInterceptor])),
        provideHttpClientTesting(),
        { provide: Router, useValue: { navigate, url: '/registration' } },
      ],
    });
    http = TestBed.inject(HttpClient);
    httpMock = TestBed.inject(HttpTestingController);

    localStorage.setItem('access_token', 'stale-access');

    let sawError = false;
    http.get('/api/notifications/unread-count').subscribe({ error: () => (sawError = true) });

    httpMock
      .expectOne('/api/notifications/unread-count')
      .flush({}, { status: 401, statusText: 'Unauthorized' });

    httpMock.expectNone('/api/auth/refresh');
    expect(sawError).toBe(true);
    expect(navigate).not.toHaveBeenCalled();
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  // "Remember me" unchecked -> tokens live in sessionStorage instead of localStorage

  it('attaches the access token as a bearer header when it lives in sessionStorage', () => {
    sessionStorage.setItem('access_token', 'session-access');

    http.get('/api/scans/exam/1').subscribe();

    const req = httpMock.expectOne('/api/scans/exam/1');
    expect(req.request.headers.get('Authorization')).toBe('Bearer session-access');
    req.flush({});
  });

  it('refreshes a sessionStorage-backed session and keeps the new tokens in sessionStorage', () => {
    sessionStorage.setItem('access_token', 'expired-access');
    sessionStorage.setItem('refresh_token', 'refresh-1');

    let result: unknown;
    http.get('/api/scans/exam/1').subscribe((r) => (result = r));

    httpMock.expectOne('/api/scans/exam/1').flush({}, { status: 401, statusText: 'Unauthorized' });
    httpMock.expectOne('/api/auth/refresh').flush({ access_token: 'new-access', refresh_token: 'new-refresh' });

    const retry = httpMock.expectOne('/api/scans/exam/1');
    expect(retry.request.headers.get('Authorization')).toBe('Bearer new-access');
    retry.flush([{ id: 'scan-1' }]);

    expect(result).toEqual([{ id: 'scan-1' }]);
    expect(sessionStorage.getItem('access_token')).toBe('new-access');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('clears both localStorage and sessionStorage on a redirect-to-login', () => {
    localStorage.setItem('access_token', 'stale-local');
    sessionStorage.setItem('access_token', 'expired-access');

    let sawError = false;
    http.get('/api/scans/exam/1').subscribe({ error: () => (sawError = true) });

    httpMock.expectOne('/api/scans/exam/1').flush({}, { status: 401, statusText: 'Unauthorized' });

    httpMock.expectNone('/api/auth/refresh');
    expect(sawError).toBe(true);
    expect(navigate).toHaveBeenCalledWith(['/login']);
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });
});
