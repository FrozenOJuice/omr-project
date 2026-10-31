import uuid
from datetime import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict

from schemas.canvas_schema import CanvasId


class CreateExamRequest(BaseModel):
    name: str
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    role: str
    course_id: uuid.UUID
    exam_template_id: uuid.UUID
    canvas_assignment_id: CanvasId | None = None


class UpdateExamRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    role: Optional[str] = None
    course_id: Optional[uuid.UUID] = None
    exam_template_id: Optional[uuid.UUID] = None
    delete_answer_keys: bool = False


class ExamResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: Optional[str]
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    role: str
    course_id: uuid.UUID
    exam_template_id: Optional[uuid.UUID]
    created_by: Optional[uuid.UUID]
    created_at: datetime
    released: bool = False
    is_graded: bool = False
    # Whether any submission has been graded yet, regardless of whether every
    # scan has been. Unlike is_graded above (list_exams_by_course's "every
    # currently-uploaded scan is graded" completion badge), this is what the
    # answer-key page uses to know it should lock editing.
    has_any_grade: bool = False
    has_scans: bool = False
    total_scans: int = 0
    graded_scans: int = 0
    failed_scans: int = 0
    has_answer_key: bool = False
    answer_keys_complete: bool = False
    template_registered: bool = False
    pending_review_request_count: int = 0
    ambiguous_grade_count: int = 0
    template_missing: bool = False
    template_warning: Optional[str] = None
    generated_pdf_path: Optional[str] = None
    canvas_assignment_id: CanvasId | None = None
    canvas_assignment_name: str | None = None


class ExamReleaseAuditEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exam_id: uuid.UUID
    actor_user_id: Optional[uuid.UUID]
    actor_name: Optional[str]
    event_type: str
    created_at: datetime
