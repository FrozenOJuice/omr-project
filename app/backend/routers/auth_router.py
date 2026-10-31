from fastapi import APIRouter
from fastapi import BackgroundTasks
from fastapi import Depends
from fastapi import Request
from fastapi import status

from dependencies.auth_dep import get_current_user
from dependencies.rate_limit import enforce_auth_rate_limit
from db.session import get_db
from models.user import User
from schemas.auth_schema import ChangePasswordRequest
from schemas.auth_schema import CurrentUserResponse
from schemas.auth_schema import LoginRequest
from schemas.auth_schema import PasswordResetConfirmRequest
from schemas.auth_schema import PasswordResetRequest
from schemas.auth_schema import PasswordResetRequestResponse
from schemas.auth_schema import RefreshRequest
from schemas.auth_schema import RegisterRequest
from schemas.auth_schema import TokenResponse
from schemas.auth_schema import UpdateMeRequest
from schemas.auth_schema import UpdateNotificationPreferencesRequest
from services import admin_users
from services import auth_credentials
from services import auth_passwords
from services import auth_preferences
from services import auth_sessions

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(
    http_request: Request,
    request: RegisterRequest,
    db=Depends(get_db),
):
    enforce_auth_rate_limit(http_request, "register")

    return await auth_credentials.register(db, request)


@router.post("/login", response_model=TokenResponse)
async def login(
    http_request: Request,
    request: LoginRequest,
    db=Depends(get_db),
):
    enforce_auth_rate_limit(http_request, "login", email=request.email)

    return await auth_credentials.authenticate(db, request)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    http_request: Request,
    request: RefreshRequest,
    db=Depends(get_db),
):
    enforce_auth_rate_limit(http_request, "refresh")

    return await auth_sessions.refresh(db, request.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: RefreshRequest, db=Depends(get_db)):
    await auth_sessions.logout(db, request.refresh_token)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(request: RefreshRequest, db=Depends(get_db)):
    await auth_sessions.logout_all(db, request.refresh_token)


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    request: ChangePasswordRequest,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    await auth_passwords.change_password(db, user, request)


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def request_password_reset(
    http_request: Request,
    request: PasswordResetRequest,
    background_tasks: BackgroundTasks,
    db=Depends(get_db),
):
    enforce_auth_rate_limit(
        http_request,
        "password_reset_request",
        email=request.email,
    )
    delivery = await auth_passwords.request_password_reset(db, request)

    if delivery:
        email, token = delivery
        background_tasks.add_task(
            auth_passwords.deliver_password_reset_email,
            email,
            token,
        )

    return {
        "message": "If an account exists for that email, a reset link has been sent."
    }


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def confirm_password_reset(
    http_request: Request,
    request: PasswordResetConfirmRequest,
    db=Depends(get_db),
):
    enforce_auth_rate_limit(http_request, "password_reset_confirm")
    await auth_passwords.confirm_password_reset(db, request)


@router.get("/me", response_model=CurrentUserResponse)
async def me(user: User = Depends(get_current_user)):
    return user


@router.patch("/me", response_model=CurrentUserResponse)
async def update_me(
    request: UpdateMeRequest,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await admin_users.update_user_account(
        db,
        user.id,
        first_name=request.first_name,
        last_name=request.last_name,
        email=str(request.email) if request.email is not None else None,
        student_number=request.student_number,
        institution=request.institution,
    )


@router.patch("/me/preferences", response_model=CurrentUserResponse)
async def update_notification_preferences(
    request: UpdateNotificationPreferencesRequest,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await auth_preferences.update_notification_preferences(db, user, request)
