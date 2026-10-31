import { TestBed } from '@angular/core/testing';
import { Router, UrlTree } from '@angular/router';
import { vi } from 'vitest';
import { guestGuard } from './guest.guard';
import { AuthService } from '../services/auth.service';

describe('guestGuard', () => {
  const mockAuthService = { isLoggedIn: vi.fn(() => false) };
  const mockRouter = { createUrlTree: vi.fn((commands) => ({ commands }) as unknown as UrlTree) };

  beforeEach(() => {
    vi.clearAllMocks();
    mockAuthService.isLoggedIn.mockReturnValue(false);

    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: mockAuthService },
        { provide: Router, useValue: mockRouter },
      ],
    });
  });

  const run = () => TestBed.runInInjectionContext(() => guestGuard({} as never, {} as never));

  it('allows an unauthenticated visitor to reach the login page', () => {
    expect(run()).toBe(true);
    expect(mockRouter.createUrlTree).not.toHaveBeenCalled();
  });

  it('bounces an already-signed-in user to their courses list', () => {
    mockAuthService.isLoggedIn.mockReturnValue(true);

    const result = run();

    expect(mockRouter.createUrlTree).toHaveBeenCalledWith(['/courses']);
    expect(result).toEqual({ commands: ['/courses'] });
  });
});
