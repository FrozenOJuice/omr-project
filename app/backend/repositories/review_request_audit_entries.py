from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.review_request_audit_entry import ReviewRequestAuditEntry


async def create_review_request_audit_entry(
    db: AsyncSession,
    review_request_id: UUID,
    actor_user_id: UUID | None,
    event_type: str,
    changes: dict,
) -> ReviewRequestAuditEntry:
    entry = ReviewRequestAuditEntry(
        review_request_id=review_request_id,
        actor_user_id=actor_user_id,
        event_type=event_type,
        changes=changes,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_review_request_audit_entries(
    db: AsyncSession, review_request_id: UUID
) -> list[ReviewRequestAuditEntry]:
    result = await db.execute(
        select(ReviewRequestAuditEntry)
        .where(ReviewRequestAuditEntry.review_request_id == review_request_id)
        .order_by(ReviewRequestAuditEntry.created_at)
    )
    return list(result.scalars().all())
