from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ReviewRequest(Base):
    __tablename__ = "review_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'resolved', 'rejected')",
            name="ck_review_requests_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exam_grade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_grades.id"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Rows submitted together in one multi-question request share a batch_id,
    # so staff can view and resolve them as one request instead of several.
    # NULL for a single-question request.
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    question_number: Mapped[str] = mapped_column(String, nullable=False)
    student_comment: Mapped[str] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String,
        default="pending",
        server_default="pending",
        nullable=False,
    )
    instructor_response: Mapped[str] = mapped_column(String, nullable=True)
    current_score: Mapped[float] = mapped_column(Float, nullable=True)
    proposed_score: Mapped[float] = mapped_column(Float, nullable=True)
    # Staff's correct/incorrect decision for this question, applied to the
    # grade's question_results on resolve. See
    # repositories.review_requests._apply_grade_adjustment_on_resolve.
    proposed_correct: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
