import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { vi } from 'vitest';
import { NotificationService } from './notification.service';
import { UserService } from './user.service';
import { ApiNotification, Notification } from '../models/notification';
import { CurrentUser } from '../models/auth.model';

const mkCurrentUser = (overrides: Partial<CurrentUser> = {}): CurrentUser => ({
  id: 'u1',
  first_name: 'Test',
  last_name: 'User',
  email: 'test@example.com',
  role: 'student',
  status: 'active',
  student_number: null,
  password_changed_at: '2026-07-27T00:00:00Z',
  email_notifications_enabled: true,
  regrade_alerts_enabled: true,
  batch_job_complete_enabled: true,
  institution: 'ubc',
  ...overrides,
});

const mkApiNotification = (overrides: Partial<ApiNotification> = {}): ApiNotification => ({
  id: 'n1',
  type: 'grade_ready',
  title: 'Your exam has been graded',
  body: 'Midterm 1',
  course_id: 'c1',
  course_label: 'COSC 320',
  link_path: '/courses',
  link_query: 'courseId=c1&examId=e1',
  is_read: false,
  created_at: '2026-07-07T09:00:00Z',
  ...overrides,
});

describe('NotificationService', () => {
  let service: NotificationService;
  let httpMock: HttpTestingController;

  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    // The poll only runs while a user is logged in (see notification.service.ts) --
    // set this before injecting the service so its poll$ picks up the signed-in
    // state on first subscribe.
    TestBed.inject(UserService).currentUser.set(mkCurrentUser());
    service = TestBed.inject(NotificationService);
    httpMock = TestBed.inject(HttpTestingController);
    // toObservable(currentUser) emits via an effect, which needs a flush to
    // run; timer(0, ...) then still schedules its first tick via the (fake)
    // async scheduler rather than firing synchronously on subscribe.
    TestBed.flushEffects();
    vi.advanceTimersByTime(0);
  });

  afterEach(() => {
    httpMock.verify();
    vi.useRealTimers();
  });

  function flushPollTick(count: number, recent: ApiNotification[]) {
    httpMock.expectOne('/api/notifications/unread-count').flush({ count });
    httpMock
      .expectOne((r) => r.url === '/api/notifications')
      .flush({ items: recent, total: recent.length, page: 1, page_size: 5 });
  }

  it('updates unreadCount from the first poll tick', () => {
    flushPollTick(2, [mkApiNotification({ is_read: false })]);
    expect(service.unreadCount()).toBe(2);
  });

  it('does not emit a toast for notifications already unread on the first poll', () => {
    const received: Notification[] = [];
    service.newNotifications$.subscribe((n) => received.push(n));

    flushPollTick(1, [mkApiNotification({ id: 'n1', is_read: false })]);

    expect(received.length).toBe(0);
  });

  it('emits a toast for a notification that appears in a later poll', () => {
    const received: Notification[] = [];
    service.newNotifications$.subscribe((n) => received.push(n));

    // Baseline poll: nothing unread yet.
    flushPollTick(0, []);

    vi.advanceTimersByTime(2500);
    flushPollTick(1, [
      mkApiNotification({ id: 'n2', created_at: '2026-07-07T10:00:00Z', is_read: false }),
    ]);

    expect(received.map((n) => n.id)).toEqual(['n2']);
  });

  it('does not re-emit a notification already seen in a previous poll', () => {
    const received: Notification[] = [];
    service.newNotifications$.subscribe((n) => received.push(n));

    flushPollTick(0, []);

    vi.advanceTimersByTime(2500);
    flushPollTick(1, [
      mkApiNotification({ id: 'n2', created_at: '2026-07-07T10:00:00Z', is_read: false }),
    ]);

    vi.advanceTimersByTime(2500);
    flushPollTick(1, [
      mkApiNotification({ id: 'n2', created_at: '2026-07-07T10:00:00Z', is_read: false }),
    ]);

    expect(received.map((n) => n.id)).toEqual(['n2']);
  });

  it('recovers on the next tick after a poll fails (e.g. an expired session)', () => {
    // Baseline poll succeeds.
    flushPollTick(0, []);

    // Next tick's unread-count request fails (mirrors authInterceptor's
    // behaviour on an unrecoverable 401: it still errors the request after
    // redirecting to /login). Polling must not die permanently because of it.
    vi.advanceTimersByTime(2500);
    httpMock.expectOne('/api/notifications/unread-count').error(new ProgressEvent('error'), {
      status: 401,
      statusText: 'Unauthorized',
    });
    expect(service.unreadCount()).toBe(0);

    // A later tick (e.g. after logging back in) succeeds normally again.
    vi.advanceTimersByTime(2500);
    flushPollTick(3, [mkApiNotification({ is_read: false })]);
    expect(service.unreadCount()).toBe(3);
  });

  it('still emits a toast for a notification seen for the first time after a hard refresh', () => {
    // First "tab": establishes a baseline, then a notification arrives that
    // it never gets to see (e.g. the page is reloaded right after).
    const received: Notification[] = [];
    service.newNotifications$.subscribe((n) => received.push(n));
    flushPollTick(0, []);

    // Simulate a hard refresh: a brand-new service instance, backed by the
    // same localStorage, in a fresh TestBed.
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    TestBed.inject(UserService).currentUser.set(mkCurrentUser());
    service = TestBed.inject(NotificationService);
    httpMock = TestBed.inject(HttpTestingController);
    TestBed.flushEffects();
    vi.advanceTimersByTime(0);

    const receivedAfterReload: Notification[] = [];
    service.newNotifications$.subscribe((n) => receivedAfterReload.push(n));

    flushPollTick(1, [
      mkApiNotification({ id: 'n3', created_at: '2026-07-07T10:00:00Z', is_read: false }),
    ]);

    expect(receivedAfterReload.map((n) => n.id)).toEqual(['n3']);
  });

  it('does not poll while logged out, and stops polling once logged out', () => {
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [provideHttpClient(), provideHttpClientTesting()],
    });
    service = TestBed.inject(NotificationService);
    httpMock = TestBed.inject(HttpTestingController);
    TestBed.flushEffects();
    vi.advanceTimersByTime(0);

    // No user logged in yet: the first tick must not fire any request.
    httpMock.expectNone('/api/notifications/unread-count');
    vi.advanceTimersByTime(60000);
    httpMock.expectNone('/api/notifications/unread-count');

    const userService = TestBed.inject(UserService);
    userService.currentUser.set(mkCurrentUser());
    TestBed.flushEffects();
    vi.advanceTimersByTime(0);
    flushPollTick(1, [mkApiNotification({ is_read: false })]);
    expect(service.unreadCount()).toBe(1);

    // Logging out must stop the poll instead of letting it keep firing
    // (and 401ing) with no valid session.
    userService.clear();
    TestBed.flushEffects();
    vi.advanceTimersByTime(60000);
    httpMock.expectNone('/api/notifications/unread-count');
  });
});
