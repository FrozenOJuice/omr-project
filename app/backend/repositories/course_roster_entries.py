from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.course_roster_entry import CourseRosterEntry


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def create(
    db: AsyncSession,
    *,
    course_id: UUID,
    email: str,
    first_name: str,
    last_name: str,
    student_number: str | None,
    source: str,
    user_id: UUID | None = None,
    canvas_user_id: str | None = None,
) -> CourseRosterEntry:
    entry = CourseRosterEntry(
        course_id=course_id,
        user_id=user_id,
        email=normalize_email(email),
        first_name=first_name,
        last_name=last_name,
        student_number=student_number,
        source=source,
        canvas_user_id=canvas_user_id,
    )
    db.add(entry)
    await db.flush()
    return entry


async def get_by_id(
    db: AsyncSession,
    entry_id: UUID,
) -> CourseRosterEntry | None:
    result = await db.execute(
        select(CourseRosterEntry).where(CourseRosterEntry.id == entry_id)
    )
    return result.scalar_one_or_none()


async def get_by_course_and_email(
    db: AsyncSession,
    course_id: UUID,
    email: str,
) -> CourseRosterEntry | None:
    result = await db.execute(
        select(CourseRosterEntry).where(
            CourseRosterEntry.course_id == course_id,
            func.lower(CourseRosterEntry.email) == normalize_email(email),
        )
    )
    return result.scalar_one_or_none()


async def get_by_course_and_student_number(
    db: AsyncSession,
    course_id: UUID,
    student_number: str,
) -> CourseRosterEntry | None:
    result = await db.execute(
        select(CourseRosterEntry).where(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.student_number == student_number,
        )
    )
    return result.scalar_one_or_none()


async def get_active_canvas_mapping(
    db: AsyncSession,
    course_id: UUID,
    user_id: UUID,
    canvas_user_id: str,
) -> CourseRosterEntry | None:
    result = await db.execute(
        select(CourseRosterEntry).where(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.user_id == user_id,
            CourseRosterEntry.canvas_user_id == canvas_user_id,
            CourseRosterEntry.active.is_(True),
        )
    )
    return result.scalar_one_or_none()


async def list_by_course(
    db: AsyncSession,
    course_id: UUID,
) -> list[CourseRosterEntry]:
    result = await db.execute(
        select(CourseRosterEntry)
        .where(CourseRosterEntry.course_id == course_id)
        .order_by(CourseRosterEntry.last_name, CourseRosterEntry.first_name)
    )
    return list(result.scalars().all())


async def list_active_by_course(
    db: AsyncSession,
    course_id: UUID,
) -> list[CourseRosterEntry]:
    result = await db.execute(
        select(CourseRosterEntry)
        .where(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.active.is_(True),
        )
        .order_by(CourseRosterEntry.last_name, CourseRosterEntry.first_name)
    )
    return list(result.scalars().all())


async def list_unclaimed_by_email(
    db: AsyncSession,
    email: str,
) -> list[CourseRosterEntry]:
    result = await db.execute(
        select(CourseRosterEntry).where(
            CourseRosterEntry.user_id.is_(None),
            CourseRosterEntry.active.is_(True),
            func.lower(CourseRosterEntry.email) == normalize_email(email),
        )
    )
    return list(result.scalars().all())


async def count_active_by_course(db: AsyncSession, course_id: UUID) -> int:
    result = await db.execute(
        select(func.count()).where(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.active.is_(True),
        )
    )
    return result.scalar_one()


async def reset_pending_invitations(db: AsyncSession, course_id: UUID) -> None:
    await db.execute(
        update(CourseRosterEntry)
        .where(
            CourseRosterEntry.course_id == course_id,
            CourseRosterEntry.user_id.is_(None),
            CourseRosterEntry.active.is_(True),
        )
        .values(invited_at=None)
    )


async def delete(db: AsyncSession, entry: CourseRosterEntry) -> None:
    await db.delete(entry)
    await db.flush()
