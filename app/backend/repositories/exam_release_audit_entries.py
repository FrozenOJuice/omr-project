from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam_release_audit_entry import ExamReleaseAuditEntry


async def create_release_audit_entry(
    db: AsyncSession,
    exam_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
) -> ExamReleaseAuditEntry:
    entry = ExamReleaseAuditEntry(
        exam_id=exam_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_release_audit_entries_by_exam(
    db: AsyncSession, exam_id: UUID
) -> list[ExamReleaseAuditEntry]:
    result = await db.execute(
        select(ExamReleaseAuditEntry)
        .where(ExamReleaseAuditEntry.exam_id == exam_id)
        .order_by(ExamReleaseAuditEntry.created_at)
    )
    return list(result.scalars().all())
