from uuid import UUID

from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Query

from db.session import get_db
from dependencies.auth_dep import require_admin
from dependencies.storage_dep import get_storage_repo
from errors.exceptions import BadRequestError
from models.user import User
from models.user import AccountStatus
from models.user import UserRole
from schemas.admin_schema import AdminUserResponse
from schemas.admin_schema import AdminUserListResponse
from schemas.admin_schema import AdminSummaryResponse
from schemas.admin_schema import CreateAdminUserRequest
from schemas.admin_schema import CleanupArchivesRequest
from schemas.admin_schema import CleanupArchivesResponse
from schemas.admin_schema import UpdateAdminUserRequest
from schemas.admin_schema import UpdateUserRoleRequest
from schemas.admin_schema import UpdateUserStatusRequest
from services import admin_users
from services import auth_passwords
from services.retention_processor import process_due_retention

router = APIRouter(
    prefix="/api/admin",
    tags=["admin"],
)


def _queue_setup_email(background_tasks: BackgroundTasks, user: User, token: str) -> None:
    background_tasks.add_task(
        auth_passwords.deliver_account_created_email,
        user.email,
        token,
        user.full_name,
        user.role_enum.value,
    )


@router.get("/summary", response_model=AdminSummaryResponse)
async def get_summary(
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_users.get_summary(db)


@router.post(
    "/courses/cleanup-archives",
    response_model=CleanupArchivesResponse,
)
async def cleanup_archived_courses(
    request: CleanupArchivesRequest,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
    storage=Depends(get_storage_repo),
):
    if not request.confirmed:
        raise BadRequestError(
            "Confirm archive cleanup before continuing.",
            code="archive_cleanup_confirmation_required",
        )

    return await process_due_retention(db, storage)


@router.get("/users", response_model=AdminUserListResponse)
async def list_users(
    search: str | None = Query(default=None, min_length=1, max_length=100),
    role: UserRole | None = None,
    status: AccountStatus | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_users.list_users(
        db,
        search=search,
        role=role,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.post("/users", response_model=AdminUserResponse, status_code=201)
async def create_user(
    request: CreateAdminUserRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    user, activation_token = await admin_users.create_user(
        db,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email),
        password=request.password,
        role=request.role,
        status=request.status,
        student_number=request.student_number,
    )

    # The setup link reuses the password-reset confirm flow, which rejects
    # non-active accounts. Emailing a disabled account would send a link that
    # can't be redeemed, so only active accounts get the setup email; disabled
    # accounts get theirs when an admin activates them (see update_user_status).
    if user.status_enum == AccountStatus.ACTIVE:
        _queue_setup_email(background_tasks, user, activation_token)

    return user


@router.get("/users/{user_id}", response_model=AdminUserResponse)
async def get_user(
    user_id: UUID,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_users.get_user(db, user_id)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def update_user_account(
    user_id: UUID,
    request: UpdateAdminUserRequest,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_users.update_user_account(
        db,
        user_id,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email) if request.email is not None else None,
        student_number=request.student_number,
    )


@router.patch("/users/{user_id}/status", response_model=AdminUserResponse)
async def update_user_status(
    user_id: UUID,
    request: UpdateUserStatusRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    user, activation_token = await admin_users.update_user_status(
        db, user_id, request.status, admin
    )

    # Activating a previously-disabled account is when it finally gets its
    # setup email — the account couldn't use the link while disabled.
    if activation_token is not None:
        _queue_setup_email(background_tasks, user, activation_token)

    return user


@router.post("/users/{user_id}/resend-setup-email", status_code=202)
async def resend_setup_email(
    user_id: UUID,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    user, token = await admin_users.resend_setup_email(db, user_id)
    _queue_setup_email(background_tasks, user, token)
    return {"message": f"Setup email queued for {user.email}."}


@router.patch("/users/{user_id}/role", response_model=AdminUserResponse)
async def update_user_role(
    user_id: UUID,
    request: UpdateUserRoleRequest,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    return await admin_users.update_user_role(db, user_id, request.role, admin)


@router.post("/users/{user_id}/logout-all", status_code=204)
async def logout_user_sessions(
    user_id: UUID,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    await admin_users.logout_user_sessions(db, user_id)


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: UUID,
    db=Depends(get_db),
    admin: User = Depends(require_admin),
):
    await admin_users.delete_user(db, user_id, admin)
