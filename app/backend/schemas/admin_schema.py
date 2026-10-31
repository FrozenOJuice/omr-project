from datetime import datetime
from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import model_validator

from models.user import AccountStatus
from models.user import UserRole
from schemas.auth_schema import NormalizedEmail
from schemas.auth_schema import NormalizedPersonName
from schemas.auth_schema import NormalizedStudentNumber
from schemas.auth_schema import StrongPassword


class AdminUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    email: str
    role: UserRole
    status: AccountStatus
    student_number: str | None = None
    created_at: datetime
    active_session: bool = False


class AdminUserListResponse(BaseModel):
    items: list[AdminUserResponse]
    total: int
    limit: int
    offset: int


class AdminSummaryResponse(BaseModel):
    total_users: int
    active_users: int
    disabled_users: int
    admins: int
    professors: int
    students: int
    active_sessions: int


class CreateAdminUserRequest(BaseModel):
    first_name: NormalizedPersonName
    last_name: NormalizedPersonName
    email: NormalizedEmail
    password: StrongPassword
    role: UserRole = UserRole.STUDENT
    status: AccountStatus = AccountStatus.ACTIVE
    student_number: NormalizedStudentNumber | None = None

    @model_validator(mode="after")
    def validate_student_number_matches_role(self) -> "CreateAdminUserRequest":
        if self.role == UserRole.STUDENT and not self.student_number:
            raise ValueError("Student number is required for student accounts")

        if self.role != UserRole.STUDENT and self.student_number is not None:
            raise ValueError("Student number is only applicable to student accounts")

        return self


class UpdateAdminUserRequest(BaseModel):
    first_name: NormalizedPersonName | None = None
    last_name: NormalizedPersonName | None = None
    email: NormalizedEmail | None = None
    student_number: NormalizedStudentNumber | None = None


class UpdateUserRoleRequest(BaseModel):
    role: UserRole


class UpdateUserStatusRequest(BaseModel):
    status: AccountStatus


class CleanupArchivesRequest(BaseModel):
    confirmed: bool = False


class CleanupArchivesResponse(BaseModel):
    scanned_images: int
    exam_records: int
