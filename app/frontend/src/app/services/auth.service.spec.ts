import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { vi } from 'vitest';
import { AuthService } from './auth.service';
import { UserService } from './user.service';
import { TokenResponse } from '../models/auth.model';

const mockTokens: TokenResponse = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  token_type: 'bearer',
};

describe('AuthService', () => {
  let service: AuthService;
  let httpMock: HttpTestingController;
  const mockUserService = { clear: vi.fn() };

  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    sessionStorage.clear();

    TestBed.configureTestingModule({
      providers: [
        provideHttpClient(),
        provideHttpClientTesting(),
        { provide: UserService, useValue: mockUserService },
      ],
    });

    service = TestBed.inject(AuthService);
    httpMock = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    httpMock.verify();
    localStorage.clear();
    sessionStorage.clear();
  });

  // login / rememberMe

  it('stores tokens in sessionStorage by default (rememberMe unset)', () => {
    service.login('a@example.com', 'pw').subscribe();
    httpMock.expectOne('/api/auth/login').flush(mockTokens);

    expect(sessionStorage.getItem('access_token')).toBe('access-1');
    expect(sessionStorage.getItem('refresh_token')).toBe('refresh-1');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('stores tokens in localStorage when rememberMe is true', () => {
    service.login('a@example.com', 'pw', true).subscribe();
    httpMock.expectOne('/api/auth/login').flush(mockTokens);

    expect(localStorage.getItem('access_token')).toBe('access-1');
    expect(localStorage.getItem('refresh_token')).toBe('refresh-1');
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });

  it('stores tokens in sessionStorage when rememberMe is explicitly false', () => {
    service.login('a@example.com', 'pw', false).subscribe();
    httpMock.expectOne('/api/auth/login').flush(mockTokens);

    expect(sessionStorage.getItem('access_token')).toBe('access-1');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  it('clears any prior tokens before storing a fresh login, even across storages', () => {
    localStorage.setItem('access_token', 'stale-local');
    sessionStorage.setItem('access_token', 'stale-session');

    service.login('a@example.com', 'pw', true).subscribe();
    httpMock.expectOne('/api/auth/login').flush(mockTokens);

    expect(localStorage.getItem('access_token')).toBe('access-1');
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });

  it('always stores registration tokens in localStorage', () => {
    service.register('Jane', 'Doe', 'a@example.com', 'pw', 'student').subscribe();
    httpMock.expectOne('/api/auth/register').flush(mockTokens);

    expect(localStorage.getItem('access_token')).toBe('access-1');
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });

  // isLoggedIn / getAccessToken / getRefreshToken

  it('isLoggedIn is false when neither storage has an access token', () => {
    expect(service.isLoggedIn()).toBe(false);
  });

  it('isLoggedIn is true when the access token is in localStorage', () => {
    localStorage.setItem('access_token', 'access-1');
    expect(service.isLoggedIn()).toBe(true);
  });

  it('isLoggedIn is true when the access token is in sessionStorage', () => {
    sessionStorage.setItem('access_token', 'access-1');
    expect(service.isLoggedIn()).toBe(true);
  });

  it('getAccessToken falls back to sessionStorage when localStorage has nothing', () => {
    sessionStorage.setItem('access_token', 'session-access');
    expect(service.getAccessToken()).toBe('session-access');
  });

  it('getRefreshToken prefers localStorage over sessionStorage', () => {
    localStorage.setItem('refresh_token', 'local-refresh');
    sessionStorage.setItem('refresh_token', 'session-refresh');
    expect(service.getRefreshToken()).toBe('local-refresh');
  });

  // updateStoredTokens

  it('updateStoredTokens keeps a remembered session in localStorage', () => {
    localStorage.setItem('access_token', 'old-access');
    localStorage.setItem('refresh_token', 'old-refresh');

    service.updateStoredTokens({ access_token: 'new-access', refresh_token: 'new-refresh', token_type: 'bearer' });

    expect(localStorage.getItem('access_token')).toBe('new-access');
    expect(localStorage.getItem('refresh_token')).toBe('new-refresh');
    expect(sessionStorage.getItem('access_token')).toBeNull();
  });

  it('updateStoredTokens keeps a non-remembered session in sessionStorage', () => {
    sessionStorage.setItem('access_token', 'old-access');
    sessionStorage.setItem('refresh_token', 'old-refresh');

    service.updateStoredTokens({ access_token: 'new-access', refresh_token: 'new-refresh', token_type: 'bearer' });

    expect(sessionStorage.getItem('access_token')).toBe('new-access');
    expect(localStorage.getItem('access_token')).toBeNull();
  });

  // clearTokens

  it('clearTokens removes tokens from both storages', () => {
    localStorage.setItem('access_token', 'a');
    localStorage.setItem('refresh_token', 'r');
    sessionStorage.setItem('access_token', 'a');
    sessionStorage.setItem('refresh_token', 'r');

    service.clearTokens();

    expect(localStorage.getItem('access_token')).toBeNull();
    expect(localStorage.getItem('refresh_token')).toBeNull();
    expect(sessionStorage.getItem('access_token')).toBeNull();
    expect(sessionStorage.getItem('refresh_token')).toBeNull();
  });

  // logout / logoutAll

  it('logout reads the refresh token from whichever storage holds it and clears both on completion', () => {
    sessionStorage.setItem('refresh_token', 'refresh-1');

    service.logout().subscribe();

    const req = httpMock.expectOne('/api/auth/logout');
    expect(req.request.body).toEqual({ refresh_token: 'refresh-1' });
    req.flush(null);

    expect(sessionStorage.getItem('refresh_token')).toBeNull();
    expect(mockUserService.clear).toHaveBeenCalled();
  });

  it('logoutAll clears tokens even when the request fails', () => {
    localStorage.setItem('access_token', 'a');
    localStorage.setItem('refresh_token', 'r');

    let errored = false;
    service.logoutAll().subscribe({ error: () => (errored = true) });

    httpMock.expectOne('/api/auth/logout-all').flush('fail', { status: 500, statusText: 'Server Error' });

    expect(errored).toBe(true);
    expect(localStorage.getItem('access_token')).toBeNull();
    expect(mockUserService.clear).toHaveBeenCalled();
  });
});
