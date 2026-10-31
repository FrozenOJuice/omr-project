from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "type IN ('grade_ready', 'grade_needs_review', 'review_request_created', "
            "'review_request_resolved', 'scan_failed', 'grading_failed')",
            name="ck_notifications_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    course_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    # Route target for deep-linking from the notification (e.g. "/courses"
    # with a raw querystring like "courseId=...&examId=..."). Kept as plain
    # strings rather than a single URL so the frontend can pass link_query
    # straight through URLSearchParams without re-parsing a joined string.
    link_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    link_query: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_read: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )
