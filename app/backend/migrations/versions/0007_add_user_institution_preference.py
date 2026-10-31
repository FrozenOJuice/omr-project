"""add institution preferences and academic terms

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-26

"""
from typing import Sequence, Union
import uuid

import sqlalchemy as sa
from alembic import op


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "institution",
            sa.String(),
            server_default="ubc",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_users_institution_valid",
        "users",
        "institution IN ('ubc', 'generic')",
    )

    op.create_table(
        "academic_terms",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("institution", sa.String(), server_default="ubc", nullable=False),
        sa.Column("code", sa.String(), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("normalized_name", sa.String(), nullable=False),
        sa.Column("term_type", sa.String(), nullable=False),
        sa.Column("year_format", sa.String(), server_default="start_year", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "institution IN ('ubc', 'generic')",
            name="ck_academic_terms_institution_valid",
        ),
        sa.CheckConstraint(
            "term_type IN ('preset', 'custom')",
            name="ck_academic_terms_type_valid",
        ),
        sa.CheckConstraint(
            "year_format IN ('academic_year_range', 'following_year', 'start_year', 'none')",
            name="ck_academic_terms_year_format_valid",
        ),
        sa.CheckConstraint(
            "length(btrim(name)) > 0",
            name="ck_academic_terms_name_not_blank",
        ),
        sa.CheckConstraint(
            "length(normalized_name) > 0",
            name="ck_academic_terms_normalized_name_not_blank",
        ),
        sa.CheckConstraint(
            "(term_type = 'preset' AND code IS NOT NULL AND created_by IS NULL) "
            "OR (term_type = 'custom' AND code IS NULL)",
            name="ck_academic_terms_type_fields_valid",
        ),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "institution",
            "code",
            name="uq_academic_terms_institution_code",
        ),
        sa.UniqueConstraint(
            "institution",
            "created_by",
            "normalized_name",
            name="uq_academic_terms_owner_name",
        ),
    )

    academic_terms = sa.table(
        "academic_terms",
        sa.column("id", sa.Uuid()),
        sa.column("institution", sa.String()),
        sa.column("code", sa.String()),
        sa.column("name", sa.String()),
        sa.column("normalized_name", sa.String()),
        sa.column("term_type", sa.String()),
        sa.column("year_format", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_by", sa.Uuid()),
    )
    op.bulk_insert(
        academic_terms,
        [
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000001"),
                "institution": "ubc",
                "code": "winter-session-1",
                "name": "Winter Session 1",
                "normalized_name": "winter session 1",
                "term_type": "preset",
                "year_format": "academic_year_range",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000002"),
                "institution": "ubc",
                "code": "winter-session-2",
                "name": "Winter Session 2",
                "normalized_name": "winter session 2",
                "term_type": "preset",
                "year_format": "academic_year_range",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000003"),
                "institution": "ubc",
                "code": "winter-sessions-1-and-2",
                "name": "Winter Session 1 + 2",
                "normalized_name": "winter session 1 + 2",
                "term_type": "preset",
                "year_format": "academic_year_range",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000004"),
                "institution": "ubc",
                "code": "summer-session-1",
                "name": "Summer Session 1",
                "normalized_name": "summer session 1",
                "term_type": "preset",
                "year_format": "following_year",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000005"),
                "institution": "ubc",
                "code": "summer-session-2",
                "name": "Summer Session 2",
                "normalized_name": "summer session 2",
                "term_type": "preset",
                "year_format": "following_year",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000006"),
                "institution": "ubc",
                "code": "summer-sessions-1-and-2",
                "name": "Summer Session 1 + 2",
                "normalized_name": "summer session 1 + 2",
                "term_type": "preset",
                "year_format": "following_year",
                "is_active": True,
                "created_by": None,
            },
            {
                "id": uuid.UUID("00000000-0000-0000-0007-000000000007"),
                "institution": "generic",
                "code": "general",
                "name": "General",
                "normalized_name": "general",
                "term_type": "preset",
                "year_format": "start_year",
                "is_active": True,
                "created_by": None,
            },
        ],
    )

    op.add_column("courses", sa.Column("academic_term_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_courses_academic_term_id_academic_terms",
        "courses",
        "academic_terms",
        ["academic_term_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Match existing UBC labels to presets. Any remaining free-form or Canvas
    # values become owner-scoped custom terms, preserving every course label.
    op.execute(
        """
        INSERT INTO academic_terms (
            id, institution, code, name, normalized_name, term_type,
            year_format, is_active, created_by
        )
        SELECT
            CAST(md5(c.created_by::text || ':' ||
                COALESCE(NULLIF(lower(btrim(c.semester)), ''), 'general')) AS uuid),
            u.institution,
            NULL,
            COALESCE(NULLIF(min(btrim(c.semester)), ''), 'General'),
            COALESCE(NULLIF(lower(btrim(c.semester)), ''), 'general'),
            'custom',
            'none',
            true,
            c.created_by
        FROM courses c
        JOIN users u ON u.id = c.created_by
        WHERE NOT EXISTS (
            SELECT 1
            FROM academic_terms preset
            WHERE preset.institution = u.institution
              AND preset.term_type = 'preset'
              AND preset.normalized_name = COALESCE(
                  NULLIF(lower(btrim(c.semester)), ''),
                  'general'
              )
        )
        GROUP BY c.created_by, u.institution,
            COALESCE(NULLIF(lower(btrim(c.semester)), ''), 'general')
        """
    )
    op.execute(
        """
        UPDATE courses c
        SET academic_term_id = term.id
        FROM users u, academic_terms term
        WHERE u.id = c.created_by
          AND term.institution = u.institution
          AND term.normalized_name = COALESCE(
              NULLIF(lower(btrim(c.semester)), ''),
              'general'
          )
          AND (term.term_type = 'preset' OR term.created_by = c.created_by)
        """
    )
    op.alter_column("courses", "academic_term_id", nullable=False)
    op.drop_column("courses", "semester")


def downgrade() -> None:
    op.add_column("courses", sa.Column("semester", sa.String(), nullable=True))
    op.execute(
        """
        UPDATE courses c
        SET semester = term.name
        FROM academic_terms term
        WHERE term.id = c.academic_term_id
        """
    )
    op.alter_column("courses", "semester", nullable=False)
    op.drop_constraint(
        "fk_courses_academic_term_id_academic_terms",
        "courses",
        type_="foreignkey",
    )
    op.drop_column("courses", "academic_term_id")
    op.drop_table("academic_terms")
    op.drop_constraint(
        "ck_users_institution_valid",
        "users",
        type_="check",
    )
    op.drop_column("users", "institution")
