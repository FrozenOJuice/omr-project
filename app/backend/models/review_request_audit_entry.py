from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ReviewRequestAuditEntry(Base):
    __tablename__ = "review_request_audit_entries"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('resolved', 'rejected')",
            name="ck_review_request_audit_entries_event_type_valid",
        ),
        Index(
            "ix_review_request_audit_entries_review_request_id_created_at",
            "review_request_id",
            "created_at",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Deliberately not foreign keys: audit evidence must survive deletion of
    # the business record or actor it describes.
    review_request_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    # Null means the entry was recorded by an automated process, not a person.
    actor_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    changes: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.clock_timestamp(),
        nullable=False,
    )
