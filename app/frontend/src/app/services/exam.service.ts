import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ApiExam,
  ExamGrade,
  ExamReleaseAuditEntry,
  ExamScoreDistribution,
  ExamStats,
  GradeAuditEntry,
  IdentityAnnotations,
  QuestionAnnotation,
  UpdateGradePayload,
  VersionAnnotation,
} from '../models/exam.model';


@Injectable({ providedIn: 'root' })
export class ExamService {
  private http = inject(HttpClient);

  // Handles the handshake between the frontend and backend for exams

  listExamsByCourse(courseId: string): Observable<ApiExam[]> {
    return this.http.get<ApiExam[]>(`/api/exams/course/${courseId}`);
  }

  getExam(examId: string): Observable<ApiExam> {
    return this.http.get<ApiExam>(`/api/exams/${examId}`);
  }

  createExam(
    name: string,
    description: string | null,
    startTime: string | null,
    endTime: string | null,
    role: string,
    courseId: string,
    examTemplateId: string,
    canvasAssignmentId: string | null = null,
  ): Observable<ApiExam> {
    return this.http.post<ApiExam>('/api/exams', {
      name,
      description,
      start_time: startTime,
      end_time: endTime,
      role,
      course_id: courseId,
      exam_template_id: examTemplateId,
      canvas_assignment_id: canvasAssignmentId,
    });
  }

  deleteExam(examId: string): Observable<void> {
    return this.http.delete<void>(`/api/exams/${examId}`);
  }

  releaseExam(examId: string): Observable<ApiExam> {
    return this.http.post<ApiExam>(`/api/exams/${examId}/release`, {});
  }

  closeExam(examId: string): Observable<ApiExam> {
    return this.http.post<ApiExam>(`/api/exams/${examId}/close`, {});
  }

  // Renders the exam-specific sheet: the template's layout plus this exam's
  // name, course, and date/time. Requires the template to already be
  // registered with OMR (see ExamTemplateService.finalizeTemplate).
  generateExamPdf(examId: string): Observable<ApiExam> {
    return this.http.post<ApiExam>(`/api/exams/${examId}/generate-pdf`, {});
  }

  // Streamed through the backend rather than a presigned Garage URL, same
  // reasoning as ExamTemplateService.downloadPdf.
  downloadExamPdf(examId: string): Observable<Blob> {
    return this.http.get(`/api/exams/${examId}/download-pdf`, { responseType: 'blob' });
  }

  getReleaseHistory(examId: string): Observable<ExamReleaseAuditEntry[]> {
    return this.http.get<ExamReleaseAuditEntry[]>(`/api/exams/${examId}/release-history`);
  }

  updateExamTemplate(
    examId: string,
    examTemplateId: string,
    deleteAnswerKeys = false,
  ): Observable<ApiExam> {
    return this.http.patch<ApiExam>(`/api/exams/${examId}`, {
      exam_template_id: examTemplateId,
      delete_answer_keys: deleteAnswerKeys,
    });
  }

  updateExamSchedule(
    examId: string,
    startTime: string | null,
    endTime: string | null,
  ): Observable<ApiExam> {
    return this.http.patch<ApiExam>(`/api/exams/${examId}`, {
      start_time: startTime,
      end_time: endTime,
    });
  }

  getExamStats(examId: string): Observable<ExamStats> {
    return this.http.get<ExamStats>(`/api/exams/${examId}/stats`);
  }

  getExamScoreDistribution(examId: string): Observable<ExamScoreDistribution> {
    return this.http.get<ExamScoreDistribution>(`/api/exams/${examId}/score-distribution`);
  }

  exportExamResults(examId: string): Observable<Blob> {
    return this.http.get(`/api/exams/${examId}/export`, {
      responseType: 'blob',
    });
  }

  listExamGrades(examId: string): Observable<ExamGrade[]> {
    return this.http.get<ExamGrade[]>(`/api/exams/${examId}/grades`);
  }

  getGrade(gradeId: string): Observable<ExamGrade> {
    return this.http.get<ExamGrade>(`/api/grades/${gradeId}`);
  }

  updateGrade(gradeId: string, changes: UpdateGradePayload): Observable<ExamGrade> {
    return this.http.patch<ExamGrade>(`/api/grades/${gradeId}`, changes);
  }

  getGradeQuestionSnippet(gradeId: string, questionNumber: string): Observable<Blob> {
    return this.http.get(`/api/grades/${gradeId}/questions/${questionNumber}/snippet`, {
      responseType: 'blob',
    });
  }

  getGradeHistory(gradeId: string): Observable<GradeAuditEntry[]> {
    return this.http.get<GradeAuditEntry[]>(`/api/grades/${gradeId}/history`);
  }

  getGradePageAnnotations(gradeId: string, pageIndex: number): Observable<QuestionAnnotation[]> {
    return this.http.get<QuestionAnnotation[]>(`/api/grades/${gradeId}/pages/${pageIndex}/annotations`);
  }

  getGradePageImage(gradeId: string, pageIndex: number): Observable<Blob> {
    return this.http.get(`/api/grades/${gradeId}/pages/${pageIndex}/image`, {
      responseType: 'blob',
    });
  }

  getGradeIdentity(gradeId: string): Observable<IdentityAnnotations> {
    return this.http.get<IdentityAnnotations>(`/api/grades/${gradeId}/identity`);
  }

  getGradePageIdentity(gradeId: string, pageIndex: number): Observable<IdentityAnnotations> {
    return this.http.get<IdentityAnnotations>(`/api/grades/${gradeId}/pages/${pageIndex}/identity`);
  }

  getGradePageVersion(gradeId: string, pageIndex: number): Observable<VersionAnnotation> {
    return this.http.get<VersionAnnotation>(`/api/grades/${gradeId}/pages/${pageIndex}/version`);
  }
}
