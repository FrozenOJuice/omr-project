"""add configurable retention management

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-19

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "retention_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "scanned_image_retention_months",
            sa.Integer(),
            server_default="12",
            nullable=False,
        ),
        sa.Column(
            "exam_record_retention_months",
            sa.Integer(),
            server_default="12",
            nullable=False,
        ),
        sa.Column(
            "retain_anonymized_analytics",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(),
            server_default="ubc_default",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "scanned_image_retention_months BETWEEN 12 AND 72",
            name="ck_retention_policies_scanned_image_months",
        ),
        sa.CheckConstraint(
            "exam_record_retention_months BETWEEN 12 AND 72",
            name="ck_retention_policies_exam_record_months",
        ),
        sa.CheckConstraint(
            "source IN ('ubc_default', 'custom')",
            name="ck_retention_policies_source_valid",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            name="uq_retention_policies_owner_user_id",
        ),
    )

    op.add_column("courses", sa.Column("archived_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("courses", sa.Column("retention_policy_id", sa.Uuid(), nullable=True))
    op.add_column(
        "courses",
        sa.Column(
            "retention_policy_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "courses",
        sa.Column(
            "scanned_images_retention_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "courses",
        sa.Column(
            "exam_records_retention_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "courses",
        sa.Column("scanned_images_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("exam_records_purged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column("retention_processed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "courses",
        sa.Column(
            "retained_analytics",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.create_foreign_key(
        "fk_courses_archived_by_user_id_users",
        "courses",
        "users",
        ["archived_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_courses_retention_policy_id_retention_policies",
        "courses",
        "retention_policies",
        ["retention_policy_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_courses_scanned_images_retention_until",
        "courses",
        ["scanned_images_retention_until"],
        unique=False,
    )
    op.create_index(
        "ix_courses_exam_records_retention_until",
        "courses",
        ["exam_records_retention_until"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_courses_exam_records_retention_until", table_name="courses")
    op.drop_index("ix_courses_scanned_images_retention_until", table_name="courses")
    op.drop_constraint(
        "fk_courses_retention_policy_id_retention_policies",
        "courses",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_courses_archived_by_user_id_users",
        "courses",
        type_="foreignkey",
    )
    op.drop_column("courses", "retained_analytics")
    op.drop_column("courses", "retention_processed_at")
    op.drop_column("courses", "exam_records_purged_at")
    op.drop_column("courses", "scanned_images_purged_at")
    op.drop_column("courses", "exam_records_retention_until")
    op.drop_column("courses", "scanned_images_retention_until")
    op.drop_column("courses", "retention_policy_snapshot")
    op.drop_column("courses", "retention_policy_id")
    op.drop_column("courses", "archived_by_user_id")
    op.drop_table("retention_policies")
