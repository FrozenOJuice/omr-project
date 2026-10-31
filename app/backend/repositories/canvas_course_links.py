from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.canvas_course_link import CanvasCourseLink
from models.course import Course, CourseSource


async def create(
    db: AsyncSession,
    *,
    course: Course,
    canvas_connection_id: UUID,
    canvas_course_id: str,
    synced_at: datetime,
) -> CanvasCourseLink:
    course.source = CourseSource.CANVAS.value
    link = CanvasCourseLink(
        course=course,
        canvas_connection_id=canvas_connection_id,
        owner_user_id=course.created_by,
        canvas_course_id=canvas_course_id,
        last_synced_at=synced_at,
    )
    db.add(link)
    await db.flush()
    await db.refresh(link)
    return link


async def get_by_course_id(
    db: AsyncSession, course_id: UUID
) -> CanvasCourseLink | None:
    result = await db.execute(
        select(CanvasCourseLink).where(CanvasCourseLink.course_id == course_id)
    )
    return result.scalar_one_or_none()


async def get_by_canvas_course(
    db: AsyncSession,
    owner_user_id: UUID,
    canvas_course_id: str,
) -> CanvasCourseLink | None:
    result = await db.execute(
        select(CanvasCourseLink).where(
            CanvasCourseLink.owner_user_id == owner_user_id,
            CanvasCourseLink.canvas_course_id == canvas_course_id,
        )
    )
    return result.scalar_one_or_none()


async def list_by_canvas_courses(
    db: AsyncSession,
    owner_user_id: UUID,
    canvas_course_ids: list[str],
) -> list[CanvasCourseLink]:
    if not canvas_course_ids:
        return []
    result = await db.execute(
        select(CanvasCourseLink).where(
            CanvasCourseLink.owner_user_id == owner_user_id,
            CanvasCourseLink.canvas_course_id.in_(canvas_course_ids),
        )
    )
    return list(result.scalars())
