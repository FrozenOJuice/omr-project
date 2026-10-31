import type { ApiCourse } from './course.model';

export interface CanvasConnection {
  connected: boolean;
  user_name: string | null;
  login_id: string | null;
  connected_at: string | null;
  last_verified_at: string | null;
}

export interface CanvasCapabilities {
  configured: boolean;
  instructor_only: boolean;
  settings_url: string | null;
}

export interface CanvasCourse {
  id: string;
  name: string;
  course_code: string | null;
  imported: boolean;
  omr_course_id: string | null;
}

export interface CanvasStudent {
  id: string;
  name: string;
  login_id: string | null;
  sis_user_id: string | null;
  email?: string | null;
  sortable_name?: string | null;
}

export interface CanvasRoster {
  course_id: string;
  students: CanvasStudent[];
  skip_reasons: Record<string, number>;
}

export interface CanvasRosterSync {
  added: number;
  updated: number;
  removed: number;
  skipped: number;
  skip_reasons: Record<string, number>;
  active: number;
  last_synced_at: string;
}

export interface CanvasCourseImportResult {
  canvas_course_id: string;
  status: 'imported' | 'already_imported' | 'failed';
  course: ApiCourse | null;
  roster_sync: CanvasRosterSync | null;
  message: string | null;
}

export interface CanvasCourseImportResponse {
  results: CanvasCourseImportResult[];
}

export interface CanvasRosterInvitation {
  sent: number;
  already_invited: number;
  linked: number;
  failed: number;
  pending: number;
}

const rosterSkipLabels: Record<string, string> = {
  invalid_canvas_record: 'invalid Canvas record',
  missing_canvas_user_id: 'missing Canvas user ID',
  duplicate_canvas_user_id: 'duplicate Canvas user ID',
  missing_email: 'missing email',
  invalid_email: 'invalid email',
  missing_student_number: 'missing student number',
  invalid_student_number: 'invalid student number',
  invalid_name: 'invalid name',
  identity_conflict: 'conflicting student identity',
  invalid_student_data: 'invalid student data',
};

export function canvasRosterSkipSummary(reasons: Record<string, number>): string {
  return Object.entries(reasons)
    .map(([reason, count]) => `${count} ${rosterSkipLabels[reason] ?? reason.replaceAll('_', ' ')}`)
    .join(', ');
}

export interface CanvasAssignment {
  id: string;
  name: string;
  due_at: string | null;
  points_possible: number | null;
  published: boolean;
  html_url: string | null;
  linked_exam_id: string | null;
  available: boolean;
}

export interface CanvasGradeRelease {
  exam_id: string;
  assignment_id: string | null;
  assignment_name: string | null;
  eligible_count: number;
  skipped_count: number;
  skipped_reasons: Record<string, number>;
  target_locked: boolean;
  last_sent_count: number;
  last_skipped_count: number;
  last_failed_count: number;
  last_attempted_at: string | null;
  last_attempt_status: 'running' | 'completed' | 'partial' | 'failed' | null;
}
