import { ChangeDetectionStrategy, Component, OnDestroy, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Subscription } from 'rxjs';
import { NotificationService } from '../../services/notification.service';
import { Notification, parseNotificationLinkQuery } from '../../models/notification';

const AUTO_DISMISS_MS = 6000;

interface DismissTimer {
  timerId: ReturnType<typeof setTimeout> | null;
  remainingMs: number;
  startedAt: number;
}

@Component({
  selector: 'app-notification-toast',
  imports: [],
  templateUrl: './notification-toast.html',
  styleUrl: './notification-toast.css',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class NotificationToast implements OnDestroy {
  private notificationService = inject(NotificationService);
  private router = inject(Router);
  private sub: Subscription;

  // A toast that fires while the tab is backgrounded (or that's still on
  // screen when the tab is backgrounded) would otherwise auto-dismiss on a
  // real-time clock the user never saw tick down. These timers pause on
  // visibilitychange and resume with whatever time was left, so a toast is
  // guaranteed its full on-screen window once the tab is actually visible.
  private dismissTimers = new Map<string, DismissTimer>();
  private onVisibilityChange = () => {
    if (document.hidden) {
      this.pauseTimers();
    } else {
      this.resumeTimers();
    }
  };

  toasts = signal<Notification[]>([]);

  constructor() {
    // This component only exists while app.html's showMenu() is true (see
    // app.ts's menuRoutes) — if it gets destroyed/recreated (e.g. a route
    // outside that list, or a hard refresh), any toast the service emits
    // while it's gone is lost, since newNotifications$ is a plain Subject
    // with no replay buffer.
    this.sub = this.notificationService.newNotifications$.subscribe((notification) => {
      this.toasts.update((toasts) => [...toasts, notification]);
      this.dismissTimers.set(notification.id, { timerId: null, remainingMs: AUTO_DISMISS_MS, startedAt: 0 });
      if (!document.hidden) {
        this.scheduleDismiss(notification);
      }
    });
    document.addEventListener('visibilitychange', this.onVisibilityChange);
  }

  ngOnDestroy(): void {
    this.sub.unsubscribe();
    document.removeEventListener('visibilitychange', this.onVisibilityChange);
    this.dismissTimers.forEach((timer) => {
      if (timer.timerId !== null) clearTimeout(timer.timerId);
    });
  }

  open(notification: Notification): void {
    if (!notification.isRead) this.notificationService.markRead(notification.id).subscribe();
    this.dismiss(notification);
    if (notification.linkPath) {
      this.router.navigate([notification.linkPath], {
        queryParams: parseNotificationLinkQuery(notification.linkQuery),
      });
    }
  }

  dismiss(notification: Notification): void {
    const timer = this.dismissTimers.get(notification.id);
    if (timer?.timerId !== null && timer?.timerId !== undefined) clearTimeout(timer.timerId);
    this.dismissTimers.delete(notification.id);
    this.toasts.update((toasts) => toasts.filter((t) => t.id !== notification.id));
  }

  private scheduleDismiss(notification: Notification): void {
    const timer = this.dismissTimers.get(notification.id);
    if (!timer) return;
    timer.startedAt = Date.now();
    timer.timerId = setTimeout(() => this.dismiss(notification), timer.remainingMs);
  }

  private pauseTimers(): void {
    this.dismissTimers.forEach((timer) => {
      if (timer.timerId === null) return;
      clearTimeout(timer.timerId);
      timer.remainingMs -= Date.now() - timer.startedAt;
      timer.timerId = null;
    });
  }

  private resumeTimers(): void {
    this.toasts().forEach((notification) => {
      const timer = this.dismissTimers.get(notification.id);
      if (timer && timer.timerId === null) {
        this.scheduleDismiss(notification);
      }
    });
  }
}
