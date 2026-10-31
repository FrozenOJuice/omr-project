import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { Subject, of } from 'rxjs';
import { vi } from 'vitest';
import { NotificationToast } from './notification-toast';
import { NotificationService } from '../../services/notification.service';
import { Notification } from '../../models/notification';

const mkNotification = (overrides: Partial<Notification> = {}): Notification => ({
  id: 'n1',
  type: 'Processing',
  severity: 'info',
  title: 'Your exam has been graded',
  course: 'COSC 320',
  courseId: 'c1',
  subtitle: 'Midterm 1',
  time: '9:00 AM',
  createdAt: '2026-07-07T09:00:00Z',
  isRead: false,
  linkPath: '/courses',
  linkQuery: 'courseId=c1&examId=e1',
  ...overrides,
});

describe('NotificationToast', () => {
  let component: NotificationToast;
  let fixture: ComponentFixture<NotificationToast>;
  let newNotifications: Subject<Notification>;
  let mockService: { newNotifications$: Subject<Notification>; markRead: ReturnType<typeof vi.fn> };

  beforeEach(async () => {
    newNotifications = new Subject<Notification>();
    mockService = {
      newNotifications$: newNotifications,
      markRead: vi.fn(() => of(void 0)),
    };

    await TestBed.configureTestingModule({
      imports: [NotificationToast],
      providers: [provideRouter([]), { provide: NotificationService, useValue: mockService }],
    }).compileComponents();

    fixture = TestBed.createComponent(NotificationToast);
    component = fixture.componentInstance;
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  it('should start with no toasts', () => {
    expect(component.toasts().length).toBe(0);
  });

  it('should add a toast when a new notification arrives', () => {
    newNotifications.next(mkNotification());
    expect(component.toasts().length).toBe(1);
  });

  it('should stack multiple toasts', () => {
    newNotifications.next(mkNotification({ id: 'n1' }));
    newNotifications.next(mkNotification({ id: 'n2' }));
    expect(component.toasts().map(t => t.id)).toEqual(['n1', 'n2']);
  });

  it('should mark read and navigate when a toast is opened', () => {
    const notification = mkNotification();
    newNotifications.next(notification);
    const router = TestBed.inject(Router);

    component.open(notification);

    expect(mockService.markRead).toHaveBeenCalledWith('n1');
    expect(router.navigate).toHaveBeenCalledWith(['/courses'], {
      queryParams: { courseId: 'c1', examId: 'e1' },
    });
    expect(component.toasts().length).toBe(0);
  });

  it('should not navigate when the toast has no link', () => {
    const notification = mkNotification({ isRead: true, linkPath: null, linkQuery: null });
    newNotifications.next(notification);
    const router = TestBed.inject(Router);

    component.open(notification);

    expect(mockService.markRead).not.toHaveBeenCalled();
    expect(router.navigate).not.toHaveBeenCalled();
  });

  it('should remove only the dismissed toast', () => {
    newNotifications.next(mkNotification({ id: 'n1' }));
    newNotifications.next(mkNotification({ id: 'n2' }));

    component.dismiss({ ...mkNotification({ id: 'n1' }) });

    expect(component.toasts().map(t => t.id)).toEqual(['n2']);
  });

  it('does not auto-dismiss a toast while the tab is hidden, and dismisses it after resuming', () => {
    vi.useFakeTimers();
    try {
      vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
      newNotifications.next(mkNotification({ id: 'n1' }));

      vi.advanceTimersByTime(60000);
      expect(component.toasts().map((t) => t.id)).toEqual(['n1']);

      vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
      document.dispatchEvent(new Event('visibilitychange'));

      vi.advanceTimersByTime(5999);
      expect(component.toasts().map((t) => t.id)).toEqual(['n1']);

      vi.advanceTimersByTime(1);
      expect(component.toasts().length).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });

  it('pauses the remaining time when the tab is hidden mid-countdown', () => {
    vi.useFakeTimers();
    try {
      newNotifications.next(mkNotification({ id: 'n1' }));

      vi.advanceTimersByTime(5000);
      vi.spyOn(document, 'hidden', 'get').mockReturnValue(true);
      document.dispatchEvent(new Event('visibilitychange'));

      // Fully "hidden" for way longer than the remaining 1s would've taken.
      vi.advanceTimersByTime(60000);
      expect(component.toasts().map((t) => t.id)).toEqual(['n1']);

      vi.spyOn(document, 'hidden', 'get').mockReturnValue(false);
      document.dispatchEvent(new Event('visibilitychange'));

      vi.advanceTimersByTime(999);
      expect(component.toasts().map((t) => t.id)).toEqual(['n1']);

      vi.advanceTimersByTime(1);
      expect(component.toasts().length).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
