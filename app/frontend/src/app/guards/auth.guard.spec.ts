import { TestBed } from '@angular/core/testing';
import { Router, UrlTree } from '@angular/router';
import { vi } from 'vitest';
import { of, throwError } from 'rxjs';
import { authGuard } from './auth.guard';
import { AuthService } from '../services/auth.service';
import { UserService } from '../services/user.service';

describe('authGuard', () => {
  const mockAuthService = { isLoggedIn: vi.fn(() => true) };
  const mockUserService = { ensureLoaded: vi.fn(() => of(undefined)) };
  const mockRouter = { createUrlTree: vi.fn((commands, extras) => ({ commands, extras }) as unknown as UrlTree) };

  const route = {} as never;
  const state = { url: '/courses/c1' } as never;

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthService.isLoggedIn.mockReturnValue(true);
    mockUserService.ensureLoaded.mockReturnValue(of(undefined));
    sessionStorage.clear();

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: mockAuthService },
        { provide: UserService, useValue: mockUserService },
        { provide: Router, useValue: mockRouter },
      ],
    });
  });

  afterEach(() => sessionStorage.clear());

  const run = () => TestBed.runInInjectionContext(() => authGuard(route, state));

  it('redirects to login with a returnUrl when not logged in', () => {
    mockAuthService.isLoggedIn.mockReturnValue(false);

    const result = run();

    expect(mockRouter.createUrlTree).toHaveBeenCalledWith(['/login'], {
      queryParams: { returnUrl: '/courses/c1' },
    });
    expect(result).toEqual({ commands: ['/login'], extras: { queryParams: { returnUrl: '/courses/c1' } } });
  });

  it('remembers the return url in sessionStorage when not logged in', () => {
    mockAuthService.isLoggedIn.mockReturnValue(false);

    run();

    expect(sessionStorage.getItem('auth.returnUrl')).toBe('/courses/c1');
  });

  it('allows navigation once the user profile loads successfully', async () => {
    const result = await new Promise((resolve) => (run() as ReturnType<typeof of>).subscribe(resolve));
    expect(result).toBe(true);
  });

  it('redirects to login when loading the user profile fails, despite having a token', async () => {
    mockUserService.ensureLoaded.mockReturnValue(throwError(() => new Error('401')));

    const result = await new Promise((resolve) => (run() as ReturnType<typeof of>).subscribe(resolve));

    expect(mockRouter.createUrlTree).toHaveBeenCalledWith(['/login'], {
      queryParams: { returnUrl: '/courses/c1' },
    });
    expect(result).toEqual({ commands: ['/login'], extras: { queryParams: { returnUrl: '/courses/c1' } } });
  });
});
