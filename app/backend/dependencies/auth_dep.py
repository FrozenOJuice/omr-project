from collections.abc import Callable

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from errors.exceptions import ForbiddenError
from errors.exceptions import UnauthorizedError
from models.user import User
from models.user import UserRole
from services import auth_sessions

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError(
            "Invalid authorization header",
            code="invalid_authorization_header",
        )

    return await auth_sessions.get_current_user(db, credentials.credentials)


def require_roles(*allowed_roles: UserRole) -> Callable:
    allowed_role_values = set(allowed_roles)

    async def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role_enum not in allowed_role_values:
            raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

        return user

    return dependency


require_role = require_roles

require_student = require_role(UserRole.STUDENT)
require_professor = require_role(UserRole.PROFESSOR)
require_admin = require_role(UserRole.ADMIN)
require_staff = require_role(UserRole.PROFESSOR, UserRole.ADMIN)
require_admin_or_prof = require_role(UserRole.ADMIN, UserRole.PROFESSOR)
