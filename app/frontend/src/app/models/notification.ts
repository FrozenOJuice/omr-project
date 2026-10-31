export type ApiNotificationType =
  | 'grade_ready'
  | 'grade_needs_review'
  | 'review_request_created'
  | 'review_request_resolved'
  | 'scan_failed'
  | 'grading_failed';

export interface ApiNotification {
  id: string;
  type: ApiNotificationType;
  title: string;
  body: string | null;
  course_id: string | null;
  course_label: string | null;
  link_path: string | null;
  link_query: string | null;
  is_read: boolean;
  created_at: string;
}

export interface ApiNotificationList {
  items: ApiNotification[];
  total: number;
  page: number;
  page_size: number;
}

// Display bucket the notifications page filters/groups by. Re-grade covers
// the review-request lifecycle; Processing covers grading and scan pipeline
// events (grade ready/needs review, scan/grading failures).
export type NotificationDisplayType = 'Re-grade' | 'Processing';

// Drives toast styling (icon/color) — 'error' for pipeline failures, 'info' otherwise.
export type NotificationSeverity = 'error' | 'info';

export interface Notification {
  id: string;
  type: NotificationDisplayType;
  severity: NotificationSeverity;
  title: string;
  course: string;
  courseId: string | null;
  subtitle: string;
  time: string;
  createdAt: string;
  isRead: boolean;
  linkPath: string | null;
  linkQuery: string | null;
}

// Shared by the notifications list and the toast stack, both of which
// navigate to a notification's linkPath with its linkQuery as query params.
export function parseNotificationLinkQuery(linkQuery: string | null): Record<string, string> {
  if (!linkQuery) return {};
  return Object.fromEntries(new URLSearchParams(linkQuery));
}
