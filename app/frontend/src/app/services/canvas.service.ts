import { HttpClient } from '@angular/common/http';
import { inject, Injectable } from '@angular/core';
import { Observable } from 'rxjs';
import {
  CanvasConnection,
  CanvasCapabilities,
  CanvasAssignment,
  CanvasCourse,
  CanvasGradeRelease,
  CanvasRoster,
  CanvasRosterInvitation,
  CanvasRosterSync,
  CanvasCourseImportResponse,
} from '../models/canvas.model';
import {
  ExamGrade,
  IdentityAnnotations,
  QuestionAnnotation,
  VersionAnnotation,
} from '../models/exam.model';

@Injectable({ providedIn: 'root' })
export class CanvasService {
  private http = inject(HttpClient);

  getCapabilities(): Observable<CanvasCapabilities> {
    return this.http.get<CanvasCapabilities>('/api/canvas/capabilities');
  }

  connect(accessToken: string): Observable<CanvasConnection> {
    return this.http.post<CanvasConnection>('/api/canvas/connection', {
      access_token: accessToken,
    });
  }

  getConnection(): Observable<CanvasConnection> {
    return this.http.get<CanvasConnection>('/api/canvas/connection');
  }

  disconnect(): Observable<void> {
    return this.http.delete<void>('/api/canvas/connection');
  }

  getCourses(): Observable<CanvasCourse[]> {
    return this.http.get<CanvasCourse[]>('/api/canvas/courses');
  }

  importCourses(courseIds: string[]): Observable<CanvasCourseImportResponse> {
    return this.http.post<CanvasCourseImportResponse>('/api/canvas/courses/import', {
      course_ids: courseIds,
    });
  }

  getRoster(courseId: string): Observable<CanvasRoster> {
    return this.http.get<CanvasRoster>(`/api/canvas/courses/${courseId}/students`);
  }

  syncRoster(courseId: string): Observable<CanvasRosterSync> {
    return this.http.post<CanvasRosterSync>(
      `/api/canvas/imported-courses/${courseId}/roster/sync`,
      {},
    );
  }

  invitePendingStudents(courseId: string): Observable<CanvasRosterInvitation> {
    return this.http.post<CanvasRosterInvitation>(
      `/api/canvas/imported-courses/${courseId}/roster/invite-pending`,
      {},
    );
  }

  inviteStudent(courseId: string, rosterEntryId: string): Observable<CanvasRosterInvitation> {
    return this.http.post<CanvasRosterInvitation>(
      `/api/canvas/imported-courses/${courseId}/roster/${rosterEntryId}/invite`,
      {},
    );
  }

  getAssignments(courseId: string): Observable<CanvasAssignment[]> {
    return this.http.get<CanvasAssignment[]>(
      `/api/canvas/imported-courses/${courseId}/assignments`,
    );
  }

  linkExamAssignment(examId: string, assignmentId: string): Observable<CanvasGradeRelease> {
    return this.http.put<CanvasGradeRelease>(`/api/canvas/exams/${examId}/canvas-assignment`, {
      assignment_id: assignmentId,
    });
  }

  unlinkExamAssignment(examId: string): Observable<CanvasGradeRelease> {
    return this.http.delete<CanvasGradeRelease>(`/api/canvas/exams/${examId}/canvas-assignment`);
  }

  getGradeRelease(examId: string): Observable<CanvasGradeRelease> {
    return this.http.get<CanvasGradeRelease>(`/api/canvas/exams/${examId}/grade-release`);
  }

  releaseGrades(examId: string): Observable<CanvasGradeRelease> {
    return this.http.post<CanvasGradeRelease>(`/api/canvas/exams/${examId}/grade-release`, {});
  }

  getStudentResult(accessToken: string): Observable<ExamGrade> {
    return this.http.post<ExamGrade>('/api/canvas/student-results/access', {
      access_token: accessToken,
    });
  }

  getStudentResultIdentity(accessToken: string): Observable<IdentityAnnotations> {
    return this.http.post<IdentityAnnotations>('/api/canvas/student-results/identity', {
      access_token: accessToken,
    });
  }

  getStudentResultPageAnnotations(
    accessToken: string,
    pageIndex: number,
  ): Observable<QuestionAnnotation[]> {
    return this.http.post<QuestionAnnotation[]>(
      `/api/canvas/student-results/pages/${pageIndex}/annotations`,
      { access_token: accessToken },
    );
  }

  getStudentResultPageIdentity(
    accessToken: string,
    pageIndex: number,
  ): Observable<IdentityAnnotations> {
    return this.http.post<IdentityAnnotations>(
      `/api/canvas/student-results/pages/${pageIndex}/identity`,
      { access_token: accessToken },
    );
  }

  getStudentResultPageVersion(
    accessToken: string,
    pageIndex: number,
  ): Observable<VersionAnnotation> {
    return this.http.post<VersionAnnotation>(
      `/api/canvas/student-results/pages/${pageIndex}/version`,
      { access_token: accessToken },
    );
  }

  getStudentResultPageImage(accessToken: string, pageIndex: number): Observable<Blob> {
    return this.http.post(
      `/api/canvas/student-results/pages/${pageIndex}/image`,
      { access_token: accessToken },
      { responseType: 'blob' },
    );
  }
}
