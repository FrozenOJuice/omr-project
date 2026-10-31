import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from db.session import Base
from models.user import Institution


UBC_WINTER_SESSION_1_TERM_ID = uuid.UUID("00000000-0000-0000-0007-000000000001")


class AcademicTermType(StrEnum):
    PRESET = "preset"
    CUSTOM = "custom"


class AcademicTermYearFormat(StrEnum):
    ACADEMIC_YEAR_RANGE = "academic_year_range"
    FOLLOWING_YEAR = "following_year"
    START_YEAR = "start_year"
    NONE = "none"


class AcademicTerm(Base):
    __tablename__ = "academic_terms"
    __table_args__ = (
        UniqueConstraint(
            "institution",
            "code",
            name="uq_academic_terms_institution_code",
        ),
        UniqueConstraint(
            "institution",
            "created_by",
            "normalized_name",
            name="uq_academic_terms_owner_name",
        ),
        CheckConstraint(
            "institution IN ('ubc', 'generic')",
            name="ck_academic_terms_institution_valid",
        ),
        CheckConstraint(
            "term_type IN ('preset', 'custom')",
            name="ck_academic_terms_type_valid",
        ),
        CheckConstraint(
            "year_format IN ('academic_year_range', 'following_year', 'start_year', 'none')",
            name="ck_academic_terms_year_format_valid",
        ),
        CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_academic_terms_name_not_blank",
        ),
        CheckConstraint(
            "length(normalized_name) > 0",
            name="ck_academic_terms_normalized_name_not_blank",
        ),
        CheckConstraint(
            "(term_type = 'preset' AND code IS NOT NULL AND created_by IS NULL) "
            "OR (term_type = 'custom' AND code IS NULL)",
            name="ck_academic_terms_type_fields_valid",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    institution: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=Institution.UBC.value,
        server_default=Institution.UBC.value,
    )
    code: Mapped[str | None] = mapped_column(String, nullable=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    normalized_name: Mapped[str] = mapped_column(String, nullable=False)
    term_type: Mapped[str] = mapped_column(String, nullable=False)
    year_format: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=AcademicTermYearFormat.START_YEAR.value,
        server_default=AcademicTermYearFormat.START_YEAR.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
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

    @property
    def term_type_enum(self) -> AcademicTermType:
        return AcademicTermType(self.term_type)

    @property
    def year_format_enum(self) -> AcademicTermYearFormat:
        return AcademicTermYearFormat(self.year_format)
