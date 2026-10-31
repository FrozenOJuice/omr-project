import re
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AfterValidator
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import EmailStr
from pydantic import Field
from pydantic import model_validator

from models.user import Institution


def normalize_email(email: EmailStr) -> str:
    return str(email).strip().lower()


def normalize_person_name(name: str) -> str:
    normalized = name.strip()

    if not normalized:
        raise ValueError("Name is required")

    return normalized


_STUDENT_NUMBER_PATTERN = re.compile(r"^\d{8}$")


def normalize_student_number(student_number: str) -> str:
    normalized = student_number.strip()

    if not _STUDENT_NUMBER_PATTERN.fullmatch(normalized):
        raise ValueError("Student number must be exactly 8 digits")

    return normalized


def validate_password_strength(password: str) -> str:
    has_uppercase = any(char.isupper() for char in password)
    has_lowercase = any(char.islower() for char in password)
    has_number = any(char.isdigit() for char in password)
    has_special = any(
        not char.isalnum() and not char.isspace()
        for char in password
    )

    if not has_uppercase:
        raise ValueError("Password must contain at least one uppercase letter")

    if not has_lowercase:
        raise ValueError("Password must contain at least one lowercase letter")

    if not has_number:
        raise ValueError("Password must contain at least one number")

    if not has_special:
        raise ValueError("Password must contain at least one special character")

    return password


NormalizedEmail = Annotated[EmailStr, AfterValidator(normalize_email)]
StrongPassword = Annotated[
    str,
    Field(min_length=12, max_length=128),
    AfterValidator(validate_password_strength),
]
NormalizedPersonName = Annotated[
    str,
    Field(min_length=1, max_length=100),
    AfterValidator(normalize_person_name),
]
NormalizedStudentNumber = Annotated[str, AfterValidator(normalize_student_number)]


class RegisterRequest(BaseModel):
    first_name: NormalizedPersonName
    last_name: NormalizedPersonName
    email: NormalizedEmail
    password: StrongPassword
    role: Literal['student', 'professor'] = 'student'
    student_number: NormalizedStudentNumber | None = None

    @model_validator(mode="after")
    def validate_student_number_matches_role(self) -> "RegisterRequest":
        if self.role == 'student' and not self.student_number:
            raise ValueError("Student number is required for student accounts")

        if self.role != 'student' and self.student_number is not None:
            raise ValueError("Student number is only applicable to student accounts")

        return self


class LoginRequest(BaseModel):
    email: NormalizedEmail
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: StrongPassword


class PasswordResetRequest(BaseModel):
    email: NormalizedEmail


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=512)
    new_password: StrongPassword


class PasswordResetRequestResponse(BaseModel):
    message: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UpdateMeRequest(BaseModel):
    first_name: NormalizedPersonName | None = None
    last_name: NormalizedPersonName | None = None
    email: NormalizedEmail | None = None
    student_number: NormalizedStudentNumber | None = None
    institution: Institution | None = None


class UpdateNotificationPreferencesRequest(BaseModel):
    email_notifications_enabled: bool
    regrade_alerts_enabled: bool
    batch_job_complete_enabled: bool


class CurrentUserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    first_name: str
    last_name: str
    email: EmailStr
    role: str
    status: str
    student_number: str | None = None
    password_changed_at: datetime
    email_notifications_enabled: bool
    regrade_alerts_enabled: bool
    batch_job_complete_enabled: bool
    institution: Institution
