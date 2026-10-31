from datetime import datetime
import uuid

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class CanvasGradeReleaseAttempt(Base):
    __tablename__ = "canvas_grade_release_attempts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name="ck_canvas_grade_release_attempts_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canvas_grade_release_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvas_grade_releases.id", ondelete="CASCADE"), nullable=False
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String, default="running", nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CanvasGradeReleaseRecipient(Base):
    __tablename__ = "canvas_grade_release_recipients"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_canvas_grade_release_recipients_status",
        ),
        UniqueConstraint(
            "attempt_id",
            "canvas_user_id",
            name="uq_canvas_grade_release_recipients_attempt_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvas_grade_release_attempts.id", ondelete="CASCADE"),
        nullable=False,
    )
    canvas_user_id: Mapped[str] = mapped_column(String, nullable=False)
    percentage: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[str] = mapped_column(String, default="pending", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
