from uuid import UUID

from sqlalchemy.exc import IntegrityError

from core.security import hash_password
from dependencies.rate_limit import clear_login_rate_limit
from errors.exceptions import BadRequestError
from errors.exceptions import ConflictError
from errors.exceptions import NotFoundError
from models.user import AccountStatus
from models.user import Institution
from models.user import UserRole
from repositories import users
from services import auth_passwords
from services import auth_sessions


async def list_users(
    db,
    *,
    search: str | None = None,
    role: UserRole | None = None,
    status: AccountStatus | None = None,
    limit: int = 50,
    offset: int = 0,
):
    user_list, total = await users.list_users(
        db,
        search=search,
        role=role,
        status=status,
        limit=limit,
        offset=offset,
    )

    return {
        "items": user_list,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


async def get_summary(db):
    return await users.get_admin_summary(db)


async def get_user(db, user_id: UUID):
    user = await users.get_by_id(db, user_id)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    return user


async def logout_user_sessions(db, user_id: UUID) -> None:
    user = await users.get_by_id(db, user_id)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    await auth_sessions.revoke_all_active(db, user.id)


async def delete_user(db, user_id: UUID, actor) -> None:
    user = await users.get_by_id(db, user_id, for_update=True)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if user.id == actor.id:
        raise BadRequestError(
            "Cannot delete your own account",
            code="cannot_delete_self",
        )

    blockers = await users.get_delete_blockers(db, user.id)
    if blockers:
        raise ConflictError(
            "Cannot delete user with existing academic records",
            code="user_has_records",
            details={"records": blockers},
        )

    try:
        if user.role_enum == UserRole.ADMIN and user.status_enum == AccountStatus.ACTIVE:
            await _ensure_not_last_active_admin(db)

        await users.delete_account(db, user)
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def create_user(
    db,
    *,
    first_name: str,
    last_name: str,
    email: str,
    password: str,
    role: UserRole,
    status: AccountStatus,
    student_number: str | None = None,
):
    existing_user = await users.get_by_email(db, email)

    if existing_user:
        raise ConflictError("User already exists", code="user_exists")

    user = users.create(
        db,
        first_name=first_name,
        last_name=last_name,
        email=email,
        password_hash=hash_password(password),
        role=role,
        status=status,
        student_number=student_number,
    )

    try:
        await db.flush()
        await db.refresh(user)
        # Minted inside the same transaction as the account so a committed user
        # always has a usable activation link, even if the email itself bounces.
        activation_token = await auth_passwords.issue_activation_token(db, user)
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        if users.is_email_conflict(exc):
            raise ConflictError("User already exists", code="user_exists") from exc

        if users.is_student_number_conflict(exc):
            raise ConflictError(
                "Student number already in use", code="student_number_exists"
            ) from exc

        raise

    return user, activation_token


async def update_user_account(
    db,
    user_id: UUID,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    student_number: str | None = None,
    institution: Institution | None = None,
):
    if (
        first_name is None
        and last_name is None
        and email is None
        and student_number is None
        and institution is None
    ):
        raise BadRequestError("No user updates provided", code="no_user_updates")

    user = await users.get_by_id(db, user_id, for_update=True)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if email is not None:
        existing_user = await users.get_by_email(db, email)

        if existing_user and existing_user.id != user.id:
            raise ConflictError("User already exists", code="user_exists")

    try:
        updated_user = await users.update_account(
            db,
            user,
            first_name=first_name,
            last_name=last_name,
            email=email,
            student_number=student_number,
            institution=institution,
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()

        if users.is_email_conflict(exc):
            raise ConflictError("User already exists", code="user_exists") from exc

        if users.is_student_number_conflict(exc):
            raise ConflictError(
                "Student number already in use", code="student_number_exists"
            ) from exc

        raise
    except Exception:
        await db.rollback()
        raise

    return updated_user


async def update_user_status(
    db,
    user_id: UUID,
    status: AccountStatus,
    actor,
):
    user = await users.get_by_id(db, user_id, for_update=True)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if user.id == actor.id and status == AccountStatus.DISABLED:
        raise BadRequestError(
            "Cannot disable your own account",
            code="cannot_disable_self",
        )

    was_active = user.status_enum == AccountStatus.ACTIVE
    activation_token = None

    try:
        if _removes_active_admin_status(user, status):
            await _ensure_not_last_active_admin(db)

        updated_user = await users.update_status(db, user, status)

        if status == AccountStatus.DISABLED:
            await auth_sessions.revoke_all_active_tokens(db, user.id)
        elif status == AccountStatus.ACTIVE and not was_active:
            # The account is being activated. An account created as disabled
            # never got its setup email, so mint a fresh activation token now
            # and let the caller deliver it.
            activation_token = await auth_passwords.issue_activation_token(
                db, updated_user
            )

        await db.commit()
    except Exception:
        await db.rollback()
        raise

    if status == AccountStatus.ACTIVE:
        # Login attempts made while the account was disabled shouldn't count
        # against the user once an admin re-enables it.
        clear_login_rate_limit(updated_user.email)

    return updated_user, activation_token


async def resend_setup_email(db, user_id: UUID):
    """Re-issue a set-password activation token for an active account.

    Gives an admin a recovery action when the original setup email failed to
    send. Returns the user and a fresh token for the caller to deliver.
    """
    user = await users.get_by_id(db, user_id, for_update=True)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if user.status_enum != AccountStatus.ACTIVE:
        raise BadRequestError(
            "Only active accounts can receive a setup email.",
            code="account_not_active",
        )

    try:
        token = await auth_passwords.issue_activation_token(db, user)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return user, token


async def update_user_role(db, user_id: UUID, role: UserRole, actor):
    user = await users.get_by_id(db, user_id, for_update=True)

    if not user:
        raise NotFoundError("User not found", code="user_not_found")

    if user.id == actor.id:
        raise BadRequestError(
            "Cannot change your own role",
            code="cannot_change_own_role",
        )

    if _is_professor_to_student_switch(user.role_enum, role):
        raise BadRequestError(
            "Cannot change a professor directly into a student because a "
            "student number is required.",
            code="professor_student_switch_forbidden",
        )

    try:
        if _removes_active_admin_role(user, role):
            await _ensure_not_last_active_admin(db)

        updated_user = await users.update_role(db, user, role)
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return updated_user


def _removes_active_admin_status(user, status: AccountStatus) -> bool:
    return (
        user.role_enum == UserRole.ADMIN
        and user.status_enum == AccountStatus.ACTIVE
        and status == AccountStatus.DISABLED
    )


def _removes_active_admin_role(user, role: UserRole) -> bool:
    return (
        user.role_enum == UserRole.ADMIN
        and user.status_enum == AccountStatus.ACTIVE
        and role != UserRole.ADMIN
    )


def _is_professor_to_student_switch(
    current_role: UserRole,
    new_role: UserRole,
) -> bool:
    return current_role == UserRole.PROFESSOR and new_role == UserRole.STUDENT


async def _ensure_not_last_active_admin(db) -> None:
    active_admins = await users.list_active_admins(db, for_update=True)

    if len(active_admins) <= 1:
        raise ConflictError(
            "Cannot remove the last active administrator",
            code="last_active_admin",
        )
