"""add Canvas integration

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canvas_connections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_user_id", sa.String(), nullable=True),
        sa.Column("canvas_user_name", sa.String(), nullable=True),
        sa.Column("canvas_user_login_id", sa.String(), nullable=True),
        sa.Column("access_token_encrypted", sa.Text(), nullable=True),
        sa.Column("connected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id"),
    )

    op.add_column(
        "courses",
        sa.Column("source", sa.String(), server_default="omr", nullable=False),
    )
    op.create_check_constraint(
        "ck_courses_source_valid",
        "courses",
        "source IN ('omr', 'canvas')",
    )
    op.create_table(
        "canvas_course_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_connection_id", sa.Uuid(), nullable=True),
        sa.Column("owner_user_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_course_id", sa.String(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["canvas_connection_id"],
            ["canvas_connections.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_user_id",
            "canvas_course_id",
            name="uq_canvas_course_links_owner_course",
        ),
        sa.UniqueConstraint("course_id"),
    )

    op.add_column(
        "course_roster_entries",
        sa.Column("canvas_user_id", sa.String(), nullable=True),
    )
    op.add_column(
        "course_roster_entries",
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
    )
    op.add_column(
        "course_roster_entries",
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(
        "ck_course_roster_entries_source_valid",
        "course_roster_entries",
        type_="check",
    )
    op.create_check_constraint(
        "ck_course_roster_entries_source_valid",
        "course_roster_entries",
        "source IN ('manual', 'csv', 'invite', 'canvas')",
    )
    op.create_unique_constraint(
        "uq_course_roster_entries_course_canvas_user",
        "course_roster_entries",
        ["course_id", "canvas_user_id"],
    )

    op.create_table(
        "canvas_assignment_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("course_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_assignment_id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("points_possible", sa.Float(), nullable=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("html_url", sa.String(), nullable=True),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "canvas_assignment_id",
            name="uq_canvas_assignment_links_course_assignment",
        ),
    )
    op.create_table(
        "canvas_grade_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("exam_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_assignment_link_id", sa.Uuid(), nullable=False),
        sa.Column("last_sent_count", sa.Integer(), nullable=False),
        sa.Column("last_skipped_count", sa.Integer(), nullable=False),
        sa.Column("last_failed_count", sa.Integer(), nullable=False),
        sa.Column("first_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["canvas_assignment_link_id"],
            ["canvas_assignment_links.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["exam_id"], ["exams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "canvas_assignment_link_id",
            name="uq_canvas_grade_releases_assignment",
        ),
        sa.UniqueConstraint("exam_id", name="uq_canvas_grade_releases_exam"),
    )
    op.create_table(
        "canvas_grade_release_attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("canvas_grade_release_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("sent_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'partial', 'failed')",
            name="ck_canvas_grade_release_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["canvas_grade_release_id"],
            ["canvas_grade_releases.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "canvas_grade_release_recipients",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("canvas_user_id", sa.String(), nullable=False),
        sa.Column("percentage", sa.Float(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error_code", sa.String(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sent', 'failed')",
            name="ck_canvas_grade_release_recipients_status",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["canvas_grade_release_attempts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "attempt_id",
            "canvas_user_id",
            name="uq_canvas_grade_release_recipients_attempt_user",
        ),
    )


def downgrade() -> None:
    op.drop_table("canvas_grade_release_recipients")
    op.drop_table("canvas_grade_release_attempts")
    op.drop_table("canvas_grade_releases")
    op.drop_table("canvas_assignment_links")

    op.drop_constraint(
        "uq_course_roster_entries_course_canvas_user",
        "course_roster_entries",
        type_="unique",
    )
    op.drop_constraint(
        "ck_course_roster_entries_source_valid",
        "course_roster_entries",
        type_="check",
    )
    op.execute(
        "UPDATE course_roster_entries SET source = 'manual' WHERE source = 'canvas'"
    )
    op.create_check_constraint(
        "ck_course_roster_entries_source_valid",
        "course_roster_entries",
        "source IN ('manual', 'csv', 'invite')",
    )
    op.drop_column("course_roster_entries", "invited_at")
    op.drop_column("course_roster_entries", "active")
    op.drop_column("course_roster_entries", "canvas_user_id")

    op.drop_table("canvas_course_links")
    op.drop_constraint("ck_courses_source_valid", "courses", type_="check")
    op.drop_column("courses", "source")
    op.drop_table("canvas_connections")
