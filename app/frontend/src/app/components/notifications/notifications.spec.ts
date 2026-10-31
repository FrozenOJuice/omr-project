import { ComponentFixture, TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';
import { of } from 'rxjs';
import { vi } from 'vitest';
import { Notifications } from './notifications';
import { NotificationService } from '../../services/notification.service';
import { Notification } from '../../models/notification';

// Small, predictable dataset used across all tests.
// 7 notifications: 3 Re-grade (ids 1,3,5), 4 Processing (ids 2,4,6,7)
// Unread: ids 1, 2, 6  →  unreadCount = 3
const mockNotifications: Notification[] = [
  { id: '1', type: 'Re-grade',  severity: 'info', title: 'New re-grade request', course: 'COSC 320', courseId: null, subtitle: 'Q1', time: '9:00 AM',    createdAt: '2026-07-01T09:00:00Z', isRead: false, linkPath: '/regrade', linkQuery: null },
  { id: '2', type: 'Processing', severity: 'info', title: 'Batch job completed',  course: 'COSC 101', courseId: null, subtitle: 'Q2', time: '8:00 AM',    createdAt: '2026-07-01T08:00:00Z', isRead: false, linkPath: '/courses', linkQuery: null },
  { id: '3', type: 'Re-grade',  severity: 'info', title: 'New re-grade request', course: 'COSC 210', courseId: null, subtitle: 'Q3', time: '7:00 AM',    createdAt: '2026-07-01T07:00:00Z', isRead: true,  linkPath: '/regrade', linkQuery: null },
  { id: '4', type: 'Processing', severity: 'error', title: 'Batch job failed',     course: 'COSC 221', courseId: null, subtitle: 'Q4', time: 'Yesterday',  createdAt: '2026-06-30T12:00:00Z', isRead: true,  linkPath: '/courses', linkQuery: null },
  { id: '5', type: 'Re-grade',  severity: 'info', title: 'New re-grade request', course: 'COSC 340', courseId: null, subtitle: 'Q5', time: '2 days ago', createdAt: '2026-06-29T12:00:00Z', isRead: true,  linkPath: '/regrade', linkQuery: null },
  { id: '6', type: 'Processing', severity: 'info', title: 'Batch job completed',  course: 'COSC 301', courseId: null, subtitle: 'Q6', time: '3 days ago', createdAt: '2026-06-28T12:00:00Z', isRead: false, linkPath: '/courses', linkQuery: null },
  { id: '7', type: 'Processing', severity: 'info', title: 'Batch job completed',  course: 'COSC 404', courseId: null, subtitle: 'Q7', time: '4 days ago', createdAt: '2026-06-27T12:00:00Z', isRead: true,  linkPath: '/courses', linkQuery: null },
];

// A plain class mock — no test framework imports needed.
class MockNotificationService {
  wasGetAllCalled = false;
  getAll() {
    this.wasGetAllCalled = true;
    return of({ items: [...mockNotifications], total: mockNotifications.length });
  }
  markRead() {
    return of(void 0);
  }
  markAllRead() {
    return of(void 0);
  }
}

describe('Notifications', () => {
  let component: Notifications;
  let fixture: ComponentFixture<Notifications>;
  let mockService: MockNotificationService;

  beforeEach(async () => {
    mockService = new MockNotificationService();

    await TestBed.configureTestingModule({
      imports: [Notifications],
      providers: [provideRouter([]), { provide: NotificationService, useValue: mockService }],
    }).compileComponents();

    fixture = TestBed.createComponent(Notifications);
    component = fixture.componentInstance;
    vi.spyOn(TestBed.inject(Router), 'navigate').mockResolvedValue(true);
    fixture.detectChanges(); // triggers ngOnInit
    component.notifications = [...mockNotifications]; // ensure controlled test data
  });

  // ─── Loading data ────────────────────────────────────────────────────────────
  // These tests verify that the component talks to the service correctly on startup.

  it('should create the component', () => {
    // Basic sanity check — if this fails, something is wrong with the imports or providers.
    expect(component).toBeTruthy();
  });


  // ─── Filtering ───────────────────────────────────────────────────────────────
  // filteredNotifications is a getter that looks at activeFilter.
  // These tests make sure each filter chip produces the right subset.

  it('should show all notifications when the active filter is All', () => {
    component.setFilter('All');
    expect(component.filteredNotifications.length).toBe(7);
  });

  it('should show only unread notifications when the Unread filter is active', () => {
    component.setFilter('Unread');
    const result = component.filteredNotifications;
    // ids 1, 2, 6 are unread in our mock data
    expect(result.length).toBe(3);
    expect(result.every(n => !n.isRead)).toBe(true);
  });

  it('should show only Processing notifications when the Processing filter is active', () => {
    component.setFilter('Processing');
    const result = component.filteredNotifications;
    // ids 2, 4, 6, 7 are Processing
    expect(result.length).toBe(4);
    expect(result.every(n => n.type === 'Processing')).toBe(true);
  });

  it('should show only Re-grade notifications when the Re-grade filter is active', () => {
    component.setFilter('Re-grade');
    const result = component.filteredNotifications;
    // ids 1, 3, 5 are Re-grades
    expect(result.length).toBe(3);
    expect(result.every(n => n.type === 'Re-grade')).toBe(true);
  });

  it('should reset to page 1 when the filter changes', () => {
    // Prevents the user from being stranded on a page that no longer exists
    // after they switch filters.
    component.currentPage = 3;
    component.setFilter('Unread');
    expect(component.currentPage).toBe(1);
  });

  // ─── Counts ──────────────────────────────────────────────────────────────────
  // These getters drive the numbers shown in the filter chip labels (e.g. "Unread (3)").
  // They always count from the full notifications array, ignoring the active filter.

  it('should count unread notifications correctly', () => {
    expect(component.unreadCount).toBe(3);
  });

  it('should count Processing notifications correctly', () => {
    expect(component.processingCount).toBe(4);
  });

  it('should count Re-grade notifications correctly', () => {
    expect(component.regradeCount).toBe(3);
  });

  // ─── Sorting ─────────────────────────────────────────────────────────────────
  // filteredNotifications sorts by createdAt. Later timestamp = newer notification.

  it('should sort newest first by default (id 7 has the earliest createdAt, id 1 the latest)', () => {
    component.sortOrder = 'newest';
    const ids = component.filteredNotifications.map(n => n.id);
    expect(ids[0]).toBe('1');
    expect(ids[ids.length - 1]).toBe('7');
  });

  it('should sort oldest first when sortOrder is oldest', () => {
    component.sortOrder = 'oldest';
    const ids = component.filteredNotifications.map(n => n.id);
    expect(ids[0]).toBe('7');
    expect(ids[ids.length - 1]).toBe('1');
  });

  it('should reset to page 1 when the sort order changes', () => {
    component.currentPage = 2;
    component.onSortChange();
    expect(component.currentPage).toBe(1);
  });

  // ─── Pagination ──────────────────────────────────────────────────────────────
  // pagedNotifications slices filteredNotifications based on currentPage and pageSize.
  // With 7 notifications and pageSize 3: page 1 = 3 items, page 2 = 3, page 3 = 1.

  it('should return only pageSize notifications for page 1', () => {
    component.pageSize = 3;
    component.currentPage = 1;
    expect(component.pagedNotifications.length).toBe(3);
  });

  it('should return the correct notifications for page 2', () => {
    component.pageSize = 3;
    component.sortOrder = 'newest'; // ids returned: 1,2,3,4,5,6,7
    component.currentPage = 2;
    const ids = component.pagedNotifications.map(n => n.id);
    // Page 1 = [1,2,3], page 2 = [4,5,6]
    expect(ids).toEqual(['4', '5', '6']);
  });

  it('should return remaining notifications on the last page', () => {
    component.pageSize = 3;
    component.currentPage = 3;
    expect(component.pagedNotifications.length).toBe(1);
  });

  it('should calculate totalPages correctly', () => {
    component.pageSize = 3; // ceil(7/3) = 3
    expect(component.totalPages).toBe(3);

    component.pageSize = 7; // ceil(7/7) = 1
    expect(component.totalPages).toBe(1);

    component.pageSize = 4; // ceil(7/4) = 2
    expect(component.totalPages).toBe(2);
  });

  it('should increment currentPage when nextPage is called', () => {
    component.pageSize = 3;
    component.currentPage = 1;
    component.nextPage();
    expect(component.currentPage).toBe(2);
  });

  it('should not go past totalPages when nextPage is called on the last page', () => {
    component.pageSize = 3; // totalPages = 3
    component.currentPage = 3;
    component.nextPage();
    expect(component.currentPage).toBe(3);
  });

  it('should decrement currentPage when previousPage is called', () => {
    component.pageSize = 3;
    component.currentPage = 2;
    component.previousPage();
    expect(component.currentPage).toBe(1);
  });

  it('should not go below page 1 when previousPage is called on the first page', () => {
    component.currentPage = 1;
    component.previousPage();
    expect(component.currentPage).toBe(1);
  });

  it('should reset to page 1 when pageSize changes', () => {
    component.currentPage = 3;
    component.pageSize = 10;
    component.onPageSizeChange();
    expect(component.currentPage).toBe(1);
  });

  it('should clamp pageSize to 1 if set below 1', () => {
    component.pageSize = 0;
    component.onPageSizeChange();
    expect(component.pageSize).toBe(1);
  });

  // ─── Click-to-navigate / mark-read ─────────────────────────────────────────

  it('should mark an unread notification as read when opened', () => {
    const notification = { ...mockNotifications[0] };
    const spy = vi.spyOn(mockService, 'markRead');
    component.open(notification);
    expect(notification.isRead).toBe(true);
    expect(spy).toHaveBeenCalledWith('1');
  });

  it('should not call markRead again for an already-read notification', () => {
    const notification = { ...mockNotifications[2] }; // id 3, already read
    const spy = vi.spyOn(mockService, 'markRead');
    component.open(notification);
    expect(spy).not.toHaveBeenCalled();
  });

  // ─── Dismiss all ────────────────────────────────────────────────────────────

  it('should mark every notification as read and call markAllRead when dismissAll is called', () => {
    // Own deep copy so this mutation doesn't leak into other tests via the
    // shared mockNotifications objects.
    component.notifications = mockNotifications.map(n => ({ ...n }));
    const spy = vi.spyOn(mockService, 'markAllRead');

    component.dismissAll();

    expect(spy).toHaveBeenCalled();
    expect(component.notifications.every(n => n.isRead)).toBe(true);
  });

  it('should not call markAllRead when there are no unread notifications', () => {
    component.notifications = mockNotifications.map(n => ({ ...n, isRead: true }));
    const spy = vi.spyOn(mockService, 'markAllRead');

    component.dismissAll();

    expect(spy).not.toHaveBeenCalled();
  });
});
