from datetime import datetime
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class CanvasGradeRelease(Base):
    __tablename__ = "canvas_grade_releases"
    __table_args__ = (
        UniqueConstraint("exam_id", name="uq_canvas_grade_releases_exam"),
        UniqueConstraint(
            "canvas_assignment_link_id",
            name="uq_canvas_grade_releases_assignment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    exam_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("exams.id", ondelete="CASCADE"), nullable=False
    )
    canvas_assignment_link_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("canvas_assignment_links.id", ondelete="CASCADE"),
        nullable=False,
    )
    last_sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_skipped_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_failed_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    first_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
