import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { map, Observable } from 'rxjs';
import { ApiCourse, ApiEnrolledStudent, CourseComparison, CourseStats, ExamComparisonMapping, Student, apiEnrolledStudentToStudent } from '../models/course.model';
import { RetentionPolicy, RetentionPolicyDraft, RetentionPolicyStatus } from '../models/retention-policy.model';

export interface CsvUploadResult {
  enrolled: number;
  linked: number;
  pending: number;
  skipped: number;
  invited: number;
  invite_failed: number;
  warnings: string[];
  errors: string[];
}

export interface InviteResendResult {
  invited: number;
  invite_failed: number;
}

export interface InviteLinkResult {
  course_id: string;
  invite_link: string;
  invite_link_expires_at: string;
}

export interface AddStudentRequest {
  first_name: string;
  last_name: string;
  email: string;
  student_number: string;
}

export interface ArchiveCleanupResult {
  scanned_images: number;
  exam_records: number;
}

@Injectable({ providedIn: 'root' })
export class CourseService {
  private http = inject(HttpClient);

  // Handles the handshake between the front and backend for courses.

  listCourses(includeArchived = false): Observable<ApiCourse[]> {
    return this.http.get<ApiCourse[]>('/api/courses', {
      params: includeArchived ? { include_archived: true } : {},
    });
  }

  getCourse(courseId: string): Observable<ApiCourse> {
    return this.http.get<ApiCourse>(`/api/courses/${courseId}`);
  }

  getCourseStats(courseId: string): Observable<CourseStats> {
    return this.http.get<CourseStats>(`/api/courses/${courseId}/stats`);
  }

  listCourseComparisons(courseId: string): Observable<CourseComparison[]> {
    return this.http.get<CourseComparison[]>(`/api/courses/${courseId}/comparisons`);
  }

  createCourseComparison(courseId: string, comparisonCourseId: string): Observable<CourseComparison> {
    return this.http.post<CourseComparison>(`/api/courses/${courseId}/comparisons`, {
      comparison_course_id: comparisonCourseId,
    });
  }

  updateCourseComparison(courseId: string, comparisonId: string, mappings: Pick<ExamComparisonMapping, 'base_exam_id' | 'comparison_exam_id'>[]): Observable<CourseComparison> {
    return this.http.patch<CourseComparison>(`/api/courses/${courseId}/comparisons/${comparisonId}`, { mappings });
  }

  deleteCourseComparison(courseId: string, comparisonId: string): Observable<void> {
    return this.http.delete<void>(`/api/courses/${courseId}/comparisons/${comparisonId}`);
  }

  createCourse(code: string, name: string, academicTermId: string, academicYearStart: number): Observable<ApiCourse> {
    return this.http.post<ApiCourse>('/api/courses', {
      name: `${code} - ${name}`,
      academic_term_id: academicTermId,
      academic_year_start: academicYearStart,
    });
  }

  updateCourse(
    id: string,
    code: string,
    name: string,
    academicYearStart: number,
    academicTermId?: string,
  ): Observable<ApiCourse> {
    return this.http.patch<ApiCourse>(`/api/courses/${id}`, {
      name: `${code} - ${name}`,
      academic_year_start: academicYearStart,
      ...(academicTermId ? { academic_term_id: academicTermId } : {}),
    });
  }

  deleteCourse(id: string): Observable<void> {
    return this.http.delete<void>(`/api/courses/${id}`);
  }

    archiveCourse(id: string, confirmed: boolean, overrideActiveCourse = false): Observable<ApiCourse> {
      return this.http.post<ApiCourse>(`/api/courses/${id}/archive`, {
        confirmed,
        override_active_course: overrideActiveCourse,
      });
  }

  restoreCourse(id: string): Observable<void> {
    return this.http.post<void>(`/api/courses/${id}/restore`, {});
  }

  cleanupArchivedCourses(): Observable<ArchiveCleanupResult> {
    return this.http.post<ArchiveCleanupResult>('/api/admin/courses/cleanup-archives', {
      confirmed: true,
    });
  }

  getRetentionPolicy(): Observable<RetentionPolicyStatus> {
    return this.http.get<RetentionPolicyStatus>('/api/retention-policy');
  }

  upsertRetentionPolicy(policy: RetentionPolicyDraft): Observable<RetentionPolicy> {
    return this.http.put<RetentionPolicy>('/api/retention-policy', policy);
  }

  deleteRetentionPolicy(): Observable<void> {
    return this.http.delete<void>('/api/retention-policy');
  }

  uploadStudentsCsv(courseId: string, file: File): Observable<CsvUploadResult> {
    const formData = new FormData();
    formData.append('file', file);
    return this.http.post<CsvUploadResult>(`/api/courses/${courseId}/students/upload-csv`, formData);
  }

  resendInvites(courseId: string): Observable<InviteResendResult> {
    return this.http.post<InviteResendResult>(
      `/api/courses/${courseId}/students/resend-invites`,
      null,
    );
  }

  addStudent(courseId: string, student: AddStudentRequest): Observable<Student> {
    return this.http.post<ApiEnrolledStudent>(`/api/courses/${courseId}/students`, student).pipe(
      map(apiEnrolledStudentToStudent),
    );
  }

  unenrollStudent(courseId: string, studentId: string): Observable<void> {
    return this.http.delete<void>(`/api/courses/${courseId}/students/${studentId}`);
  }

  promoteStudent(courseId: string, studentId: string): Observable<void> {
    return this.http.post<void>(`/api/courses/${courseId}/students/${studentId}/promote`, {});
  }

  regenerateInviteLink(courseId: string): Observable<InviteLinkResult> {
    return this.http.post<InviteLinkResult>(`/api/courses/${courseId}/regenerate-link`, {});
  }

  joinCourse(inviteLink: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`/api/students/join/${inviteLink}`, {});
  }

  getCourseStudents(courseId: string): Observable<Student[]> {
    return this.http.get<ApiEnrolledStudent[]>(`/api/courses/${courseId}/students`).pipe(
      map(students => students.map(apiEnrolledStudentToStudent)),
    );
  }

}
