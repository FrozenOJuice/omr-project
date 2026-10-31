"""add omr_job_id to scans

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0013"
down_revision: Union[str, Sequence[str], None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "scans",
        sa.Column("omr_job_id", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scans", "omr_job_id")
