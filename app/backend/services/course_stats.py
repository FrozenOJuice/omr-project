from collections import Counter, defaultdict
from statistics import mean, median, multimode, pstdev
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import ForbiddenError, NotFoundError
from repositories.course_stats import list_course_exam_grade_rows
from repositories.courses import get_by_id as get_course_by_id
from repositories.users import get_by_id as get_user_by_id
from schemas.course_stats import CourseStatsResponse, ExamComparisonStats


_DISTRIBUTION_BANDS = (
    "<50",
    "50-60",
    "60-70",
    "70-80",
    "80-90",
    "90-100",
)


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def _distribution_band(percentage: float) -> str:
    if percentage < 50:
        return "<50"
    if percentage < 60:
        return "50-60"
    if percentage < 70:
        return "60-70"
    if percentage < 80:
        return "70-80"
    if percentage < 90:
        return "80-90"
    return "90-100"


def _distribution(percentages: list[float]) -> dict[str, int]:
    counts = Counter(_distribution_band(value) for value in percentages)
    return {band: counts.get(band, 0) for band in _DISTRIBUTION_BANDS}


def _summary(
    *,
    exam_id: UUID,
    exam_name: str,
    percentages: list[float],
) -> ExamComparisonStats:
    return ExamComparisonStats(
        exam_id=exam_id,
        exam_name=exam_name,
        graded_count=len(percentages),
        mean_percentage=_round(mean(percentages)) if percentages else None,
        standard_deviation_percentage=_round(pstdev(percentages)) if percentages else None,
        median_percentage=_round(median(percentages)) if percentages else None,
        mode_percentages=[_round(value) for value in multimode(percentages)] if percentages else [],
        highest_percentage=_round(max(percentages)) if percentages else None,
        lowest_percentage=_round(min(percentages)) if percentages else None,
        distribution=_distribution(percentages),
    )


async def get_course_stats(
    db: AsyncSession,
    course_id: UUID,
    requesting_user_id: UUID,
) -> CourseStatsResponse:
    course = await get_course_by_id(db, course_id)
    if not course:
        raise NotFoundError("Course not found", code="course_not_found")

    user = await get_user_by_id(db, requesting_user_id)
    if user.role != "admin" and course.created_by != requesting_user_id:
        raise ForbiddenError(
            "You do not have permission to view this course's stats",
            code="course_stats_forbidden",
        )

    retention_processed_at = getattr(course, "retention_processed_at", None)
    retained_analytics = getattr(course, "retained_analytics", None)
    if retention_processed_at is not None and retained_analytics is not None:
        return CourseStatsResponse.model_validate(retained_analytics)

    rows = await list_course_exam_grade_rows(db, course_id)
    exam_names: dict[UUID, str] = {}
    percentages_by_exam: defaultdict[UUID, list[float]] = defaultdict(list)

    for exam_id, exam_name, total_score, max_score in rows:
        exam_names[exam_id] = exam_name
        if total_score is None or max_score is None or float(max_score) <= 0:
            continue
        percentage = round((float(total_score) / float(max_score)) * 100, 2)
        percentages_by_exam[exam_id].append(percentage)

    exams = [
        _summary(
            exam_id=exam_id,
            exam_name=exam_name,
            percentages=percentages_by_exam[exam_id],
        )
        for exam_id, exam_name in exam_names.items()
    ]
    all_percentages = [
        percentage
        for exam in exams
        for percentage in percentages_by_exam[exam.exam_id]
    ]

    return CourseStatsResponse(
        course_id=course_id,
        exam_count=len(exams),
        graded_count=len(all_percentages),
        mean_percentage=_round(mean(all_percentages)) if all_percentages else None,
        standard_deviation_percentage=_round(pstdev(all_percentages)) if all_percentages else None,
        median_percentage=_round(median(all_percentages)) if all_percentages else None,
        mode_percentages=[_round(value) for value in multimode(all_percentages)] if all_percentages else [],
        highest_percentage=_round(max(all_percentages)) if all_percentages else None,
        lowest_percentage=_round(min(all_percentages)) if all_percentages else None,
        distribution=_distribution(all_percentages),
        exams=exams,
    )
