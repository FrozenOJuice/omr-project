from sqlalchemy.ext.asyncio import AsyncSession

from models.retention_policy import RetentionPolicySource
from models.user import User
from repositories import retention_policies
from schemas.retention_policy import (
    RetentionPolicyStatusResponse,
    RetentionPolicyUpsertRequest,
    UBC_EXAM_RECORD_RETENTION_MONTHS,
    UBC_SCANNED_IMAGE_RETENTION_MONTHS,
)


async def get_current_policy(
    db: AsyncSession,
    user: User,
) -> RetentionPolicyStatusResponse:
    policy = await retention_policies.get_by_owner_id(db, user.id)
    return RetentionPolicyStatusResponse(
        configured=policy is not None,
        policy=policy,
    )


async def upsert_current_policy(
    db: AsyncSession,
    user: User,
    request: RetentionPolicyUpsertRequest,
):
    uses_ubc_default = (
        request.scanned_image_retention_months
        == UBC_SCANNED_IMAGE_RETENTION_MONTHS
        and request.exam_record_retention_months
        == UBC_EXAM_RECORD_RETENTION_MONTHS
        and request.retain_anonymized_analytics
    )
    source = (
        RetentionPolicySource.UBC_DEFAULT.value
        if uses_ubc_default
        else RetentionPolicySource.CUSTOM.value
    )

    try:
        policy = await retention_policies.upsert(
            db,
            owner_user_id=user.id,
            scanned_image_retention_months=request.scanned_image_retention_months,
            exam_record_retention_months=request.exam_record_retention_months,
            retain_anonymized_analytics=request.retain_anonymized_analytics,
            source=source,
        )
        await db.commit()
        return policy
    except Exception:
        await db.rollback()
        raise


async def delete_current_policy(db: AsyncSession, user: User) -> None:
    policy = await retention_policies.get_by_owner_id(db, user.id)
    if policy is None:
        return

    try:
        await retention_policies.delete(db, policy)
        await db.commit()
    except Exception:
        await db.rollback()
        raise
