from enum import StrEnum
import uuid

from sqlalchemy import Boolean, CheckConstraint, FLOAT, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base


class MarkFieldType(StrEnum):
    QUESTION = "question"
    VERSION = "version"
    LAST_NAME = "last_name"
    FIRST_NAME = "first_name"
    STUDENT_ID = "student_id"


class OMRDetectedMark(Base):
    __tablename__ = "omr_detected_marks"
    __table_args__ = (
        CheckConstraint(
            "field_type IN ('question', 'version', 'last_name', 'first_name', 'student_id')",
            name="ck_omr_detected_marks_field_type_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    marking_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("omr_markings.id", ondelete="CASCADE"),
        nullable=False
    )
    # The field's semantic type and its position within that field, decoded from
    # the OMR service's questionId (e.g. "L3" -> field_type=last_name, field_index=3).
    field_type: Mapped[str] = mapped_column(String, nullable=False)
    field_index: Mapped[int] = mapped_column(Integer, nullable=False)
    detected_value: Mapped[str] = mapped_column(String, nullable=True)
    confidence_score: Mapped[float] = mapped_column(FLOAT, nullable=True)
    needs_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="false",
        nullable=False,
    )
    # Which page (matching the scan's page images, see GET /image on the OMR
    # service) bounds/boxes below are relative to.
    page_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Bounding box enclosing every one of the question's bubbles, not just the
    # selected ones: {"x": .., "y": .., "width": .., "height": ..}. Present
    # even for a blank question, unlike boxes.
    bounds: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    # One box per option in the question, selected or not:
    # [{"label": "A", "selected": true, "x": .., "y": .., "width": .., "height": ..}, ...].
    boxes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")
