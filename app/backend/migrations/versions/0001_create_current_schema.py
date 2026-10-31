"""create current schema

Revision ID: 0001
Revises: 
Create Date: 2026-07-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('exam_release_audit_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('exam_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.CheckConstraint("event_type IN ('released', 'closed')", name='ck_exam_release_audit_entries_event_type_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_exam_release_audit_entries_exam_id_created_at', 'exam_release_audit_entries', ['exam_id', 'created_at'], unique=False)
    op.create_table('omr_templates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('scan_template_path', sa.String(), nullable=True),
    sa.Column('mark_template_path', sa.String(), nullable=True),
    sa.Column('preprocess_template_id', sa.String(), nullable=True),
    sa.Column('mark_template_id', sa.String(), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('review_request_audit_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('review_request_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('clock_timestamp()'), nullable=False),
    sa.CheckConstraint("event_type IN ('resolved', 'rejected')", name='ck_review_request_audit_entries_event_type_valid'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_review_request_audit_entries_review_request_id_created_at', 'review_request_audit_entries', ['review_request_id', 'created_at'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('first_name', sa.String(), nullable=False),
    sa.Column('last_name', sa.String(), nullable=False),
    sa.Column('student_number', sa.String(), nullable=True),
    sa.Column('password_hash', sa.String(), nullable=False),
    sa.Column('role', sa.String(), server_default='student', nullable=False),
    sa.Column('status', sa.String(), server_default='active', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('student', 'ta', 'professor', 'admin')", name='ck_users_role_valid'),
    sa.CheckConstraint("status IN ('active', 'disabled')", name='ck_users_status_valid'),
    sa.CheckConstraint("student_number IS NULL OR student_number ~ '^[0-9]{8}$'", name='ck_users_student_number_format'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('student_number', name='uq_users_student_number')
    )
    op.create_table('courses',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('semester', sa.String(), nullable=False),
    sa.Column('academic_year_start', sa.Integer(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('invite_link', sa.String(), nullable=False),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('invite_link')
    )
    op.create_table('exam_templates',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('question_config', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('sections', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('total_questions', sa.Integer(), nullable=False),
    sa.Column('blueprint', sa.String(), nullable=True),
    sa.Column('version_from_q1', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('version', sa.Integer(), server_default='1', nullable=False),
    sa.Column('n_versions', sa.Integer(), server_default='4', nullable=False),
    sa.Column('omr_template_id', sa.Uuid(), nullable=True),
    sa.Column('generated_pdf_path', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['omr_template_id'], ['omr_templates.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('password_reset_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_password_reset_tokens_user_id', 'password_reset_tokens', ['user_id'], unique=False)
    op.create_table('refresh_tokens',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('jti', sa.String(length=36), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('replaced_by_token_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['replaced_by_token_id'], ['refresh_tokens.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('jti'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index('ix_refresh_tokens_user_id', 'refresh_tokens', ['user_id'], unique=False)
    op.create_table('course_comparisons',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('base_course_id', sa.Uuid(), nullable=False),
    sa.Column('comparison_course_id', sa.Uuid(), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['base_course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['comparison_course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('base_course_id', 'comparison_course_id', name='uq_course_comparison_pair')
    )
    op.create_index(op.f('ix_course_comparisons_base_course_id'), 'course_comparisons', ['base_course_id'], unique=False)
    op.create_table('course_roster_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('course_id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=True),
    sa.Column('email', sa.String(), nullable=False),
    sa.Column('first_name', sa.String(), nullable=False),
    sa.Column('last_name', sa.String(), nullable=False),
    sa.Column('student_number', sa.String(), nullable=True),
    sa.Column('source', sa.String(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("source IN ('manual', 'csv', 'invite')", name='ck_course_roster_entries_source_valid'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('course_id', 'email', name='uq_course_roster_entries_course_email'),
    sa.UniqueConstraint('course_id', 'student_number', name='uq_course_roster_entries_course_student_number')
    )
    op.create_table('enrolments',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('course_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.CheckConstraint("role IN ('student', 'ta', 'professor')", name='ck_enrolments_role_valid'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exams',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('name', sa.String(), nullable=False),
    sa.Column('description', sa.String(), nullable=True),
    sa.Column('start_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('end_time', sa.DateTime(timezone=True), nullable=False),
    sa.Column('role', sa.String(), nullable=False),
    sa.Column('released', sa.Boolean(), server_default=sa.text('false'), nullable=False),
    sa.Column('created_by', sa.Uuid(), nullable=True),
    sa.Column('course_id', sa.Uuid(), nullable=False),
    sa.Column('exam_template_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('generated_pdf_path', sa.String(), nullable=True),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['exam_template_id'], ['exam_templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('notifications',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('recipient_user_id', sa.Uuid(), nullable=False),
    sa.Column('type', sa.String(), nullable=False),
    sa.Column('title', sa.String(), nullable=False),
    sa.Column('body', sa.String(), nullable=True),
    sa.Column('course_id', sa.Uuid(), nullable=True),
    sa.Column('link_path', sa.String(), nullable=True),
    sa.Column('link_query', sa.String(), nullable=True),
    sa.Column('is_read', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("type IN ('grade_ready', 'grade_needs_review', 'review_request_created', 'review_request_resolved', 'scan_failed', 'grading_failed')", name='ck_notifications_type_valid'),
    sa.ForeignKeyConstraint(['course_id'], ['courses.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['recipient_user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_notifications_created_at'), 'notifications', ['created_at'], unique=False)
    op.create_index(op.f('ix_notifications_recipient_user_id'), 'notifications', ['recipient_user_id'], unique=False)
    op.create_table('exam_answer_keys',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('exam_id', sa.Uuid(), nullable=False),
    sa.Column('exam_template_id', sa.Uuid(), nullable=True),
    sa.Column('exam_version', sa.String(), nullable=True),
    sa.Column('answer_key', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('scoring_rules', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('answer_key_path', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['exam_template_id'], ['exam_templates.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exam_comparison_mappings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('course_comparison_id', sa.Uuid(), nullable=False),
    sa.Column('base_exam_id', sa.Uuid(), nullable=False),
    sa.Column('comparison_exam_id', sa.Uuid(), nullable=True),
    sa.ForeignKeyConstraint(['base_exam_id'], ['exams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['comparison_exam_id'], ['exams.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['course_comparison_id'], ['course_comparisons.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('course_comparison_id', 'base_exam_id', name='uq_comparison_base_exam'),
    sa.UniqueConstraint('course_comparison_id', 'comparison_exam_id', name='uq_comparison_historical_exam')
    )
    op.create_index(op.f('ix_exam_comparison_mappings_course_comparison_id'), 'exam_comparison_mappings', ['course_comparison_id'], unique=False)
    op.create_table('scans',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('exam_id', sa.Uuid(), nullable=False),
    sa.Column('exam_template_id', sa.Uuid(), nullable=True),
    sa.Column('uploader_user_id', sa.Uuid(), nullable=False),
    sa.Column('path', sa.String(), nullable=False),
    sa.Column('page_count', sa.Integer(), nullable=True),
    sa.Column('batch_id', sa.Uuid(), nullable=True),
    sa.Column('batch_index', sa.Integer(), nullable=True),
    sa.Column('omr_scan_id', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('failure_code', sa.String(), nullable=True),
    sa.Column('failure_detail', sa.String(), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'completed', 'failed')", name='ck_scans_status_valid'),
    sa.ForeignKeyConstraint(['exam_id'], ['exams.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['exam_template_id'], ['exam_templates.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['uploader_user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scans_batch_id'), 'scans', ['batch_id'], unique=False)
    op.create_table('omr_markings',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('scan_id', sa.Uuid(), nullable=False),
    sa.Column('omr_template_id', sa.Uuid(), nullable=False),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('marked_file_path', sa.String(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'processing', 'completed', 'failed', 'needs_review')", name='ck_omr_markings_status_valid'),
    sa.ForeignKeyConstraint(['omr_template_id'], ['omr_templates.id'], ),
    sa.ForeignKeyConstraint(['scan_id'], ['scans.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('exam_grades',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('omr_marking_id', sa.Uuid(), nullable=False),
    sa.Column('exam_answer_key_id', sa.Uuid(), nullable=False),
    sa.Column('question_results', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('total_score', sa.FLOAT(), nullable=False),
    sa.Column('max_score', sa.FLOAT(), nullable=False),
    sa.Column('template_version', sa.Integer(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(), server_default='graded', nullable=False),
    sa.Column('flag_reason', sa.String(), nullable=True),
    sa.Column('graded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('graded', 'needs_review')", name='ck_exam_grades_status_valid'),
    sa.ForeignKeyConstraint(['exam_answer_key_id'], ['exam_answer_keys.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['omr_marking_id'], ['omr_markings.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('omr_marking_id', name='uq_exam_grades_omr_marking_id')
    )
    op.create_table('omr_detected_marks',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('marking_id', sa.Uuid(), nullable=False),
    sa.Column('field_type', sa.String(), nullable=False),
    sa.Column('field_index', sa.Integer(), nullable=False),
    sa.Column('detected_value', sa.String(), nullable=True),
    sa.Column('confidence_score', sa.FLOAT(), nullable=True),
    sa.Column('needs_review', sa.Boolean(), server_default='false', nullable=False),
    sa.Column('x', sa.Integer(), nullable=True),
    sa.Column('y', sa.Integer(), nullable=True),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.CheckConstraint("field_type IN ('question', 'version', 'last_name', 'first_name', 'student_id')", name='ck_omr_detected_marks_field_type_valid'),
    sa.ForeignKeyConstraint(['marking_id'], ['omr_markings.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('grade_audit_entries',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('exam_grade_id', sa.Uuid(), nullable=False),
    sa.Column('actor_user_id', sa.Uuid(), nullable=True),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('previous_total_score', sa.FLOAT(), nullable=True),
    sa.Column('new_total_score', sa.FLOAT(), nullable=False),
    sa.Column('changes', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("event_type IN ('initial_grade', 'manual_correction')", name='ck_grade_audit_entries_event_type_valid'),
    sa.ForeignKeyConstraint(['actor_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['exam_grade_id'], ['exam_grades.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_grade_audit_entries_exam_grade_id_created_at', 'grade_audit_entries', ['exam_grade_id', 'created_at'], unique=False)
    op.create_table('review_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('exam_grade_id', sa.Uuid(), nullable=False),
    sa.Column('student_id', sa.Uuid(), nullable=False),
    sa.Column('question_number', sa.String(), nullable=False),
    sa.Column('student_comment', sa.String(), nullable=True),
    sa.Column('status', sa.String(), server_default='pending', nullable=False),
    sa.Column('instructor_response', sa.String(), nullable=True),
    sa.Column('current_score', sa.Float(), nullable=True),
    sa.Column('proposed_score', sa.Float(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    sa.CheckConstraint("status IN ('pending', 'resolved', 'rejected')", name='ck_review_requests_status_valid'),
    sa.ForeignKeyConstraint(['exam_grade_id'], ['exam_grades.id'], ),
    sa.ForeignKeyConstraint(['student_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('review_requests')
    op.drop_index('ix_grade_audit_entries_exam_grade_id_created_at', table_name='grade_audit_entries')
    op.drop_table('grade_audit_entries')
    op.drop_table('omr_detected_marks')
    op.drop_table('exam_grades')
    op.drop_table('omr_markings')
    op.drop_index(op.f('ix_scans_batch_id'), table_name='scans')
    op.drop_table('scans')
    op.drop_index(op.f('ix_exam_comparison_mappings_course_comparison_id'), table_name='exam_comparison_mappings')
    op.drop_table('exam_comparison_mappings')
    op.drop_table('exam_answer_keys')
    op.drop_index(op.f('ix_notifications_recipient_user_id'), table_name='notifications')
    op.drop_index(op.f('ix_notifications_created_at'), table_name='notifications')
    op.drop_table('notifications')
    op.drop_table('exams')
    op.drop_table('enrolments')
    op.drop_table('course_roster_entries')
    op.drop_index(op.f('ix_course_comparisons_base_course_id'), table_name='course_comparisons')
    op.drop_table('course_comparisons')
    op.drop_index('ix_refresh_tokens_user_id', table_name='refresh_tokens')
    op.drop_table('refresh_tokens')
    op.drop_index('ix_password_reset_tokens_user_id', table_name='password_reset_tokens')
    op.drop_table('password_reset_tokens')
    op.drop_table('exam_templates')
    op.drop_table('courses')
    op.drop_table('users')
    op.drop_index('ix_review_request_audit_entries_review_request_id_created_at', table_name='review_request_audit_entries')
    op.drop_table('review_request_audit_entries')
    op.drop_table('omr_templates')
    op.drop_index('ix_exam_release_audit_entries_exam_id_created_at', table_name='exam_release_audit_entries')
    op.drop_table('exam_release_audit_entries')
