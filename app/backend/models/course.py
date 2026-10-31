from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from core.settings import settings
from db.session import Base
from models.canvas_course_link import CanvasCourseLink

if TYPE_CHECKING:
    from models.academic_term import AcademicTerm


def new_invite_link_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(
        seconds=settings.course_invite_expire_seconds
    )


class CourseSource(StrEnum):
    OMR = "omr"
    CANVAS = "canvas"


class Course(Base):
    __tablename__ = "courses"
    __table_args__ = (
        CheckConstraint(
            "source IN ('omr', 'canvas')",
            name="ck_courses_source_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    academic_term_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("academic_terms.id", ondelete="RESTRICT"),
        nullable=False,
    )
    academic_year_start: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=lambda: datetime.now(timezone.utc).year,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    archived_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("retention_policies.id", ondelete="SET NULL"),
        nullable=True,
    )
    retention_policy_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    scanned_images_retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    exam_records_retention_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    scanned_images_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exam_records_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retention_processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retained_analytics: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    invite_link: Mapped[str] = mapped_column(String, unique=True, nullable=False, default=lambda: uuid.uuid4().hex[:8])
    invite_link_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=new_invite_link_expiry,
        # ORM inserts use the configurable Python default above; this static
        # fallback only applies to inserts that bypass the ORM (raw SQL,
        # bulk_insert_mappings) so the NOT NULL constraint can't be violated.
        server_default=text("now() + interval '7 days'"),
    )
    source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=CourseSource.OMR.value,
        server_default=CourseSource.OMR.value,
    )
    canvas_link: Mapped[CanvasCourseLink | None] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="selectin",
        uselist=False,
    )
    academic_term: Mapped["AcademicTerm"] = relationship(
        "AcademicTerm",
        lazy="selectin",
    )
