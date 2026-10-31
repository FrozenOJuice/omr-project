from uuid import UUID

from sqlalchemy import desc
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models.course import Course
from models.enrolment import Enrolment
from models.exam import Exam
from models.password_reset_token import PasswordResetToken
from models.refresh_token import RefreshToken
from models.review_request import ReviewRequest
from models.scan import Scan
from models.user import AccountStatus
from models.user import Institution
from models.user import User
from models.user import UserRole


def is_email_conflict(exc: IntegrityError) -> bool:
    return "users_email_key" in str(exc)


def is_student_number_conflict(exc: IntegrityError) -> bool:
    message = str(exc)
    return (
        "uq_users_student_number" in message
        or "users_student_number_key" in message
    )


async def get_by_email(db: AsyncSession, email: str, for_update: bool = False):
    normalized_email = email.strip().lower()
    statement = select(User).where(User.email == normalized_email)

    if for_update:
        statement = statement.with_for_update()

    result = await db.execute(statement)

    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, user_id: UUID, for_update: bool = False):
    statement = select(User).where(User.id == user_id)

    if for_update:
        statement = statement.with_for_update()

    result = await db.execute(statement)

    return result.scalar_one_or_none()


async def get_users_by_ids(db: AsyncSession, user_ids: list[UUID]) -> list[User]:
    if not user_ids:
        return []
    result = await db.execute(select(User).where(User.id.in_(user_ids)))
    return list(result.scalars().all())


async def list_users(
    db: AsyncSession,
    *,
    search: str | None = None,
    role: UserRole | None = None,
    status: AccountStatus | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[User], int]:
    filters = _user_filters(search=search, role=role, status=status)

    count_statement = select(func.count()).select_from(User).where(*filters)
    count_result = await db.execute(count_statement)
    total = count_result.scalar_one()

    statement = (
        select(User)
        .where(*filters)
        .order_by(desc(User.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(statement)

    user_list = list(result.scalars().all())
    active_user_ids = await get_active_session_user_ids(
        db,
        [user.id for user in user_list],
    )

    for user in user_list:
        user.active_session = user.id in active_user_ids

    return user_list, total


async def get_active_session_user_ids(
    db: AsyncSession,
    user_ids: list[UUID],
) -> set[UUID]:
    if not user_ids:
        return set()

    result = await db.execute(
        select(RefreshToken.user_id)
        .where(
            RefreshToken.user_id.in_(user_ids),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
        .distinct()
    )

    return set(result.scalars().all())


async def list_active_admins(
    db: AsyncSession,
    for_update: bool = False,
) -> list[User]:
    statement = select(User).where(
        User.role == UserRole.ADMIN.value,
        User.status == AccountStatus.ACTIVE.value,
    )

    if for_update:
        statement = statement.with_for_update()

    result = await db.execute(statement)

    return list(result.scalars().all())


async def get_admin_summary(db: AsyncSession) -> dict[str, int]:
    total_result = await db.execute(select(func.count()).select_from(User))
    active_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.status == AccountStatus.ACTIVE.value)
    )
    disabled_result = await db.execute(
        select(func.count())
        .select_from(User)
        .where(User.status == AccountStatus.DISABLED.value)
    )
    active_sessions_result = await db.execute(
        select(func.count())
        .select_from(RefreshToken)
        .where(
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > func.now(),
        )
    )

    role_counts = {role: 0 for role in UserRole}
    role_result = await db.execute(
        select(User.role, func.count()).group_by(User.role)
    )
    for role_value, count in role_result.all():
        role_counts[UserRole(role_value)] = count

    return {
        "total_users": total_result.scalar_one(),
        "active_users": active_result.scalar_one(),
        "disabled_users": disabled_result.scalar_one(),
        "admins": role_counts[UserRole.ADMIN],
        "professors": role_counts[UserRole.PROFESSOR],
        "students": role_counts[UserRole.STUDENT],
        "active_sessions": active_sessions_result.scalar_one(),
    }


async def update_status(
    db: AsyncSession,
    user: User,
    status: AccountStatus,
) -> User:
    user.status = status.value

    await db.flush()
    await db.refresh(user)

    return user


async def update_role(
    db: AsyncSession,
    user: User,
    role: UserRole,
) -> User:
    user.role = role.value
    if role != UserRole.STUDENT:
        user.student_number = None

    await db.flush()
    await db.refresh(user)

    return user


async def update_account(
    db: AsyncSession,
    user: User,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
    student_number: str | None = None,
    institution: Institution | None = None,
) -> User:
    if first_name is not None:
        user.first_name = first_name.strip()

    if last_name is not None:
        user.last_name = last_name.strip()

    if email is not None:
        user.email = email.strip().lower()

    if student_number is not None:
        user.student_number = student_number.strip()

    if institution is not None:
        user.institution = institution.value

    await db.flush()
    await db.refresh(user)

    return user


async def get_delete_blockers(db: AsyncSession, user_id: UUID) -> list[str]:
    checks = [
        (
            "created courses",
            select(func.count()).select_from(Course).where(Course.created_by == user_id),
        ),
        (
            "uploaded scans",
            select(func.count()).select_from(Scan).where(Scan.uploader_user_id == user_id),
        ),
        (
            "review requests",
            select(func.count())
            .select_from(ReviewRequest)
            .where(ReviewRequest.student_id == user_id),
        ),
    ]

    blockers = []
    for label, statement in checks:
        result = await db.execute(statement)
        if result.scalar_one() > 0:
            blockers.append(label)

    return blockers


async def delete_account(db: AsyncSession, user: User) -> None:
    await db.execute(
        update(Exam)
        .where(Exam.created_by == user.id)
        .values(created_by=None)
    )
    await db.execute(delete(Enrolment).where(Enrolment.user_id == user.id))
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user.id)
        .values(replaced_by_token_id=None)
    )
    await db.execute(delete(RefreshToken).where(RefreshToken.user_id == user.id))
    await db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id)
    )
    await db.delete(user)


def create(
    db: AsyncSession,
    first_name: str,
    last_name: str,
    email: str,
    password_hash: str,
    role: UserRole = UserRole.STUDENT,
    status: AccountStatus = AccountStatus.ACTIVE,
    student_number: str | None = None,
):
    user = User(
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        email=email.strip().lower(),
        password_hash=password_hash,
        role=role.value,
        status=status.value,
        student_number=student_number.strip() if student_number else None,
    )

    db.add(user)

    return user


def _user_filters(
    *,
    search: str | None,
    role: UserRole | None,
    status: AccountStatus | None,
):
    filters = []
    normalized_search = search.strip() if search else None

    if normalized_search:
        pattern = f"%{normalized_search}%"
        filters.append(or_(
            User.first_name.ilike(pattern),
            User.last_name.ilike(pattern),
            User.email.ilike(pattern),
        ))

    if role:
        filters.append(User.role == role.value)

    if status:
        filters.append(User.status == status.value)

    return filters
