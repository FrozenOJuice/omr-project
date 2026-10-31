"""reconcile merged heads and add exam template archiving

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-25

The archive migration originally shipped with the same ``0007`` revision id
as the merge migration. Databases that ran that version already have
``exam_templates.archived_at`` but may not have the parallel
``review_requests.proposed_correct`` migration that the corrected ``0007``
merge now includes. Keep this migration conditional so both legacy databases
and fresh installs converge on the same schema without losing data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    review_request_columns = {
        column["name"] for column in inspector.get_columns("review_requests")
    }
    if "proposed_correct" not in review_request_columns:
        op.add_column(
            "review_requests",
            sa.Column("proposed_correct", sa.Boolean(), nullable=True),
        )

    exam_template_columns = {
        column["name"] for column in inspector.get_columns("exam_templates")
    }
    if "archived_at" not in exam_template_columns:
        op.add_column(
            "exam_templates",
            sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    exam_template_columns = {
        column["name"] for column in inspector.get_columns("exam_templates")
    }
    if "archived_at" in exam_template_columns:
        op.drop_column("exam_templates", "archived_at")
