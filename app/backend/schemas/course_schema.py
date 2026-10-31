from uuid import UUID
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator
from schemas.auth_schema import NormalizedPersonName, NormalizedStudentNumber
from schemas.academic_term import AcademicTermResponse
from schemas.canvas_schema import CanvasId, CanvasRosterSyncResponse


def _validate_academic_year_not_past(value: int | None) -> int | None:
    if value is not None and value < datetime.now(timezone.utc).year:
        raise ValueError("Academic year cannot be in the past")
    return value


class CreateCourseRequest(BaseModel):
    name: str
    academic_term_id: UUID
    academic_year_start: int = Field(default_factory=lambda: datetime.now(timezone.utc).year, ge=2000, le=2100)

    _validate_academic_year_start_not_past = field_validator("academic_year_start")(_validate_academic_year_not_past)


class UpdateCourseRequest(BaseModel):
    name: str | None = None
    academic_term_id: UUID | None = None
    academic_year_start: int | None = Field(default=None, ge=2000, le=2100)


class ArchiveCourseRequest(BaseModel):
    confirmed: bool = False
    override_active_course: bool = False


class AddStudentRequest(BaseModel):
    email: EmailStr
    first_name: NormalizedPersonName
    last_name: NormalizedPersonName
    student_number: NormalizedStudentNumber


class CanvasCourseLinkResponse(BaseModel):
    canvas_course_id: CanvasId
    last_synced_at: datetime
    connection_status: Literal["connected", "disconnected"]

    model_config = {"from_attributes": True}


class CourseResponse(BaseModel):
    id: UUID
    name: str
    academic_term_id: UUID
    academic_term: AcademicTermResponse
    academic_year_start: int
    archived_at: datetime | None
    archived_by_user_id: UUID | None = None
    retention_policy_id: UUID | None = None
    scanned_images_retention_until: datetime | None = None
    exam_records_retention_until: datetime | None = None
    scanned_images_purged_at: datetime | None = None
    exam_records_purged_at: datetime | None = None
    retention_processed_at: datetime | None = None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    invite_link: str
    invite_link_expires_at: datetime
    student_count: int = 0
    source: Literal["omr", "canvas"]
    canvas_link: CanvasCourseLinkResponse | None = None
    can_manage_canvas: bool = False

    model_config = {"from_attributes": True}


class CanvasCourseImportRequest(BaseModel):
    course_ids: list[CanvasId] = Field(min_length=1, max_length=25)


class CanvasCourseImportResult(BaseModel):
    canvas_course_id: CanvasId
    status: Literal["imported", "already_imported", "failed"]
    course: CourseResponse | None = None
    roster_sync: CanvasRosterSyncResponse | None = None
    message: str | None = None


class CanvasCourseImportResponse(BaseModel):
    results: list[CanvasCourseImportResult]


class CourseInviteCodeResponse(BaseModel):
    course_id: UUID
    invite_link: str
    invite_link_expires_at: datetime


class EnrolledStudentResponse(BaseModel):
    id: UUID
    user_id: UUID | None = None
    first_name: str
    last_name: str
    email: str
    role: str = "student"
    student_number: str | None = None
    account_status: str
    invited_at: datetime | None = None
    source: Literal["manual", "csv", "invite", "canvas"]
    active: bool

    model_config = {"from_attributes": True}
