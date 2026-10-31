from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, FLOAT, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class GradeAuditEntry(Base):
    __tablename__ = "grade_audit_entries"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('initial_grade', 'manual_correction')",
            name="ck_grade_audit_entries_event_type_valid",
        ),
        Index(
            "ix_grade_audit_entries_exam_grade_id_created_at",
            "exam_grade_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exam_grade_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exam_grades.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Null means the entry was recorded by automated OMR grading, not a person.
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    previous_total_score: Mapped[Optional[float]] = mapped_column(FLOAT, nullable=True)
    new_total_score: Mapped[float] = mapped_column(FLOAT, nullable=False)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
