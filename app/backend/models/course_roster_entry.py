import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class CourseRosterEntry(Base):
    __tablename__ = "course_roster_entries"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual', 'csv', 'invite', 'canvas')",
            name="ck_course_roster_entries_source_valid",
        ),
        UniqueConstraint("course_id", "email", name="uq_course_roster_entries_course_email"),
        UniqueConstraint(
            "course_id",
            "student_number",
            name="uq_course_roster_entries_course_student_number",
        ),
        UniqueConstraint(
            "course_id",
            "canvas_user_id",
            name="uq_course_roster_entries_course_canvas_user",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    email: Mapped[str] = mapped_column(String, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    student_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    canvas_user_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    @property
    def role(self) -> str:
        return "student"

    @property
    def account_status(self) -> str:
        return "linked" if self.user_id else "pending"
