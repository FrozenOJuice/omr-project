import uuid
from typing import Optional

from sqlalchemy import CheckConstraint, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'completed', 'failed')",
            name="ck_scans_status_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    exam_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True
    )
    uploader_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    path: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=True)
    # Groups scans produced by splitting a single batch upload into one Scan
    # per exam. Null for scans predating batch-split support.
    batch_id: Mapped[Optional[uuid.UUID]] = mapped_column(nullable=True, index=True)
    batch_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # The scanId the OMR service issues from POST /scan, once preprocessed.
    omr_scan_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The OMR job id for an in-flight batch upload (POST /job/scan/pdf), set
    # on the seed scan row while OMR preprocesses it. Used to proxy live
    # progress to the frontend; irrelevant once the batch is materialized.
    omr_job_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(
        String,
        default="pending",
        server_default="pending",
        nullable=False,
    )
    # Set together when status is set to "failed", so staff can tell a
    # skewed/low-quality scan or a missing/extra page apart from a config or
    # connectivity problem, instead of an undifferentiated "failed". See
    # services/scan_processing.py's failure classification.
    failure_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    failure_detail: Mapped[Optional[str]] = mapped_column(String, nullable=True)
