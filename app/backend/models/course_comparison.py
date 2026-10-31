import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class CourseComparison(Base):
    __tablename__ = "course_comparisons"
    __table_args__ = (
        UniqueConstraint("base_course_id", "comparison_course_id", name="uq_course_comparison_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    base_course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False, index=True)
    comparison_course_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    mappings: Mapped[list["ExamComparisonMapping"]] = relationship(cascade="all, delete-orphan", lazy="selectin")


class ExamComparisonMapping(Base):
    __tablename__ = "exam_comparison_mappings"
    __table_args__ = (
        UniqueConstraint("course_comparison_id", "base_exam_id", name="uq_comparison_base_exam"),
        UniqueConstraint("course_comparison_id", "comparison_exam_id", name="uq_comparison_historical_exam"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    course_comparison_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("course_comparisons.id", ondelete="CASCADE"), nullable=False, index=True)
    base_exam_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), nullable=False)
    comparison_exam_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)

