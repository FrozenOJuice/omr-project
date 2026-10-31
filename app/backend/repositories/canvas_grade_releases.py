from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.canvas_assignment_link import CanvasAssignmentLink
from models.canvas_grade_release import CanvasGradeRelease
from models.canvas_grade_release_attempt import (
    CanvasGradeReleaseAttempt,
    CanvasGradeReleaseRecipient,
)


async def get_by_exam(
    db: AsyncSession, exam_id: UUID, *, for_update: bool = False
) -> CanvasGradeRelease | None:
    query = select(CanvasGradeRelease).where(CanvasGradeRelease.exam_id == exam_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def get_running_attempt(
    db: AsyncSession, release_id: UUID
) -> CanvasGradeReleaseAttempt | None:
    return await db.scalar(
        select(CanvasGradeReleaseAttempt).where(
            CanvasGradeReleaseAttempt.canvas_grade_release_id == release_id,
            CanvasGradeReleaseAttempt.status == "running",
        ).order_by(CanvasGradeReleaseAttempt.started_at.desc())
    )


async def list_recipients(
    db: AsyncSession, attempt_id: UUID
) -> list[CanvasGradeReleaseRecipient]:
    result = await db.scalars(
        select(CanvasGradeReleaseRecipient).where(
            CanvasGradeReleaseRecipient.attempt_id == attempt_id
        )
    )
    return list(result)


async def get_latest_attempt(
    db: AsyncSession, release_id: UUID
) -> CanvasGradeReleaseAttempt | None:
    return await db.scalar(
        select(CanvasGradeReleaseAttempt)
        .where(CanvasGradeReleaseAttempt.canvas_grade_release_id == release_id)
        .order_by(CanvasGradeReleaseAttempt.started_at.desc())
        .limit(1)
    )


async def get_by_assignment(
    db: AsyncSession, assignment_link_id: UUID
) -> CanvasGradeRelease | None:
    return await db.scalar(
        select(CanvasGradeRelease).where(
            CanvasGradeRelease.canvas_assignment_link_id == assignment_link_id
        )
    )


async def list_by_assignments(
    db: AsyncSession, assignment_link_ids: Iterable[UUID]
) -> list[CanvasGradeRelease]:
    ids = list(assignment_link_ids)
    if not ids:
        return []
    result = await db.scalars(
        select(CanvasGradeRelease).where(
            CanvasGradeRelease.canvas_assignment_link_id.in_(ids)
        )
    )
    return list(result)


async def assignments_by_exam(
    db: AsyncSession,
    exam_ids: Iterable[UUID],
) -> dict[UUID, CanvasAssignmentLink]:
    ids = list(exam_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(CanvasGradeRelease.exam_id, CanvasAssignmentLink)
        .join(
            CanvasAssignmentLink,
            CanvasAssignmentLink.id == CanvasGradeRelease.canvas_assignment_link_id,
        )
        .where(CanvasGradeRelease.exam_id.in_(ids))
    )
    return {exam_id: assignment for exam_id, assignment in rows}
