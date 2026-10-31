from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, Field, SecretStr, StringConstraints


CanvasId = Annotated[
    str,
    StringConstraints(pattern=r"^[1-9][0-9]*$", max_length=20),
]


class CanvasConnectionRequest(BaseModel):
    access_token: SecretStr


class CanvasStudentAccessRequest(BaseModel):
    access_token: SecretStr


class CanvasCapabilitiesResponse(BaseModel):
    configured: bool
    instructor_only: bool = True
    settings_url: str | None = None


class CanvasConnectionResponse(BaseModel):
    connected: bool
    user_name: str | None = None
    login_id: str | None = None
    connected_at: datetime | None = None
    last_verified_at: datetime | None = None


class CanvasCourseResponse(BaseModel):
    id: CanvasId
    name: str
    course_code: str | None = None
    imported: bool = False
    omr_course_id: UUID | None = None


class CanvasStudentResponse(BaseModel):
    id: CanvasId
    name: str
    login_id: str | None = None
    sis_user_id: str | None = None
    email: str | None = None
    sortable_name: str | None = None


class CanvasRosterResponse(BaseModel):
    course_id: CanvasId
    students: list[CanvasStudentResponse]
    skip_reasons: dict[str, int] = Field(default_factory=dict)


class CanvasRosterSyncResponse(BaseModel):
    added: int
    updated: int
    removed: int
    skipped: int
    skip_reasons: dict[str, int] = Field(default_factory=dict)
    active: int
    last_synced_at: datetime


class CanvasRosterInvitationResponse(BaseModel):
    sent: int
    already_invited: int
    linked: int
    failed: int
    pending: int


class CanvasAssignmentResponse(BaseModel):
    id: CanvasId
    name: str
    due_at: datetime | None = None
    points_possible: float | None = None
    published: bool
    html_url: str | None = None
    linked_exam_id: UUID | None = None
    available: bool = True


class CanvasExamAssignmentRequest(BaseModel):
    assignment_id: CanvasId


class CanvasGradeReleaseResponse(BaseModel):
    exam_id: UUID
    assignment_id: CanvasId | None = None
    assignment_name: str | None = None
    eligible_count: int
    skipped_count: int
    skipped_reasons: dict[str, int]
    target_locked: bool = False
    last_sent_count: int = 0
    last_skipped_count: int = 0
    last_failed_count: int = 0
    last_attempted_at: datetime | None = None
    last_attempt_status: Literal["running", "completed", "partial", "failed"] | None = None
