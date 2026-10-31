"""add site-wide branding settings

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0012"
down_revision: Union[str, Sequence[str], None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "site_branding",
        sa.Column("id", sa.SmallInteger(), nullable=False),
        sa.Column("logo_data", sa.LargeBinary(), nullable=True),
        sa.Column("logo_content_type", sa.String(length=32), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("id = 1", name="ck_site_branding_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute("INSERT INTO site_branding (id) VALUES (1)")


def downgrade() -> None:
    op.drop_table("site_branding")
