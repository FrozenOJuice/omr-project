from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ExamReleaseAuditEntry(Base):
    __tablename__ = "exam_release_audit_entries"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('released', 'closed')",
            name="ck_exam_release_audit_entries_event_type_valid",
        ),
        Index(
            "ix_exam_release_audit_entries_exam_id_created_at",
            "exam_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Deliberately not foreign keys: audit evidence must survive deletion of
    # the business record or actor it describes.
    exam_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Null means the entry was recorded by an automated process, not a person.
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        # Unlike now(), this is evaluated when the row is inserted rather than
        # when the transaction began, so row-lock serialization is reflected
        # in audit ordering.
        server_default=func.clock_timestamp(),
        nullable=False,
    )
