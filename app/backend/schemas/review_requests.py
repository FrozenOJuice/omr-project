from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class ReviewStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    REJECTED = "rejected"


class ReviewResolutionStatus(StrEnum):
    RESOLVED = "resolved"
    REJECTED = "rejected"


class CreateReviewRequestRequest(BaseModel):
    # More than one question here creates one row per question, all sharing
    # a batch_id, so staff see and resolve them together as one request.
    question_numbers: list[str] = Field(min_length=1)
    student_comment: str | None = None
    # The score the student thinks they should have gotten for each question,
    # keyed by question_number. A question in question_numbers with no entry
    # here just has no specific proposal. Each value is bounded by that
    # question's own max_score, checked in
    # repositories.review_requests.create_review_request.
    proposed_scores: dict[str, float] = Field(default_factory=dict)


class UpdateReviewRequestRequest(BaseModel):
    # Reopening a resolved or rejected request needs its own audited flow,
    # so this endpoint only records the initial decision.
    status: ReviewResolutionStatus
    # Feedback for the student, shared across every question in the batch.
    # Required either way so a decision is never recorded silently.
    instructor_response: str
    # Staff's correct/incorrect decision for each question, keyed by
    # question_number, applied to the grade's question_results (see
    # repositories.review_requests._apply_grade_adjustment_on_resolve). Every
    # question in the batch must have an entry when status is "resolved";
    # ignored entirely when rejecting, since a rejection doesn't touch the
    # grade.
    proposed_correct: dict[str, bool] = Field(default_factory=dict)
    # Optional per-question score override, keyed by question_number, for
    # cases the simple correct-is-full-credit / incorrect-is-zero-credit
    # default doesn't capture (e.g. partial credit). Each value is bounded by
    # that question's own max_score, checked in
    # repositories.review_requests._apply_grade_adjustment_on_resolve.
    proposed_scores: dict[str, float] = Field(default_factory=dict)


class ReviewRequestResponse(BaseModel):
    id: UUID
    exam_grade_id: UUID
    student_id: UUID
    # Shared by every row created from the same submission. None for a
    # request made before batching existed, or a single-question request.
    batch_id: UUID | None
    question_number: str
    student_comment: str | None
    status: str
    instructor_response: str | None
    current_score: float | None
    proposed_score: float | None
    proposed_correct: bool | None
    created_at: datetime
    resolved_at: datetime | None

    model_config = {"from_attributes": True}


class ReviewRequestStudentResponse(ReviewRequestResponse):
    course_id: UUID


class ReviewRequestEnrichedResponse(ReviewRequestResponse):
    student_name: str
    course_id: UUID
    course_code: str
    term: str
    exam_name: str
    max_score: float


class ReviewRequestAuditEntryResponse(BaseModel):
    id: UUID
    review_request_id: UUID
    actor_user_id: UUID | None
    actor_name: str | None
    event_type: str
    changes: dict
    created_at: datetime
