import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { UserService } from '../services/user.service';

export const roleGuard = (allowedRoles: string[]): CanActivateFn => () => {
  const router = inject(Router);
  const userService = inject(UserService);

  return userService.ensureLoaded().pipe(
    map(() => {
      const role = userService.role();
      return role && allowedRoles.includes(role) ? true : router.createUrlTree(['/courses']);
    }),
    catchError(() => of(router.createUrlTree(['/login'])))
  );
};
