from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from models.course import Course
from models.course_comparison import CourseComparison
from models.user import User
from repositories import course_comparisons as comparisons_repo
from repositories.courses import get_by_id as get_course_by_id
from schemas.course_comparison import CourseComparisonResponse, CourseComparisonUpdate
from services.course_lifecycle import ensure_course_writable


def _can_manage(user: User, course: Course) -> bool:
    return user.role == "admin" or course.created_by == user.id


async def _courses_for_comparison(db: AsyncSession, base_course_id: UUID, comparison_course_id: UUID, user: User) -> tuple[Course, Course]:
    base = await get_course_by_id(db, base_course_id)
    historical = await get_course_by_id(db, comparison_course_id)
    if not base or not historical:
        raise NotFoundError("Course not found", code="course_not_found")
    if base.id == historical.id:
        raise BadRequestError("A course cannot be compared with itself", code="same_course_comparison")
    if not _can_manage(user, base) or not _can_manage(user, historical):
        raise ForbiddenError("You do not have permission to compare these courses", code="course_comparison_forbidden")
    return base, historical


async def _authorized_comparison(db: AsyncSession, base_course_id: UUID, comparison_id: UUID, user: User) -> tuple[CourseComparison, Course, Course]:
    comparison = await comparisons_repo.get_by_id(db, comparison_id)
    if not comparison or comparison.base_course_id != base_course_id:
        raise NotFoundError("Course comparison not found", code="course_comparison_not_found")
    base, historical = await _courses_for_comparison(db, comparison.base_course_id, comparison.comparison_course_id, user)
    return comparison, base, historical


async def _response(db: AsyncSession, comparison: CourseComparison, base: Course, historical: Course) -> CourseComparisonResponse:
    base_exams = {exam.id: exam for exam in await comparisons_repo.list_exams_ordered(db, base.id)}
    historical_exams = {exam.id: exam for exam in await comparisons_repo.list_exams_ordered(db, historical.id)}
    return CourseComparisonResponse(
        id=comparison.id,
        base_course=base,
        comparison_course=historical,
        mappings=[{
            "id": mapping.id,
            "base_exam_id": mapping.base_exam_id,
            "base_exam_name": base_exams[mapping.base_exam_id].name,
            "comparison_exam_id": mapping.comparison_exam_id,
            "comparison_exam_name": historical_exams[mapping.comparison_exam_id].name if mapping.comparison_exam_id else None,
        } for mapping in sorted(comparison.mappings, key=lambda item: (base_exams[item.base_exam_id].created_at, str(item.base_exam_id)))],
        created_at=comparison.created_at,
        updated_at=comparison.updated_at,
    )


async def create_comparison(db: AsyncSession, base_course_id: UUID, comparison_course_id: UUID, user: User) -> CourseComparisonResponse:
    base, historical = await _courses_for_comparison(db, base_course_id, comparison_course_id, user)
    ensure_course_writable(base)
    if await comparisons_repo.get_pair(db, base.id, historical.id):
        raise ConflictError("These courses are already being compared", code="course_comparison_exists")
    base_exams = await comparisons_repo.list_exams_ordered(db, base.id)
    historical_exams = await comparisons_repo.list_exams_ordered(db, historical.id)
    pairs = [(exam.id, historical_exams[index].id if index < len(historical_exams) else None) for index, exam in enumerate(base_exams)]
    try:
        comparison = await comparisons_repo.create(db, base.id, historical.id, user.id, pairs)
        await db.commit()
        comparison = await comparisons_repo.get_by_id(db, comparison.id)
    except Exception:
        await db.rollback()
        raise
    return await _response(db, comparison, base, historical)


async def list_comparisons(db: AsyncSession, base_course_id: UUID, user: User) -> list[CourseComparisonResponse]:
    base = await get_course_by_id(db, base_course_id)
    if not base:
        raise NotFoundError("Course not found", code="course_not_found")
    if not _can_manage(user, base):
        raise ForbiddenError("You do not have permission to view these comparisons", code="course_comparison_forbidden")
    responses = []
    for comparison in await comparisons_repo.list_for_course(db, base_course_id):
        historical = await get_course_by_id(db, comparison.comparison_course_id)
        if historical and _can_manage(user, historical):
            responses.append(await _response(db, comparison, base, historical))
    return responses


async def get_comparison(db: AsyncSession, base_course_id: UUID, comparison_id: UUID, user: User) -> CourseComparisonResponse:
    comparison, base, historical = await _authorized_comparison(db, base_course_id, comparison_id, user)
    return await _response(db, comparison, base, historical)


async def update_comparison(db: AsyncSession, base_course_id: UUID, comparison_id: UUID, request: CourseComparisonUpdate, user: User) -> CourseComparisonResponse:
    comparison, base, historical = await _authorized_comparison(db, base_course_id, comparison_id, user)
    ensure_course_writable(base)
    base_exam_ids = {exam.id for exam in await comparisons_repo.list_exams_ordered(db, base.id)}
    historical_exam_ids = {exam.id for exam in await comparisons_repo.list_exams_ordered(db, historical.id)}
    requested_base_ids = [item.base_exam_id for item in request.mappings]
    requested_historical_ids = [item.comparison_exam_id for item in request.mappings if item.comparison_exam_id]
    if len(requested_base_ids) != len(set(requested_base_ids)) or len(requested_historical_ids) != len(set(requested_historical_ids)):
        raise BadRequestError("An exam may only appear once in a comparison mapping", code="duplicate_exam_mapping")
    if not set(requested_base_ids).issubset(base_exam_ids) or not set(requested_historical_ids).issubset(historical_exam_ids):
        raise BadRequestError("Every mapped exam must belong to its corresponding course", code="invalid_exam_mapping")
    mappings_by_exam = {mapping.base_exam_id: mapping for mapping in comparison.mappings}
    if not set(requested_base_ids).issubset(mappings_by_exam):
        raise BadRequestError("Unknown base exam mapping", code="invalid_exam_mapping")
    try:
        # Clear the selected rows first so swapping two historical exams does not
        # transiently violate the per-comparison uniqueness constraint.
        for item in request.mappings:
            mappings_by_exam[item.base_exam_id].comparison_exam_id = None
        await db.flush()
        for item in request.mappings:
            mappings_by_exam[item.base_exam_id].comparison_exam_id = item.comparison_exam_id
        await db.flush()
        await db.commit()
        comparison = await comparisons_repo.get_by_id(db, comparison.id)
    except Exception:
        await db.rollback()
        raise
    return await _response(db, comparison, base, historical)


async def delete_comparison(db: AsyncSession, base_course_id: UUID, comparison_id: UUID, user: User) -> None:
    comparison, base, _ = await _authorized_comparison(db, base_course_id, comparison_id, user)
    ensure_course_writable(base)
    try:
        await comparisons_repo.delete(db, comparison)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
