from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, FLOAT, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ExamGrade(Base):
    __tablename__ = "exam_grades"
    __table_args__ = (
        UniqueConstraint("omr_marking_id", name="uq_exam_grades_omr_marking_id"),
        CheckConstraint(
            "status IN ('graded', 'needs_review')",
            name="ck_exam_grades_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    omr_marking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("omr_markings.id", ondelete="CASCADE"),
        nullable=False,
    )
    exam_answer_key_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_answer_keys.id", ondelete="CASCADE"),
        nullable=False,
    )
    question_results: Mapped[dict] = mapped_column(JSONB, nullable=False)
    total_score: Mapped[float] = mapped_column(FLOAT, nullable=False)
    max_score: Mapped[float] = mapped_column(FLOAT, nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set only when status="graded": a version mismatch or unresolved student
    # name leaves this null and the exam flagged for manual review instead.
    student_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        String, default="graded", server_default="graded", nullable=False
    )
    # Comma-separated reason codes (e.g. "version_not_recognized,name_no_match")
    # set when status="needs_review".
    flag_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    graded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
