import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  CreateExamTemplateRequest,
  ExamTemplateResponse,
  ExamTemplateUsageResponse,
  UpdateExamTemplateRequest,
} from '../models/exam-template.model';

@Injectable({ providedIn: 'root' })
export class ExamTemplateService {
  private http = inject(HttpClient);

  // Handles the handshake between the frontend and backend for exam templates.
  // Templates are reusable layouts (no exam link) — routes mirror
  // app/backend/routers/exam_template_router.py.

  createTemplate(body: CreateExamTemplateRequest): Observable<ExamTemplateResponse> {
    return this.http.post<ExamTemplateResponse>('/api/exam-templates', body);
  }

  // UR2.8: server-side "Standard UBC 100Q" blueprint (no request body).
  createUbco100Template(
    versionFromQ1?: boolean,
    name?: string,
    nVersions?: number,
  ): Observable<ExamTemplateResponse> {
    const versionFromQ1Param = versionFromQ1 ? '&version_from_q1=true' : '';
    const versionCountParam = versionFromQ1 && nVersions !== undefined
      ? `&n_versions=${nVersions}`
      : '';
    const nameParam = name && name.trim() ? `&name=${encodeURIComponent(name.trim())}` : '';
    return this.http.post<ExamTemplateResponse>(
      `/api/exam-templates?blueprint=ubco_100${versionFromQ1Param}${versionCountParam}${nameParam}`,
      null,
    );
  }

  listTemplates(includeArchived = false): Observable<ExamTemplateResponse[]> {
    const archivedParam = includeArchived ? '?include_archived=true' : '';
    return this.http.get<ExamTemplateResponse[]>(`/api/exam-templates${archivedParam}`);
  }

  listMyTemplates(includeArchived = false): Observable<ExamTemplateResponse[]> {
    const archivedParam = includeArchived ? '?include_archived=true' : '';
    return this.http.get<ExamTemplateResponse[]>(`/api/exam-templates/me${archivedParam}`);
  }

  getTemplate(templateId: string): Observable<ExamTemplateResponse> {
    return this.http.get<ExamTemplateResponse>(`/api/exam-templates/${templateId}`);
  }

  getTemplateUsage(templateId: string): Observable<ExamTemplateUsageResponse> {
    return this.http.get<ExamTemplateUsageResponse>(`/api/exam-templates/${templateId}/usage`);
  }

  updateTemplate(templateId: string, body: UpdateExamTemplateRequest): Observable<ExamTemplateResponse> {
    return this.http.patch<ExamTemplateResponse>(`/api/exam-templates/${templateId}`, body);
  }

  deleteTemplate(templateId: string, force = false): Observable<void> {
    const forceParam = force ? '?force=true' : '';
    return this.http.delete<void>(`/api/exam-templates/${templateId}${forceParam}`);
  }

  archiveTemplate(templateId: string): Observable<ExamTemplateResponse> {
    return this.http.post<ExamTemplateResponse>(
      `/api/exam-templates/${templateId}/archive`,
      null,
    );
  }

  restoreTemplate(templateId: string): Observable<ExamTemplateResponse> {
    return this.http.post<ExamTemplateResponse>(
      `/api/exam-templates/${templateId}/restore`,
      null,
    );
  }

  // Backend streams the blank bubble-sheet PDF bytes; fetched as a blob so
  // the auth interceptor attaches the Bearer token.
  downloadPdf(templateId: string): Observable<Blob> {
    return this.http.get(`/api/exam-templates/${templateId}/download-pdf`, { responseType: 'blob' });
  }

  // Single-page front-page render for the in-app preview, computed fresh
  // from the template's current question_config rather than the stored PDF.
  previewPdf(templateId: string): Observable<Blob> {
    return this.http.get(`/api/exam-templates/${templateId}/preview-pdf`, { responseType: 'blob' });
  }

  // Renders the blank bubble-sheet PDF + scan template for a saved template.
  // Safe to call again later to regenerate after question_config changes.
  generatePdf(templateId: string): Observable<ExamTemplateResponse> {
    return this.http.post<ExamTemplateResponse>(`/api/exam-templates/${templateId}/generate`, null);
  }

  // Registers the generated sheet layout with OMR so scans can be extracted.
  finalizeTemplate(templateId: string): Observable<ExamTemplateResponse> {
    return this.http.post<ExamTemplateResponse>(`/api/exam-templates/${templateId}/finalize`, null);
  }
}
