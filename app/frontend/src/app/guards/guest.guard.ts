import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';

// Keeps an already-signed-in user from landing back on the sign-in page:
// bounces them straight to their landing page instead of re-prompting for credentials.
export const guestGuard: CanActivateFn = () => {
  const router = inject(Router);
  const authService = inject(AuthService);

  return authService.isLoggedIn() ? router.createUrlTree(['/courses']) : true;
};
