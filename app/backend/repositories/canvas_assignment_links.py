from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.canvas_assignment_link import CanvasAssignmentLink


async def list_by_course(
    db: AsyncSession, course_id: UUID
) -> list[CanvasAssignmentLink]:
    result = await db.execute(
        select(CanvasAssignmentLink)
        .where(CanvasAssignmentLink.course_id == course_id)
        .order_by(CanvasAssignmentLink.due_at, CanvasAssignmentLink.name)
    )
    return list(result.scalars())


async def get_by_canvas_id(
    db: AsyncSession,
    course_id: UUID,
    canvas_assignment_id: str,
) -> CanvasAssignmentLink | None:
    return await db.scalar(
        select(CanvasAssignmentLink).where(
            CanvasAssignmentLink.course_id == course_id,
            CanvasAssignmentLink.canvas_assignment_id == canvas_assignment_id,
        )
    )
