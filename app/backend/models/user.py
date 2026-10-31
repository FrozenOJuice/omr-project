from enum import StrEnum
from datetime import datetime
from typing import Optional
import uuid

from sqlalchemy import Boolean
from sqlalchemy import CheckConstraint
from sqlalchemy import DateTime
from sqlalchemy import String
from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


class UserRole(StrEnum):
    STUDENT = "student"
    PROFESSOR = "professor"
    ADMIN = "admin"


class AccountStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class Institution(StrEnum):
    UBC = "ubc"
    GENERIC = "generic"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "role IN ('student', 'professor', 'admin')",
            name="ck_users_role_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_users_status_valid",
        ),
        CheckConstraint(
            "institution IN ('ubc', 'generic')",
            name="ck_users_institution_valid",
        ),
        CheckConstraint(
            "student_number IS NULL OR student_number ~ '^[0-9]{8}$'",
            name="ck_users_student_number_format",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    first_name: Mapped[str] = mapped_column(String, nullable=False)
    last_name: Mapped[str] = mapped_column(String, nullable=False)
    # Institutional student number, decoded from OMR I# bubbles and matched
    # against this for exam identity matching. Only students have one.
    student_number: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=UserRole.STUDENT.value,
        server_default=UserRole.STUDENT.value,
    )
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=AccountStatus.ACTIVE.value,
        server_default=AccountStatus.ACTIVE.value,
    )
    institution: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default=Institution.UBC.value,
        server_default=Institution.UBC.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    password_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    email_notifications_enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
    )
    regrade_alerts_enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
    )
    batch_job_complete_enabled: Mapped[bool] = mapped_column(
        Boolean,
        server_default="true",
        nullable=False,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def role_enum(self) -> UserRole:
        return UserRole(self.role)

    @role_enum.setter
    def role_enum(self, role: UserRole) -> None:
        self.role = role.value

    @property
    def status_enum(self) -> AccountStatus:
        return AccountStatus(self.status)

    @status_enum.setter
    def status_enum(self, status: AccountStatus) -> None:
        self.status = status.value

    @property
    def institution_enum(self) -> Institution:
        return Institution(self.institution)

    @institution_enum.setter
    def institution_enum(self, institution: Institution) -> None:
        self.institution = institution.value
