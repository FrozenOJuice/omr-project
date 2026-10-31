from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from schemas.academic_term import AcademicTermResponse


class CourseComparisonCreate(BaseModel):
    comparison_course_id: UUID


class ExamMappingOverride(BaseModel):
    base_exam_id: UUID
    comparison_exam_id: UUID | None


class CourseComparisonUpdate(BaseModel):
    mappings: list[ExamMappingOverride] = Field(min_length=1)


class ExamMappingResponse(BaseModel):
    id: UUID
    base_exam_id: UUID
    base_exam_name: str
    comparison_exam_id: UUID | None
    comparison_exam_name: str | None


class ComparedCourseResponse(BaseModel):
    id: UUID
    name: str
    academic_term_id: UUID
    academic_term: AcademicTermResponse
    academic_year_start: int
    archived_at: datetime | None

    model_config = {"from_attributes": True}


class CourseComparisonResponse(BaseModel):
    id: UUID
    base_course: ComparedCourseResponse
    comparison_course: ComparedCourseResponse
    mappings: list[ExamMappingResponse]
    created_at: datetime
    updated_at: datetime
