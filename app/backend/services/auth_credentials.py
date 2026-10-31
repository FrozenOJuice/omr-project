from sqlalchemy.exc import IntegrityError

from core.security import DUMMY_PASSWORD_HASH
from core.security import hash_password
from core.security import password_needs_rehash
from core.security import verify_password
from errors.exceptions import ConflictError
from errors.exceptions import UnauthorizedError
from models.user import AccountStatus
from models.user import UserRole
from repositories import users
from schemas.auth_schema import LoginRequest
from schemas.auth_schema import RegisterRequest
from services import auth_sessions
from services import course


async def register(db, request: RegisterRequest):
    existing_user = await users.get_by_email(db, request.email)

    if existing_user:
        raise ConflictError("User already exists", code="user_exists")

    user = users.create(
        db,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email),
        password_hash=hash_password(request.password),
        role=UserRole(request.role),
        student_number=request.student_number,
    )

    try:
        await db.flush()
        await course.claim_roster_entries_for_user(db, user)
        token_pair = await auth_sessions.create_token_pair(db, user)
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

    await db.refresh(user)

    return token_pair


async def authenticate(db, request: LoginRequest):
    user = await users.get_by_email(db, request.email)
    password_hash = user.password_hash if user else DUMMY_PASSWORD_HASH
    password_is_valid = verify_password(request.password, password_hash)

    if not user or not password_is_valid:
        raise UnauthorizedError("Invalid email or password", code="invalid_credentials")

    # Only disclose that the account is disabled once the password has been
    # proven correct — revealing this to a wrong-password guess would let an
    # attacker enumerate which emails have disabled accounts.
    if not _is_active(user):
        raise UnauthorizedError(
            "Your account has been disabled", code="account_disabled"
        )

    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(request.password)

    await course.claim_roster_entries_for_user(db, user)

    return await auth_sessions.issue_token_pair(db, user)


def _is_active(user) -> bool:
    return user.status_enum == AccountStatus.ACTIVE
