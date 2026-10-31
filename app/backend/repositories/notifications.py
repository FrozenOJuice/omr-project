import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.notification import Notification


async def list_for_user(
    db: AsyncSession, user_id: uuid.UUID, *, page: int, page_size: int
) -> tuple[list[tuple[Notification, str | None]], int]:
    base_query = select(Notification).where(Notification.recipient_user_id == user_id)

    total = (
        await db.execute(
            select(func.count()).select_from(base_query.subquery())
        )
    ).scalar_one()

    query = (
        select(Notification, Course.name)
        .outerjoin(Course, Course.id == Notification.course_id)
        .where(Notification.recipient_user_id == user_id)
        .order_by(Notification.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = (await db.execute(query)).all()
    return [tuple(row) for row in rows], total


async def count_unread(db: AsyncSession, user_id: uuid.UUID) -> int:
    query = select(func.count()).where(
        Notification.recipient_user_id == user_id, Notification.is_read == False  # noqa: E712
    )
    return (await db.execute(query)).scalar_one()


async def mark_read(
    db: AsyncSession, notification_id: uuid.UUID, user_id: uuid.UUID
) -> Notification | None:
    result = await db.execute(
        select(Notification).where(
            Notification.id == notification_id,
            Notification.recipient_user_id == user_id,
        )
    )
    notification = result.scalar_one_or_none()
    if not notification:
        return None

    notification.is_read = True
    await db.commit()
    await db.refresh(notification)
    return notification


async def mark_all_read(db: AsyncSession, user_id: uuid.UUID) -> int:
    result = await db.execute(
        update(Notification)
        .where(
            Notification.recipient_user_id == user_id,
            Notification.is_read == False,  # noqa: E712
        )
        .values(is_read=True)
    )
    await db.commit()
    return result.rowcount or 0
