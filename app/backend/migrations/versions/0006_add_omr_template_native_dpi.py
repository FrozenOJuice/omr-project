"""add native_dpi to omr_templates

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, Sequence[str], None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "omr_templates",
        sa.Column("native_dpi", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("omr_templates", "native_dpi")
