import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { map, catchError, of } from 'rxjs';
import { UserService } from '../services/user.service';
import { AuthService } from '../services/auth.service';

export const authGuard: CanActivateFn = (_route, state) => {
  const router = inject(Router);
  const userService = inject(UserService);
  const authService = inject(AuthService);

  if (!authService.isLoggedIn()) {
    rememberReturnUrl(state.url);
    return router.createUrlTree(['/login'], {
      queryParams: { returnUrl: state.url },
    });
  }

  return userService.ensureLoaded().pipe(
    map(() => true),
    catchError(() => {
      rememberReturnUrl(state.url);
      return of(router.createUrlTree(['/login'], {
        queryParams: { returnUrl: state.url },
      }));
    })
  );
};

function rememberReturnUrl(returnUrl: string): void {
  if (typeof sessionStorage === 'undefined') return;
  sessionStorage.setItem('auth.returnUrl', returnUrl);
}
