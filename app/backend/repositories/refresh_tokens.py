from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.refresh_token import RefreshToken


async def create(
    db: AsyncSession,
    user_id: UUID,
    token_hash: str,
    jti: str,
    expires_at: datetime,
):
    refresh_token = RefreshToken(
        user_id=user_id,
        token_hash=token_hash,
        jti=jti,
        expires_at=expires_at,
    )

    db.add(refresh_token)

    return refresh_token


async def get_by_token_hash(
    db: AsyncSession,
    token_hash: str,
    for_update: bool = False,
):
    statement = select(RefreshToken).where(RefreshToken.token_hash == token_hash)

    if for_update:
        statement = statement.with_for_update()

    result = await db.execute(statement)

    return result.scalar_one_or_none()


def revoke(
    refresh_token: RefreshToken,
    replaced_by_token_id: UUID | None = None,
    revoked_at: datetime | None = None,
):
    refresh_token.revoked_at = revoked_at or datetime.now(timezone.utc)
    refresh_token.replaced_by_token_id = replaced_by_token_id

    return refresh_token


async def revoke_all_active_for_user(
    db: AsyncSession,
    user_id: UUID,
    revoked_at: datetime | None = None,
):
    revoked_at = revoked_at or datetime.now(timezone.utc)

    await db.execute(
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user_id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
        .values(revoked_at=revoked_at)
    )
