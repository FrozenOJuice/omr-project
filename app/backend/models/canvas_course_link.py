from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
import uuid

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base

if TYPE_CHECKING:
    from models.course import Course


class CanvasCourseLink(Base):
    __tablename__ = "canvas_course_links"
    __table_args__ = (
        UniqueConstraint(
            "owner_user_id",
            "canvas_course_id",
            name="uq_canvas_course_links_owner_course",
        ),
    )
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    canvas_connection_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("canvas_connections.id", ondelete="SET NULL"),
        nullable=True,
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    canvas_course_id: Mapped[str] = mapped_column(String, nullable=False)
    last_synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    course: Mapped[Course] = relationship(back_populates="canvas_link")

    @property
    def connection_status(self) -> str:
        return "connected" if self.canvas_connection_id else "disconnected"
