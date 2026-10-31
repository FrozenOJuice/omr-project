import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { Notification, parseNotificationLinkQuery } from '../../models/notification';
import { NotificationService } from '../../services/notification.service';
import { LoadingSpinner } from '../../sub-components/loading-spinner/loading-spinner';

@Component({
  selector: 'app-notifications',
  imports: [FormsModule, LoadingSpinner],
  templateUrl: './notifications.html',
  styleUrl: './notifications.css',
})
export class Notifications implements OnInit {

  notifications: Notification[] = [];

  activeFilter = 'All';
  sortOrder = 'newest';
  currentPage = 1;
  pageSize = 10;
  isLoading = true;
  loadError = '';

  private notificationService = inject(NotificationService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  ngOnInit() {
    this.notificationService.getAll().subscribe({
      next: ({ items }) => {
        this.notifications = items;
        this.isLoading = false;
        this.cdr.detectChanges();
      },
      error: () => {
        this.loadError = 'Unable to load notifications.';
        this.isLoading = false;
        this.cdr.detectChanges();
      },
    });
  }

  get totalPages(): number {
    const size = Math.max(1, Number(this.pageSize) || 1);
    return Math.max(1, Math.ceil(this.filteredNotifications.length / size));
  }

  setFilter(filter: string) {
    this.activeFilter = filter;
    this.currentPage = 1;
  }

  onPageSizeChange() {
    const size = Math.floor(Number(this.pageSize) || 1);
    this.pageSize = Math.min(100, Math.max(1, size));
    this.currentPage = 1;
  }

  onSortChange() {
    this.currentPage = 1;
  }

  previousPage() {
    if (this.currentPage > 1) this.currentPage--;
  }

  nextPage() {
    if (this.currentPage < this.totalPages) this.currentPage++;
  }

  // Returns all notifications matching the active filter, sorted by sortOrder (full list, no paging)
  get filteredNotifications(): Notification[] {
    let list: Notification[];
    if (this.activeFilter === 'All') list = [...this.notifications];
    else if (this.activeFilter === 'Unread') list = this.notifications.filter(n => !n.isRead);
    else list = this.notifications.filter(n => n.type === this.activeFilter);

    return this.sortOrder === 'oldest'
      ? list.sort((a, b) => a.createdAt.localeCompare(b.createdAt))
      : list.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  // Returns only the notifications for the current page
  get pagedNotifications(): Notification[] {
    const size = Math.max(1, Number(this.pageSize) || 1);
    const start = (this.currentPage - 1) * size;
    return this.filteredNotifications.slice(start, start + size);
  }

  get unreadCount(): number {
    return this.notifications.filter(n => !n.isRead).length;
  }

  get processingCount(): number {
    return this.notifications.filter(n => n.type === 'Processing').length;
  }

  get regradeCount(): number {
    return this.notifications.filter(n => n.type === 'Re-grade').length;
  }

  open(notification: Notification) {
    if (!notification.isRead) {
      notification.isRead = true;
      this.notificationService.markRead(notification.id).subscribe();
    }
    if (notification.linkPath) {
      this.router.navigate([notification.linkPath], {
        queryParams: parseNotificationLinkQuery(notification.linkQuery),
      });
    }
  }

  dismiss(notification: Notification, event: Event) {
    event.stopPropagation();
    if (notification.isRead) return;
    notification.isRead = true;
    this.notificationService.markRead(notification.id).subscribe();
  }

  dismissAll() {
    if (this.unreadCount === 0) return;
    this.notificationService.markAllRead().subscribe(() => {
      this.notifications.forEach(n => n.isRead = true);
      this.cdr.detectChanges();
    });
  }
}
