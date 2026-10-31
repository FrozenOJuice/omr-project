import { inject, Injectable } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import {
  ApiReviewRequest,
  ApiStudentReviewRequest,
  ReviewRequestAuditEntry,
} from '../models/regrade-requests.model';

export interface CreateReviewRequestPayload {
  // More than one question here creates one row per question, all sharing
  // a batch_id so staff see and resolve them together.
  question_numbers: string[];
  student_comment?: string | null;
  // The score proposed for each question, keyed by question_number. A
  // question in question_numbers with no entry here just has no specific
  // proposal.
  proposed_scores?: Record<string, number>;
}

export interface UpdateReviewRequestPayload {
  status: 'resolved' | 'rejected';
  instructor_response: string;
  // Staff's correct/incorrect decision for each question, keyed by
  // question_number. Every question in the batch must have an entry when
  // status is 'resolved'.
  proposed_correct?: Record<string, boolean>;
  // Optional per-question score override, keyed by question_number.
  proposed_scores?: Record<string, number>;
}

@Injectable({ providedIn: 'root' })
export class ReviewRequestService {
  private http = inject(HttpClient);

  createReviewRequest(gradeId: string, payload: CreateReviewRequestPayload): Observable<ApiStudentReviewRequest[]> {
    return this.http.post<ApiStudentReviewRequest[]>(`/api/grades/${gradeId}/review-requests`, payload);
  }

  listReviewRequests(): Observable<ApiReviewRequest[]> {
    return this.http.get<ApiReviewRequest[]>('/api/review-requests');
  }

  listMyReviewRequests(): Observable<ApiStudentReviewRequest[]> {
    return this.http.get<ApiStudentReviewRequest[]>('/api/review-requests/me');
  }

  getReviewRequestHistory(id: string): Observable<ReviewRequestAuditEntry[]> {
    return this.http.get<ReviewRequestAuditEntry[]>(`/api/review-requests/${id}/history`);
  }

  // Returns every row in the target's batch (just the one row for a
  // single-question request), not the enriched shape listReviewRequests
  // returns: the caller merges these into its already-enriched local rows.
  updateReviewRequest(id: string, payload: UpdateReviewRequestPayload): Observable<ApiStudentReviewRequest[]> {
    return this.http.patch<ApiStudentReviewRequest[]>(`/api/review-requests/${id}`, payload);
  }
}
