import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class RetentionPolicySource(StrEnum):
    UBC_DEFAULT = "ubc_default"
    CUSTOM = "custom"


class RetentionPolicy(Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        UniqueConstraint("owner_user_id", name="uq_retention_policies_owner_user_id"),
        CheckConstraint(
            "scanned_image_retention_months BETWEEN 12 AND 72",
            name="ck_retention_policies_scanned_image_months",
        ),
        CheckConstraint(
            "exam_record_retention_months BETWEEN 12 AND 72",
            name="ck_retention_policies_exam_record_months",
        ),
        CheckConstraint(
            "source IN ('ubc_default', 'custom')",
            name="ck_retention_policies_source_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    scanned_image_retention_months: Mapped[int] = mapped_column(
        Integer,
        default=12,
        server_default="12",
        nullable=False,
    )
    exam_record_retention_months: Mapped[int] = mapped_column(
        Integer,
        default=12,
        server_default="12",
        nullable=False,
    )
    retain_anonymized_analytics: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String,
        default=RetentionPolicySource.UBC_DEFAULT.value,
        server_default=RetentionPolicySource.UBC_DEFAULT.value,
        nullable=False,
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
