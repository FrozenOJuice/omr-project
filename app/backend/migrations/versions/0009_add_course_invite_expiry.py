"""add course invite expiry

Revision ID: 0009
Revises: c3d9f1a08b2e
Create Date: 2026-07-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from core.settings import settings


revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "c3d9f1a08b2e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "courses",
        sa.Column(
            "invite_link_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Backfill existing links using the configured invite window so a deployment
    # that customized COURSE_INVITE_EXPIRE_SECONDS stays consistent with the
    # application default rather than a hardcoded seven days.
    op.execute(
        "UPDATE courses "
        "SET invite_link_expires_at = "
        f"NOW() + make_interval(secs => {int(settings.course_invite_expire_seconds)}) "
        "WHERE invite_link_expires_at IS NULL"
    )
    # server_default is a DB-side safety net for inserts that bypass the ORM;
    # normal course creation still supplies the configurable Python default.
    op.alter_column(
        "courses",
        "invite_link_expires_at",
        nullable=False,
        server_default=sa.text("now() + interval '7 days'"),
    )


def downgrade() -> None:
    op.drop_column("courses", "invite_link_expires_at")
