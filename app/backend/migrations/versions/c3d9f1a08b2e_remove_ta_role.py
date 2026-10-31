"""remove ta role

The TA role never gained any behavior distinct from professor (every staff
check already treated ta/professor/admin the same way), so it's being
dropped in favor of promoting a student directly to professor within a
course. Any existing 'ta' users/enrolments are converted to 'professor'
before the check constraints are tightened.

Revision ID: c3d9f1a08b2e
Revises: 0008
Create Date: 2026-07-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3d9f1a08b2e"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE users SET role = 'professor' WHERE role = 'ta'")
    op.execute("UPDATE enrolments SET role = 'professor' WHERE role = 'ta'")

    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('student', 'professor', 'admin')",
    )

    op.drop_constraint("ck_enrolments_role_valid", "enrolments", type_="check")
    op.create_check_constraint(
        "ck_enrolments_role_valid",
        "enrolments",
        "role IN ('student', 'professor')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_enrolments_role_valid", "enrolments", type_="check")
    op.create_check_constraint(
        "ck_enrolments_role_valid",
        "enrolments",
        "role IN ('student', 'ta', 'professor')",
    )

    op.drop_constraint("ck_users_role_valid", "users", type_="check")
    op.create_check_constraint(
        "ck_users_role_valid",
        "users",
        "role IN ('student', 'ta', 'professor', 'admin')",
    )
