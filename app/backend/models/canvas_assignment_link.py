from datetime import datetime
import uuid

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class CanvasAssignmentLink(Base):
    __tablename__ = "canvas_assignment_links"
    __table_args__ = (
        UniqueConstraint(
            "course_id",
            "canvas_assignment_id",
            name="uq_canvas_assignment_links_course_assignment",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        nullable=False,
    )
    canvas_assignment_id: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    points_possible: Mapped[float | None] = mapped_column(Float)
    published: Mapped[bool] = mapped_column(Boolean, nullable=False)
    html_url: Mapped[str | None] = mapped_column(String)
