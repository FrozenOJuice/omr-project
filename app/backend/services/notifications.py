import uuid
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.enrolment import Enrolment
from models.notification import Notification
from models.user import User
from core.settings import settings
from services.email_service import EmailDeliveryError
from services.email_service import send_notification_email

logger = logging.getLogger(__name__)

_REGRADE_NOTIFICATION_TYPES = {"review_request_created", "review_request_resolved"}
_BATCH_NOTIFICATION_TYPES = {
    "grade_ready",
    "grade_needs_review",
    "scan_failed",
    "grading_failed",
}


async def notify_user(
    db: AsyncSession,
    *,
    recipient_user_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    course_id: uuid.UUID | None = None,
    link_path: str | None = None,
    link_query: str | None = None,
) -> Notification:
    notification = Notification(
        recipient_user_id=recipient_user_id,
        type=type,
        title=title,
        body=body,
        course_id=course_id,
        link_path=link_path,
        link_query=link_query,
    )
    db.add(notification)
    await db.commit()
    await db.refresh(notification)
    user = await db.get(User, recipient_user_id)
    if user:
        await _deliver_notification_email(notification, user)
    return notification


async def _notify_many(
    db: AsyncSession,
    *,
    recipient_ids: set[uuid.UUID],
    type: str,
    title: str,
    body: str | None,
    course_id: uuid.UUID,
    link_path: str | None,
    link_query: str | None,
) -> list[Notification]:
    notifications = [
        Notification(
            recipient_user_id=recipient_id,
            type=type,
            title=title,
            body=body,
            course_id=course_id,
            link_path=link_path,
            link_query=link_query,
        )
        for recipient_id in recipient_ids
    ]
    db.add_all(notifications)
    await db.commit()
    for notification in notifications:
        await db.refresh(notification)
    users_by_id = {
        user.id: user
        for user in (
            await db.execute(select(User).where(User.id.in_(recipient_ids)))
        ).scalars()
    }
    for notification in notifications:
        user = users_by_id.get(notification.recipient_user_id)
        if user:
            await _deliver_notification_email(notification, user)
    return notifications


async def _deliver_notification_email(notification: Notification, user: User) -> None:
    if not _should_deliver_notification_email(user, notification.type):
        return
    if not settings.email_from or not settings.resend_api_key:
        logger.debug("Notification email delivery is not configured")
        return

    try:
        await send_notification_email(
            user.email,
            notification_id=str(notification.id),
            notification_type=notification.type,
            title=notification.title,
            body=notification.body,
            link_path=notification.link_path,
            link_query=notification.link_query,
        )
    except EmailDeliveryError:
        logger.exception("Failed to deliver notification email for %s", notification.id)


def _should_deliver_notification_email(user: User, notification_type: str) -> bool:
    if not user.email_notifications_enabled:
        return False
    if notification_type in _REGRADE_NOTIFICATION_TYPES:
        return user.regrade_alerts_enabled
    if notification_type in _BATCH_NOTIFICATION_TYPES:
        return user.batch_job_complete_enabled
    return True


async def _course_staff_ids(db: AsyncSession, course_id: uuid.UUID) -> set[uuid.UUID]:
    query = (
        select(Course.created_by, Enrolment.user_id)
        .select_from(Course)
        .outerjoin(
            Enrolment,
            (Enrolment.course_id == Course.id)
            & (Enrolment.role == "professor"),
        )
        .where(Course.id == course_id)
    )
    rows = (await db.execute(query)).all()
    ids: set[uuid.UUID] = set()
    for created_by, enrolled_user_id in rows:
        if created_by is not None:
            ids.add(created_by)
        if enrolled_user_id is not None:
            ids.add(enrolled_user_id)
    return ids


async def notify_course_staff(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    link_query: str | None = None,
    exclude_user_id: uuid.UUID | None = None,
) -> list[Notification]:
    recipient_ids = await _course_staff_ids(db, course_id)
    if exclude_user_id is not None:
        recipient_ids.discard(exclude_user_id)
    if not recipient_ids:
        return []

    return await _notify_many(
        db,
        recipient_ids=recipient_ids,
        type=type,
        title=title,
        body=body,
        course_id=course_id,
        link_path=link_path,
        link_query=link_query,
    )


async def notify_course_students(
    db: AsyncSession,
    *,
    course_id: uuid.UUID,
    type: str,
    title: str,
    body: str | None = None,
    link_path: str | None = None,
    link_query: str | None = None,
) -> list[Notification]:
    query = select(Enrolment.user_id).where(
        Enrolment.course_id == course_id, Enrolment.role == "student"
    )
    student_ids = {row[0] for row in (await db.execute(query)).all()}
    if not student_ids:
        return []

    return await _notify_many(
        db,
        recipient_ids=student_ids,
        type=type,
        title=title,
        body=body,
        course_id=course_id,
        link_path=link_path,
        link_query=link_query,
    )
