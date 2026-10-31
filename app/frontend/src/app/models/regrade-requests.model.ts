export interface ApiReviewRequestBase {
    id: string;
    exam_grade_id: string;
    student_id: string;
    // Shared by every row created from the same multi-question submission.
    // Null for a single-question request, or one made before batching existed.
    batch_id: string | null;
    question_number: string;
    student_comment: string | null;
    status: string;
    instructor_response: string | null;
    current_score: number | null;
    proposed_score: number | null;
    // Staff's correct/incorrect decision for this question, applied to the
    // grade's question status when resolved.
    proposed_correct: boolean | null;
    created_at: string;
    resolved_at: string | null;
}

export interface ApiStudentReviewRequest extends ApiReviewRequestBase {
    course_id: string;
}

export interface ApiReviewRequest extends ApiReviewRequestBase {
    student_name: string;
    course_id: string;
    course_code: string;
    term: string;
    exam_name: string;
    max_score: number;
}

export interface ReviewRequestAuditEntry {
    id: string;
    review_request_id: string;
    actor_user_id: string | null;
    actor_name: string | null;
    event_type: 'resolved' | 'rejected';
    changes: Record<string, { before: unknown; after: unknown }>;
    created_at: string;
}
