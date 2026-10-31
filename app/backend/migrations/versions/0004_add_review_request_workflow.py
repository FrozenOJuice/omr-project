"""add review request workflow fields

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_requests",
        sa.Column("batch_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_review_requests_batch_id"),
        "review_requests",
        ["batch_id"],
        unique=False,
    )
    op.add_column(
        "review_requests",
        sa.Column("proposed_correct", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_requests", "proposed_correct")
    op.drop_index(op.f("ix_review_requests_batch_id"), table_name="review_requests")
    op.drop_column("review_requests", "batch_id")
