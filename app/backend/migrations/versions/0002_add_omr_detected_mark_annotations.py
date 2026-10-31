"""add OMR detected mark annotations

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "omr_detected_marks",
        sa.Column("page_index", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "omr_detected_marks",
        sa.Column(
            "boxes",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
    )
    op.add_column(
        "omr_detected_marks",
        sa.Column(
            "bounds",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
    )
    op.drop_column("omr_detected_marks", "x")
    op.drop_column("omr_detected_marks", "y")
    op.drop_column("omr_detected_marks", "width")
    op.drop_column("omr_detected_marks", "height")


def downgrade() -> None:
    op.add_column("omr_detected_marks", sa.Column("x", sa.Integer(), nullable=True))
    op.add_column("omr_detected_marks", sa.Column("y", sa.Integer(), nullable=True))
    op.add_column(
        "omr_detected_marks",
        sa.Column("width", sa.Integer(), nullable=True),
    )
    op.add_column(
        "omr_detected_marks",
        sa.Column("height", sa.Integer(), nullable=True),
    )
    op.drop_column("omr_detected_marks", "bounds")
    op.drop_column("omr_detected_marks", "boxes")
    op.drop_column("omr_detected_marks", "page_index")
