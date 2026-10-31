import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, catchError, map, of, shareReplay, switchMap, timer } from 'rxjs';
import { takeUntilDestroyed, toObservable, toSignal } from '@angular/core/rxjs-interop';
import {
  ApiNotification,
  ApiNotificationList,
  ApiNotificationType,
  Notification,
  NotificationDisplayType,
  NotificationSeverity,
} from '../models/notification';
import { UserService } from './user.service';

const POLL_INTERVAL_MS = 2500;

const REGRADE_TYPES: ApiNotificationType[] = ['review_request_created', 'review_request_resolved'];
const ERROR_TYPES: ApiNotificationType[] = ['scan_failed', 'grading_failed'];

function toDisplayType(type: ApiNotificationType): NotificationDisplayType {
  return REGRADE_TYPES.includes(type) ? 'Re-grade' : 'Processing';
}

function toSeverity(type: ApiNotificationType): NotificationSeverity {
  return ERROR_TYPES.includes(type) ? 'error' : 'info';
}

function formatTime(isoDate: string): string {
  const date = new Date(isoDate);
  const now = new Date();
  const isToday = date.toDateString() === now.toDateString();
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });

  if (isToday) return time;

  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return `Yesterday, ${time}`;

  return `${date.toLocaleDateString()}, ${time}`;
}

function toNotification(n: ApiNotification): Notification {
  return {
    id: n.id,
    type: toDisplayType(n.type),
    severity: toSeverity(n.type),
    title: n.title,
    course: n.course_label ?? '',
    courseId: n.course_id,
    subtitle: n.body ?? '',
    time: formatTime(n.created_at),
    createdAt: n.created_at,
    isRead: n.is_read,
    linkPath: n.link_path,
    linkQuery: n.link_query,
  };
}

const MIN_TOAST_CANDIDATES = 5;
// Upper bound on how many notifications a single poll tick will fetch for
// toast detection. Without a cap, a pathological unread count would turn
// every 30s poll into a full-table fetch.
const MAX_TOAST_CANDIDATES = 50;
const LAST_SEEN_STORAGE_PREFIX = 'notifications:lastSeenCreatedAt:';

@Injectable({ providedIn: 'root' })
export class NotificationService {
  private http = inject(HttpClient);
  private userService = inject(UserService);

  // A single poll every 30s drives both the unread badge count and the
  // "new notification" toast stream, so the app makes one round-trip per
  // tick instead of two independent pollers. `recent` is sized off `count`
  // (rather than a fixed page size) so a burst of unread notifications
  // between polls doesn't push some of them past the fetched page — an
  // item that's never fetched can never be toasted, and once the "last
  // seen" cursor advances past its timestamp it never will be.
  //
  // The whole timer is gated on UserService.currentUser: without this, the
  // poll (started once, root-provided, never torn down by route changes)
  // keeps firing after logout/session-expiry with an invalid token, 401s
  // every 30s, and authInterceptor's global redirect-on-401 boots the user
  // out of whatever unrelated page they're on (e.g. mid-registration).
  private poll$ = toObservable(this.userService.currentUser).pipe(
    switchMap((user) => {
      if (!user) return of({ count: 0, recent: [] as Notification[] });
      return timer(0, POLL_INTERVAL_MS).pipe(
        switchMap(() =>
          this.getUnreadCount().pipe(
            switchMap((count) => {
              const pageSize = Math.min(MAX_TOAST_CANDIDATES, Math.max(MIN_TOAST_CANDIDATES, count));
              return this.getAll(1, pageSize).pipe(map((res) => ({ count, recent: res.items })));
            }),
            // A single failed tick must not kill the whole timer -- shareReplay
            // caches a terminal error forever, which would permanently stop
            // polling for the rest of the session instead of just skipping
            // this tick.
            catchError(() => of({ count: 0, recent: [] as Notification[] })),
          ),
        ),
      );
    }),
    shareReplay({ bufferSize: 1, refCount: false }),
  );

  unreadCount = toSignal(this.poll$.pipe(map((r) => r.count)), { initialValue: 0 });

  // Notifications that arrived since the previous poll (unread, newer than
  // anything seen before). Nothing is emitted from the very first poll ever
  // seen for this user, so logging in doesn't dump every pre-existing unread
  // notification as a toast. The cursor is persisted in localStorage (keyed
  // per user, since multiple accounts may share a browser in dev/testing) so
  // a hard refresh or new tab doesn't re-open that same window and re-swallow
  // notifications that arrived since the last time this browser saw them.
  private newNotificationsSubject = new Subject<Notification>();
  newNotifications$ = this.newNotificationsSubject.asObservable();

  showToast(title: string, subtitle = '', severity: NotificationSeverity = 'info'): void {
    const createdAt = new Date().toISOString();
    this.newNotificationsSubject.next({
      id: `toast-${crypto.randomUUID()}`,
      type: 'Processing',
      severity,
      title,
      course: '',
      courseId: null,
      subtitle,
      time: '',
      createdAt,
      isRead: true,
      linkPath: null,
      linkQuery: null,
    });
  }

  private get lastSeenStorageKey(): string {
    return `${LAST_SEEN_STORAGE_PREFIX}${this.userService.currentUser()?.id ?? 'anonymous'}`;
  }

  constructor() {
    this.poll$.pipe(takeUntilDestroyed()).subscribe(({ recent }) => this.detectNewNotifications(recent));
  }

  private detectNewNotifications(recent: Notification[]): void {
    // Re-read per current user on every tick (rather than caching once at
    // construction) so switching accounts in the same tab picks up that
    // user's own baseline/cursor instead of the previous user's.
    const key = this.lastSeenStorageKey;
    const stored = localStorage.getItem(key);
    // A stored value of '' means "baseline already established, nothing seen
    // yet" (as opposed to no stored key at all, meaning "never established").
    const hasBaseline = stored !== null;
    const lastSeenCreatedAt = stored || null;

    // getAll() orders newest-first, so recent[0] is the most recent overall.
    const unread = recent.filter((n) => !n.isRead);

    if (hasBaseline) {
      const fresh = lastSeenCreatedAt ? unread.filter((n) => n.createdAt > lastSeenCreatedAt) : unread;
      // Emit oldest-first so toasts appear in the order they happened.
      [...fresh].reverse().forEach((n) => this.newNotificationsSubject.next(n));
    } else {
      localStorage.setItem(key, lastSeenCreatedAt ?? '');
    }

    if (unread.length > 0 && (!lastSeenCreatedAt || unread[0].createdAt > lastSeenCreatedAt)) {
      localStorage.setItem(key, unread[0].createdAt);
    }
  }

  getAll(page = 1, pageSize = 100): Observable<{ items: Notification[]; total: number }> {
    return this.http
      .get<ApiNotificationList>('/api/notifications', {
        params: { page, page_size: pageSize },
      })
      .pipe(map((res) => ({ items: res.items.map(toNotification), total: res.total })));
  }

  getUnreadCount(): Observable<number> {
    return this.http
      .get<{ count: number }>('/api/notifications/unread-count')
      .pipe(map((res) => res.count));
  }

  markRead(id: string): Observable<void> {
    return this.http.patch<void>(`/api/notifications/${id}/read`, {});
  }

  markAllRead(): Observable<void> {
    return this.http.patch<void>('/api/notifications/read-all', {});
  }
}
