"""make exam schedule optional

Revision ID: 0010
Revises: 0009
"""

from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.alter_column(
        "exams",
        "start_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )
    op.alter_column(
        "exams",
        "end_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def downgrade() -> None:
    # The old schema requires a complete schedule. Give any unscheduled exams
    # a deterministic one-hour placeholder before restoring NOT NULL.
    op.execute(
        """
        UPDATE exams
        SET start_time = COALESCE(start_time, created_at),
            end_time = COALESCE(end_time, COALESCE(start_time, created_at) + INTERVAL '1 hour')
        WHERE start_time IS NULL OR end_time IS NULL
        """
    )
    op.alter_column(
        "exams",
        "end_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "exams",
        "start_time",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
