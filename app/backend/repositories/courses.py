from uuid import UUID

from datetime import datetime

from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from models.course import Course
from models.academic_term import AcademicTerm
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.exam import Exam


async def get_by_id(db: AsyncSession, course_id: UUID) -> Course | None:
    result = await db.execute(select(Course).where(Course.id == course_id))
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    name: str,
    academic_term: AcademicTerm,
    created_by: UUID,
    academic_year_start: int,
) -> Course:
    course = Course(
        name=name,
        academic_term_id=academic_term.id,
        academic_term=academic_term,
        academic_year_start=academic_year_start,
        created_by=created_by,
    )
    db.add(course)
    await db.flush()
    await db.refresh(course)
    return course


async def delete(db: AsyncSession, course: Course) -> None:
    await db.delete(course)
    await db.flush()


async def update(
    db: AsyncSession,
    course: Course,
    name: str | None = None,
    academic_term: AcademicTerm | None = None,
    academic_year_start: int | None = None,
) -> Course:
    if name is not None:
        course.name = name
    if academic_term is not None:
        course.academic_term_id = academic_term.id
        course.academic_term = academic_term
    if academic_year_start is not None:
        course.academic_year_start = academic_year_start

    await db.flush()
    await db.refresh(course)
    return course


async def get_student_enrolment(
    db: AsyncSession, course_id: UUID, user_id: UUID
) -> Enrolment | None:
    result = await db.execute(
        select(Enrolment).where(
            Enrolment.course_id == course_id,
            Enrolment.user_id == user_id,
            Enrolment.role == "student",
        )
    )
    return result.scalar_one_or_none()


async def get_staff_enrolment(
    db: AsyncSession, course_id: UUID, user_id: UUID
) -> Enrolment | None:
    result = await db.execute(
        select(Enrolment).where(
            Enrolment.course_id == course_id,
            Enrolment.user_id == user_id,
            Enrolment.role == "professor",
        )
    )
    return result.scalar_one_or_none()


async def get_enrolment(
    db: AsyncSession, course_id: UUID, user_id: UUID
) -> Enrolment | None:
    result = await db.execute(
        select(Enrolment).where(
            Enrolment.course_id == course_id,
            Enrolment.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def archive(
    db: AsyncSession,
    course: Course,
    *,
    archived_at: datetime,
    archived_by_user_id: UUID,
    retention_policy_id: UUID,
    retention_policy_snapshot: dict,
    scanned_images_retention_until: datetime,
    exam_records_retention_until: datetime,
) -> Course:
    course.archived_at = archived_at
    course.archived_by_user_id = archived_by_user_id
    course.retention_policy_id = retention_policy_id
    course.retention_policy_snapshot = retention_policy_snapshot
    course.scanned_images_retention_until = scanned_images_retention_until
    course.exam_records_retention_until = exam_records_retention_until
    await db.flush()
    await db.refresh(course)
    return course


async def has_dependent_records(db: AsyncSession, course_id: UUID) -> bool:
    result = await db.execute(
        select(
            exists().where(Exam.course_id == course_id),
            exists().where(CourseRosterEntry.course_id == course_id),
            exists().where(Enrolment.course_id == course_id),
        )
    )
    has_exams, has_roster_entries, has_enrolments = result.one()
    return has_exams or has_roster_entries or has_enrolments


async def restore(db: AsyncSession, course: Course) -> Course:
    course.archived_at = None
    course.archived_by_user_id = None
    course.retention_policy_id = None
    course.retention_policy_snapshot = None
    course.scanned_images_retention_until = None
    course.exam_records_retention_until = None
    await db.flush()
    await db.refresh(course)
    return course


async def list_all(db: AsyncSession, *, include_archived: bool = False) -> list[tuple[Course, int]]:
    student_count_sq = (
        select(func.count())
        .where(
            CourseRosterEntry.course_id == Course.id,
            CourseRosterEntry.active.is_(True),
        )
        .correlate(Course)
        .scalar_subquery()
    )
    query = select(Course, student_count_sq.label('student_count'))
    if not include_archived:
        query = query.where(Course.archived_at.is_(None))
    result = await db.execute(query)
    return list(result.all())


async def list_by_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    include_archived: bool = False,
) -> list[tuple[Course, int]]:
    user_enrolment = aliased(Enrolment, name='user_enrolment')
    student_count_sq = (
        select(func.count())
        .where(
            CourseRosterEntry.course_id == Course.id,
            CourseRosterEntry.active.is_(True),
        )
        .correlate(Course)
        .scalar_subquery()
    )
    query = (
        select(Course, student_count_sq.label('student_count'))
        .outerjoin(user_enrolment, (user_enrolment.course_id == Course.id) & (user_enrolment.user_id == user_id))
        .where((Course.created_by == user_id) | (user_enrolment.id != None))
        .distinct()
    )
    if not include_archived:
        query = query.where(Course.archived_at.is_(None))
    result = await db.execute(query)
    return list(result.all())
