from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.grade_audit_entry import GradeAuditEntry


async def create_audit_entry(
    db: AsyncSession,
    exam_grade_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    previous_total_score: float | None,
    new_total_score: float,
    changes: dict,
    flush: bool = True,
) -> GradeAuditEntry:
    entry = GradeAuditEntry(
        exam_grade_id=exam_grade_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        previous_total_score=previous_total_score,
        new_total_score=new_total_score,
        changes=changes,
    )
    db.add(entry)
    if flush:
        await db.flush()
    return entry


async def list_audit_entries_by_grade(
    db: AsyncSession, exam_grade_id: UUID
) -> list[GradeAuditEntry]:
    result = await db.execute(
        select(GradeAuditEntry)
        .where(GradeAuditEntry.exam_grade_id == exam_grade_id)
        .order_by(GradeAuditEntry.created_at)
    )
    return list(result.scalars().all())
