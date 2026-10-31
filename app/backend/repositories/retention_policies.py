from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.retention_policy import RetentionPolicy


async def get_by_owner_id(
    db: AsyncSession,
    owner_user_id: UUID,
) -> RetentionPolicy | None:
    result = await db.execute(
        select(RetentionPolicy).where(
            RetentionPolicy.owner_user_id == owner_user_id
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    db: AsyncSession,
    *,
    owner_user_id: UUID,
    scanned_image_retention_months: int,
    exam_record_retention_months: int,
    retain_anonymized_analytics: bool,
    source: str,
) -> RetentionPolicy:
    policy = await get_by_owner_id(db, owner_user_id)
    if policy is None:
        policy = RetentionPolicy(owner_user_id=owner_user_id)
        db.add(policy)

    policy.scanned_image_retention_months = scanned_image_retention_months
    policy.exam_record_retention_months = exam_record_retention_months
    policy.retain_anonymized_analytics = retain_anonymized_analytics
    policy.source = source
    await db.flush()
    await db.refresh(policy)
    return policy


async def delete(db: AsyncSession, policy: RetentionPolicy) -> None:
    await db.delete(policy)
    await db.flush()
