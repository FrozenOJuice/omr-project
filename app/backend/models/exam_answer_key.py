import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class ExamAnswerKey(Base):
    __tablename__ = "exam_answer_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    exam_template_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        ForeignKey("exam_templates.id", ondelete="SET NULL"), nullable=True
    )
    exam_version: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    answer_key: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scoring_rules: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    answer_key_path: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
