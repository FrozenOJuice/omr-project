from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from models.course_comparison import CourseComparison, ExamComparisonMapping
from models.exam import Exam


async def list_for_course(db: AsyncSession, course_id: UUID) -> list[CourseComparison]:
    result = await db.execute(select(CourseComparison).options(selectinload(CourseComparison.mappings)).where(CourseComparison.base_course_id == course_id).order_by(CourseComparison.created_at))
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, comparison_id: UUID) -> CourseComparison | None:
    result = await db.execute(select(CourseComparison).options(selectinload(CourseComparison.mappings)).where(CourseComparison.id == comparison_id))
    return result.scalar_one_or_none()


async def get_pair(db: AsyncSession, base_course_id: UUID, comparison_course_id: UUID) -> CourseComparison | None:
    result = await db.execute(select(CourseComparison).where(CourseComparison.base_course_id == base_course_id, CourseComparison.comparison_course_id == comparison_course_id))
    return result.scalar_one_or_none()


async def list_exams_ordered(db: AsyncSession, course_id: UUID) -> list[Exam]:
    result = await db.execute(select(Exam).where(Exam.course_id == course_id).order_by(Exam.created_at, Exam.id))
    return list(result.scalars().all())


async def create(db: AsyncSession, base_course_id: UUID, comparison_course_id: UUID, created_by: UUID, exam_pairs: list[tuple[UUID, UUID | None]]) -> CourseComparison:
    comparison = CourseComparison(base_course_id=base_course_id, comparison_course_id=comparison_course_id, created_by=created_by)
    db.add(comparison)
    await db.flush()
    # Do not assign through comparison.mappings here: on an already-flushed
    # async ORM object that can first attempt a lazy load of the collection,
    # which raises MissingGreenlet. Insert the child rows explicitly instead.
    db.add_all([
        ExamComparisonMapping(
            course_comparison_id=comparison.id,
            base_exam_id=base_id,
            comparison_exam_id=historical_id,
        )
        for base_id, historical_id in exam_pairs
    ])
    await db.flush()
    return comparison


async def delete(db: AsyncSession, comparison: CourseComparison) -> None:
    await db.delete(comparison)
    await db.flush()
