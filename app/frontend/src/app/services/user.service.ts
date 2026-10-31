import { Injectable, inject, signal, computed } from '@angular/core';
import { Observable, of } from 'rxjs';
import { finalize, shareReplay, tap } from 'rxjs/operators';
import { CurrentUser } from '../models/auth.model';
import { Accounts } from './accounts';

@Injectable({ providedIn: 'root' })
export class UserService {
  private accounts = inject(Accounts);
  private loadInFlight: Observable<CurrentUser> | null = null;

  readonly currentUser = signal<CurrentUser | null>(null);
  readonly role = computed(() => this.currentUser()?.role ?? null);

  readonly isProfessorOrAbove = computed(() => {
    const r = this.role();
    return r === 'admin' || r === 'professor';
  });

  readonly isStudent = computed(() => this.role() === 'student');
  readonly isAdmin = computed(() => this.role() === 'admin');

  load(): Observable<CurrentUser> {
    return this.accounts.getMe().pipe(tap(user => this.currentUser.set(user)));
  }

  // Loads the user if not already loaded, sharing a single in-flight request
  // across concurrent callers (e.g. authGuard and roleGuard running in parallel).
  ensureLoaded(): Observable<CurrentUser> {
    const existing = this.currentUser();
    if (existing) {
      return of(existing);
    }

    if (!this.loadInFlight) {
      this.loadInFlight = this.load().pipe(
        finalize(() => this.loadInFlight = null),
        shareReplay(1),
      );
    }
    return this.loadInFlight;
  }

  clear(): void {
    this.currentUser.set(null);
  }
}
