import { Exam } from './exam.model';
import { AcademicTerm } from './academic-term.model';

export { formatAcademicPeriod } from './academic-term.model';

export type CourseSource = 'omr' | 'canvas';

export interface ApiCanvasCourseLink {
  canvas_course_id: string;
  last_synced_at: string;
  connection_status: 'connected' | 'disconnected';
}

export interface ApiCourse {
  id: string;
  name: string;
  academic_term_id: string;
  academic_term: AcademicTerm;
  academic_year_start: number;
  archived_at: string | null;
  archived_by_user_id?: string | null;
  retention_policy_id?: string | null;
  scanned_images_retention_until?: string | null;
  exam_records_retention_until?: string | null;
  scanned_images_purged_at?: string | null;
  exam_records_purged_at?: string | null;
  retention_processed_at?: string | null;
  created_by: string;
  created_at: string;
  updated_at: string;
  invite_link: string;
  invite_link_expires_at?: string | null;
  student_count: number;
  source?: CourseSource;
  canvas_link?: ApiCanvasCourseLink | null;
  can_manage_canvas: boolean;
}

export interface ApiEnrolledStudent {
  id: string;
  user_id: string | null;
  first_name: string;
  last_name: string;
  email: string;
  role: string;
  student_number: string | null;
  account_status: 'pending' | 'linked';
  invited_at: string | null;
  source: 'manual' | 'csv' | 'invite' | 'canvas';
  active: boolean;
}

export interface Student {
  id: string;
  userId: string | null;
  firstName: string;
  lastName: string;
  email: string;
  studentNumber: string | null;
  accountStatus: 'pending' | 'linked';
  invitedAt?: string | null;
  source: 'manual' | 'csv' | 'invite' | 'canvas';
  active: boolean;
}

export function apiEnrolledStudentToStudent(api: ApiEnrolledStudent): Student {
  return {
    id: api.id,
    userId: api.user_id,
    firstName: api.first_name,
    lastName: api.last_name,
    email: api.email,
    studentNumber: api.student_number,
    accountStatus: api.account_status,
    invitedAt: api.invited_at,
    source: api.source,
    active: api.active,
  };
}

export function studentFullName(student: Student): string {
  return `${student.firstName} ${student.lastName}`.trim();
}

export interface Course {
  id: string;
  code: string;
  name: string;
  students: number;
  studentList: Student[];
  academicTerm: AcademicTerm;
  academicYearStart: number;
  archivedAt: string | null;
  retentionProcessedAt?: string | null;
  exams: Exam[];
  inviteLink: string;
  inviteLinkExpiresAt?: string | null;
  source: CourseSource;
  canvasLink: ApiCanvasCourseLink | null;
  canManageCanvas: boolean;
}

export interface ExamComparisonStats {
  exam_id: string;
  exam_name: string;
  graded_count: number;
  mean_percentage: number | null;
  standard_deviation_percentage: number | null;
  median_percentage: number | null;
  mode_percentages: number[];
  highest_percentage: number | null;
  lowest_percentage: number | null;
  distribution: Record<string, number>;
}

export interface CourseStats extends Omit<ExamComparisonStats, 'exam_id' | 'exam_name'> {
  course_id: string;
  exam_count: number;
  exams: ExamComparisonStats[];
}

export interface ComparedCourse {
  id: string;
  name: string;
  academic_term_id: string;
  academic_term: AcademicTerm;
  academic_year_start: number;
  archived_at: string | null;
}

export interface ExamComparisonMapping {
  id: string;
  base_exam_id: string;
  base_exam_name: string;
  comparison_exam_id: string | null;
  comparison_exam_name: string | null;
}

export interface CourseComparison {
  id: string;
  base_course: ComparedCourse;
  comparison_course: ComparedCourse;
  mappings: ExamComparisonMapping[];
  created_at: string;
  updated_at: string;
}

// Courses are stored as a single "CODE - Full Name" string.
export function courseCodeFromName(name: string): string {
  const dashIndex = name.indexOf(' - ');
  return dashIndex !== -1 ? name.slice(0, dashIndex) : name;
}

export function courseBadgeFromCode(code: string): string {
  return code.match(/\d+[A-Z]?$/i)?.[0] ?? code.slice(0, 3).toUpperCase();
}

function courseNameWithoutCode(name: string): string {
  const dashIndex = name.indexOf(' - ');
  return dashIndex !== -1 ? name.slice(dashIndex + 3) : name;
}

export function apiCourseToCourse(api: ApiCourse): Course {
  return {
    id: api.id,
    code: courseCodeFromName(api.name),
    name: courseNameWithoutCode(api.name),
    students: api.student_count,
    studentList: [],
    academicTerm: api.academic_term,
    academicYearStart: api.academic_year_start,
    archivedAt: api.archived_at,
    retentionProcessedAt: api.retention_processed_at
      ?? api.exam_records_purged_at
      ?? api.scanned_images_purged_at
      ?? null,
    exams: [],
    inviteLink: api.invite_link,
    inviteLinkExpiresAt: api.invite_link_expires_at ?? null,
    source: api.source ?? 'omr',
    canvasLink: api.canvas_link ?? null,
    canManageCanvas: api.can_manage_canvas,
  };
}
