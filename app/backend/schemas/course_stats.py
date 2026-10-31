from uuid import UUID

from pydantic import BaseModel


class ExamComparisonStats(BaseModel):
    exam_id: UUID
    exam_name: str
    graded_count: int
    mean_percentage: float | None
    standard_deviation_percentage: float | None
    median_percentage: float | None
    mode_percentages: list[float]
    highest_percentage: float | None
    lowest_percentage: float | None
    distribution: dict[str, int]


class CourseStatsResponse(BaseModel):
    course_id: UUID
    exam_count: int
    graded_count: int
    mean_percentage: float | None
    standard_deviation_percentage: float | None
    median_percentage: float | None
    mode_percentages: list[float]
    highest_percentage: float | None
    lowest_percentage: float | None
    distribution: dict[str, int]
    exams: list[ExamComparisonStats]
