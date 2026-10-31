from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from models.academic_term import AcademicTermType, AcademicTermYearFormat
from models.user import Institution


class CreateAcademicTermRequest(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    term_type: AcademicTermType = AcademicTermType.CUSTOM
    institution: Institution | None = None
    code: str | None = Field(default=None, min_length=1, max_length=100)
    year_format: AcademicTermYearFormat = AcademicTermYearFormat.START_YEAR

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Academic term name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_term_fields(self):
        if self.term_type == AcademicTermType.CUSTOM and self.code is not None:
            raise ValueError("Custom academic terms cannot define a preset code")
        return self


class UpdateAcademicTermRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    year_format: AcademicTermYearFormat | None = None
    is_active: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Academic term name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def require_change(self):
        if not self.model_fields_set:
            raise ValueError("At least one academic term field must be provided")
        return self


class AcademicTermResponse(BaseModel):
    id: UUID
    institution: Institution
    code: str | None
    name: str
    term_type: AcademicTermType
    year_format: AcademicTermYearFormat
    is_active: bool
    created_by: UUID | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AcademicTermListItemResponse(AcademicTermResponse):
    in_use: bool = False
