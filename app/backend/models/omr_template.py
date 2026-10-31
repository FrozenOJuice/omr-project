from datetime import datetime
import uuid
from typing import Optional

from sqlalchemy import DateTime, Float, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class OMRTemplate(Base):
    __tablename__ = "omr_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    # Garage object keys for the durable source JSON (already-populated by exam_generator).
    scan_template_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mark_template_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # Opaque IDs the OMR service assigns once that JSON is POSTed to it via
    # /template/preprocess and /template/mark. Needed to reference this template
    # in later /scan and /mark calls; unrelated to the storage keys above.
    preprocess_template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mark_template_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # The DPI this template's anchor/binarization tuning is calibrated
    # against, as sent to the OMR service's /template/preprocess (see
    # exam_generator.NATIVE_DPI). Null for templates created before this
    # column existed, or ones (like the hand-made UBC template) with no
    # recorded calibration DPI.
    native_dpi: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
