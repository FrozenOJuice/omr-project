import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ExamTemplate(Base):
    __tablename__ = "exam_templates"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    question_config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    sections: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    total_questions: Mapped[int] = mapped_column(Integer, nullable=False)
    # Identifies a server-side blueprint (e.g. "ubco_100") whose physical sheet
    # layout is a fixed, hand-made OMR template rather than one generated from
    # question_config. Null for custom templates.
    blueprint: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    # UBCO_100_BLUEPRINT only: treat the sheet's physical Q1 bubble row as a
    # version selector (A/B/C/D/E) instead of a graded question, since the
    # fixed hand-made template has no dedicated version field of its own.
    version_from_q1: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    n_versions: Mapped[int] = mapped_column(Integer, default=4, server_default="4", nullable=False)
    omr_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("omr_templates.id"), nullable=True
    )
    generated_pdf_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
