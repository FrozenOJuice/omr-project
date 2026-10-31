from datetime import datetime
from datetime import timezone
from uuid import UUID

from core.datetime_utils import is_expired
from core.tokens import create_access_token
from core.tokens import create_refresh_token
from core.tokens import decode_access_token
from core.tokens import decode_refresh_token
from core.tokens import hash_token
from errors.exceptions import UnauthorizedError
from models.user import AccountStatus
from repositories import refresh_tokens
from repositories import users


async def refresh(db, refresh_token: str):
    user, persisted_token = await _get_refresh_token_context(
        db,
        refresh_token,
        for_update=True,
    )

    if persisted_token.revoked_at is not None:
        if persisted_token.replaced_by_token_id is not None:
            await revoke_all_active(db, user.id)

        raise _invalid_refresh_token()

    if is_expired(persisted_token.expires_at):
        raise _invalid_refresh_token()

    ensure_account_active(user)

    try:
        token_pair, new_refresh_token = await _create_token_pair_record(db, user)
        await db.flush()
        refresh_tokens.revoke(
            persisted_token,
            replaced_by_token_id=new_refresh_token.id,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return token_pair


async def logout(db, refresh_token: str) -> None:
    _, persisted_token = await _get_refresh_token_context(
        db,
        refresh_token,
        for_update=True,
    )

    if persisted_token.revoked_at is not None or is_expired(
        persisted_token.expires_at
    ):
        raise _invalid_refresh_token()

    try:
        refresh_tokens.revoke(persisted_token)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def logout_all(db, refresh_token: str) -> None:
    user, persisted_token = await _get_refresh_token_context(
        db,
        refresh_token,
        for_update=True,
    )

    if persisted_token.revoked_at is not None or is_expired(
        persisted_token.expires_at
    ):
        raise _invalid_refresh_token()

    await revoke_all_active(db, user.id)


async def revoke_all_active(db, user_id: UUID) -> None:
    try:
        await revoke_all_active_tokens(db, user_id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def revoke_all_active_tokens(db, user_id: UUID) -> None:
    await refresh_tokens.revoke_all_active_for_user(db, user_id)


async def get_current_user(db, access_token: str):
    try:
        payload = decode_access_token(access_token)
    except ValueError as exc:
        raise UnauthorizedError(
            "Invalid access token",
            code="invalid_access_token",
        ) from exc

    user = await _get_user_from_subject(db, payload.get("sub"))

    if not user:
        raise UnauthorizedError("Invalid access token", code="invalid_access_token")

    ensure_account_active(user)

    return user


async def issue_token_pair(db, user):
    try:
        token_pair = await create_token_pair(db, user)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return token_pair


async def create_token_pair(db, user):
    token_pair, _ = await _create_token_pair_record(db, user)

    return token_pair


def ensure_account_active(user) -> None:
    if user.status_enum != AccountStatus.ACTIVE:
        raise UnauthorizedError("Account is disabled", code="account_disabled")


async def _get_refresh_token_context(
    db,
    refresh_token: str,
    for_update: bool = False,
):
    try:
        payload = decode_refresh_token(refresh_token)
    except ValueError as exc:
        raise _invalid_refresh_token() from exc

    persisted_token = await refresh_tokens.get_by_token_hash(
        db,
        hash_token(refresh_token),
        for_update=for_update,
    )

    if not persisted_token:
        raise _invalid_refresh_token()

    user = await _get_user_from_subject(db, payload.get("sub"))

    if not user or persisted_token.user_id != user.id:
        raise _invalid_refresh_token()

    return user, persisted_token


async def _get_user_from_subject(db, subject: str | None):
    if not subject:
        return None

    try:
        user_id = UUID(subject)
    except (TypeError, ValueError):
        return None

    return await users.get_by_id(db, user_id)


async def _create_token_pair_record(db, user):
    subject = str(user.id)
    access_token = create_access_token(subject)
    refresh_token = create_refresh_token(subject)
    refresh_payload = decode_refresh_token(refresh_token)

    refresh_token_record = await refresh_tokens.create(
        db,
        user_id=user.id,
        token_hash=hash_token(refresh_token),
        jti=refresh_payload["jti"],
        expires_at=datetime.fromtimestamp(refresh_payload["exp"], tz=timezone.utc),
    )

    return (
        {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
        },
        refresh_token_record,
    )


def _invalid_refresh_token() -> UnauthorizedError:
    return UnauthorizedError(
        "Invalid refresh token",
        code="invalid_refresh_token",
    )
