from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import secrets

from core.datetime_utils import is_expired
from core.security import hash_password
from core.security import verify_password
from core.settings import settings
from core.tokens import hash_token
from errors.exceptions import BadRequestError
from models.user import AccountStatus
from repositories import password_reset_tokens
from repositories import refresh_tokens
from repositories import users
from schemas.auth_schema import ChangePasswordRequest
from schemas.auth_schema import PasswordResetConfirmRequest
from schemas.auth_schema import PasswordResetRequest
from services.email_service import EmailDeliveryError
from services.email_service import send_account_created_email
from services.email_service import send_password_reset_email

logger = logging.getLogger(__name__)


async def change_password(db, user, request: ChangePasswordRequest) -> None:
    if not verify_password(request.current_password, user.password_hash):
        raise BadRequestError(
            "Current password is incorrect",
            code="invalid_current_password",
        )

    if request.current_password == request.new_password:
        raise BadRequestError(
            "New password must be different from the current password",
            code="password_reuse",
        )

    try:
        user.password_hash = hash_password(request.new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        await refresh_tokens.revoke_all_active_for_user(db, user.id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def request_password_reset(
    db,
    request: PasswordResetRequest,
) -> tuple[str, str] | None:
    user = await users.get_by_email(db, request.email, for_update=True)

    if not user or user.status_enum != AccountStatus.ACTIVE:
        return None

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.password_reset_expire_seconds
    )

    try:
        await password_reset_tokens.revoke_active_for_user(db, user.id)
        password_reset_tokens.create(
            db,
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return user.email, token


async def deliver_password_reset_email(email: str, token: str) -> None:
    try:
        await send_password_reset_email(email, token)
    except EmailDeliveryError:
        logger.exception("event=password_reset_email_delivery_failed")


async def issue_activation_token(db, user) -> str:
    """Mint a long-lived reset token so a new account can set its own password.

    Shares the password reset token table on purpose: the confirm endpoint,
    single-use enforcement, and revocation all already work, and an activation
    link is a password reset the user didn't have to ask for.
    """
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(
        seconds=settings.account_activation_expire_seconds
    )

    await password_reset_tokens.revoke_active_for_user(db, user.id)
    password_reset_tokens.create(
        db,
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=expires_at,
    )

    return token


async def deliver_account_created_email(
    email: str,
    token: str,
    full_name: str,
    role: str,
) -> None:
    try:
        await send_account_created_email(
            email,
            full_name=full_name,
            role=role,
            token=token,
        )
    except EmailDeliveryError:
        logger.exception("event=account_created_email_delivery_failed")


async def confirm_password_reset(
    db,
    request: PasswordResetConfirmRequest,
) -> None:
    token_hash = hash_token(request.token)
    reset_token = await password_reset_tokens.get_by_token_hash(db, token_hash)

    if not reset_token:
        raise _invalid_reset_token()

    user = await users.get_by_id(db, reset_token.user_id, for_update=True)
    reset_token = await password_reset_tokens.get_by_token_hash(
        db,
        token_hash,
        for_update=True,
    )

    if (
        not user
        or user.status_enum != AccountStatus.ACTIVE
        or not _is_reset_token_valid(reset_token)
    ):
        raise _invalid_reset_token()

    if verify_password(request.new_password, user.password_hash):
        raise BadRequestError(
            "New password must be different from the current password",
            code="password_reuse",
        )

    try:
        user.password_hash = hash_password(request.new_password)
        user.password_changed_at = datetime.now(timezone.utc)
        password_reset_tokens.mark_used(reset_token)
        await db.flush()
        await password_reset_tokens.revoke_active_for_user(
            db,
            user.id,
            exclude_token_id=reset_token.id,
        )
        await refresh_tokens.revoke_all_active_for_user(db, user.id)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


def _is_reset_token_valid(reset_token) -> bool:
    if (
        not reset_token
        or reset_token.used_at is not None
        or reset_token.revoked_at is not None
    ):
        return False

    return not is_expired(reset_token.expires_at)


def _invalid_reset_token() -> BadRequestError:
    return BadRequestError(
        "Invalid or expired reset token",
        code="invalid_reset_token",
    )
