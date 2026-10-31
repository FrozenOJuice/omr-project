import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  CreateExamAnswerKeyRequest,
  ExamAnswerKeyResponse,
  ExtractAnswerKeyScanBatchResponse,
  UpdateExamAnswerKeyRequest,
} from '../models/exam-answer-key.model';

@Injectable({ providedIn: 'root' })
export class ExamAnswerKeyService {
  private http = inject(HttpClient);

  // Handles the handshake between the frontend and backend for exam answer
  // keys (correct choices + grading rules per exam, optionally per version).
  // Routes mirror app/backend/routers/exam_answer_key_router.py — create/list
  // are nested under the exam; get/update/delete are under /answer-keys/{id}.

  createAnswerKey(examId: string, body: CreateExamAnswerKeyRequest): Observable<ExamAnswerKeyResponse> {
    return this.http.post<ExamAnswerKeyResponse>(`/api/exams/${examId}/answer-keys`, body);
  }

  listAnswerKeysByExam(examId: string): Observable<ExamAnswerKeyResponse[]> {
    return this.http.get<ExamAnswerKeyResponse[]>(`/api/exams/${examId}/answer-keys`);
  }

  extractAnswerKeyScan(
    examId: string,
    files: File[],
    questionCount: number,
  ): Observable<ExtractAnswerKeyScanBatchResponse> {
    const formData = new FormData();
    for (const file of files) formData.append('files', file, file.name);
    formData.append('question_count', String(questionCount));
    return this.http.post<ExtractAnswerKeyScanBatchResponse>(
      `/api/exams/${examId}/answer-keys/extract-scan`,
      formData,
    );
  }

  getAnswerKey(answerKeyId: string): Observable<ExamAnswerKeyResponse> {
    return this.http.get<ExamAnswerKeyResponse>(`/api/answer-keys/${answerKeyId}`);
  }

  updateAnswerKey(answerKeyId: string, body: UpdateExamAnswerKeyRequest): Observable<ExamAnswerKeyResponse> {
    return this.http.patch<ExamAnswerKeyResponse>(`/api/answer-keys/${answerKeyId}`, body);
  }

  deleteAnswerKey(answerKeyId: string): Observable<void> {
    return this.http.delete<void>(`/api/answer-keys/${answerKeyId}`);
  }
}
