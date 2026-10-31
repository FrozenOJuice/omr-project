from datetime import datetime
from datetime import timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from models.password_reset_token import PasswordResetToken


def create(
    db: AsyncSession,
    user_id: UUID,
    token_hash: str,
    expires_at: datetime,
) -> PasswordResetToken:
    reset_token = PasswordResetToken(
        user_id=user_id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(reset_token)

    return reset_token


async def get_by_token_hash(
    db: AsyncSession,
    token_hash: str,
    for_update: bool = False,
):
    statement = select(PasswordResetToken).where(
        PasswordResetToken.token_hash == token_hash
    )

    if for_update:
        statement = statement.with_for_update()

    result = await db.execute(statement)

    return result.scalar_one_or_none()


async def revoke_active_for_user(
    db: AsyncSession,
    user_id: UUID,
    *,
    exclude_token_id: UUID | None = None,
    revoked_at: datetime | None = None,
) -> None:
    statement = update(PasswordResetToken).where(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
        PasswordResetToken.revoked_at.is_(None),
    )

    if exclude_token_id is not None:
        statement = statement.where(PasswordResetToken.id != exclude_token_id)

    await db.execute(
        statement.values(revoked_at=revoked_at or datetime.now(timezone.utc))
    )


def mark_used(
    reset_token: PasswordResetToken,
    used_at: datetime | None = None,
) -> None:
    reset_token.used_at = used_at or datetime.now(timezone.utc)
