from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import get_current_user
from errors.exceptions import NotFoundError
from models.user import User
from repositories.notifications import (
    count_unread,
    list_for_user,
    mark_all_read,
    mark_read,
)
from schemas.notifications import (
    MarkAllReadResponse,
    NotificationListResponse,
    NotificationResponse,
    UnreadCountResponse,
)

router = APIRouter(prefix="/api", tags=["Notifications"])


@router.get(
    "/notifications",
    response_model=NotificationListResponse,
    status_code=status.HTTP_200_OK,
)
async def list_notifications(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows, total = await list_for_user(db, current_user.id, page=page, page_size=page_size)
    items = [
        NotificationResponse.model_validate(notification).model_copy(
            update={"course_label": course_label}
        )
        for notification, course_label in rows
    ]
    return NotificationListResponse(items=items, total=total, page=page, page_size=page_size)


@router.get(
    "/notifications/unread-count",
    response_model=UnreadCountResponse,
    status_code=status.HTTP_200_OK,
)
async def get_unread_count(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    count = await count_unread(db, current_user.id)
    return UnreadCountResponse(count=count)


@router.patch(
    "/notifications/read-all",
    response_model=MarkAllReadResponse,
    status_code=status.HTTP_200_OK,
)
async def mark_all_notifications_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    updated = await mark_all_read(db, current_user.id)
    return MarkAllReadResponse(updated=updated)


@router.patch(
    "/notifications/{notification_id}/read",
    response_model=NotificationResponse,
    status_code=status.HTTP_200_OK,
)
async def mark_notification_read(
    notification_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    notification = await mark_read(db, notification_id, current_user.id)
    if not notification:
        raise NotFoundError("Notification not found", code="notification_not_found")
    return notification
