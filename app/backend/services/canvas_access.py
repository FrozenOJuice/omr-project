import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import ConflictError, ForbiddenError, NotFoundError
from integrations.canvas_client import normalize_canvas_id
from models.canvas_connection import CanvasConnection
from models.course import Course
from models.user import User
from repositories import courses
from services.canvas_connection import get_connection


async def manageable_course(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> Course:
    course = await courses.get_by_id(db, course_id)
    if course is None or course.canvas_link is None:
        raise NotFoundError(
            "Imported Canvas course not found",
            code="canvas_course_not_found",
        )
    if course.canvas_link.owner_user_id != user.id:
        raise ForbiddenError(
            "This Canvas import belongs to another OMR account",
            code="canvas_course_owner_required",
        )
    return course


async def connected_course(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> tuple[Course, CanvasConnection, str]:
    course = await manageable_course(db, user, course_id)
    connection = await get_connection(db, user.id)
    if connection is None or connection.access_token_encrypted is None:
        raise ConflictError(
            "Reconnect Canvas to continue",
            code="canvas_reconnect_required",
        )
    canvas_course_id = course.canvas_link.canvas_course_id
    if normalize_canvas_id(canvas_course_id) != canvas_course_id:
        raise ConflictError(
            "The imported Canvas course ID is invalid",
            code="invalid_canvas_course_id",
        )
    return course, connection, canvas_course_id
