import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_release_audit_entry import ExamReleaseAuditEntry
from models.exam_template import ExamTemplate
from models.notification import Notification
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import UserRole

pytestmark = pytest.mark.db


async def _seed_exam(db_session, *, course_created_by):
    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=course_created_by)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Template",
        created_by=course_created_by,
        question_config={"1": {"choices": ["A", "B"]}},
        total_questions=1,
        version=1,
        n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(
        name="Midterm",
        description=None,
        start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
        role="student",
        course_id=course.id,
        created_by=course_created_by,
        exam_template_id=template.id,
    )
    db_session.add(exam)
    await db_session.flush()
    return course, template, exam


async def _add_scan(db_session, exam, template, uploader_id, *, status="completed"):
    scan = Scan(
        exam_id=exam.id,
        exam_template_id=template.id,
        uploader_user_id=uploader_id,
        path=f"scans/{uuid.uuid4().hex}.pdf",
        status=status,
    )
    db_session.add(scan)
    await db_session.flush()
    return scan


async def _add_grade(db_session, exam, template, scan, *, status="graded", student_id=None, flag_reason=None):
    answer_key = ExamAnswerKey(
        exam_id=exam.id,
        exam_template_id=template.id,
        answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
    )
    omr_template = OMRTemplate(name="OMR", page_count=2)
    db_session.add_all([answer_key, omr_template])
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_template.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results={},
        total_score=1.0,
        max_score=1.0,
        template_version=1,
        student_id=student_id,
        status=status,
        flag_reason=flag_reason,
    )
    db_session.add(grade)
    await db_session.flush()
    return grade


async def _token_for(create_user, login_user, *, role, email=None):
    email = email or f"user_{uuid.uuid4().hex[:8]}@test.com"
    user = await create_user(email=email, role=role, student_number=None)
    resp = await login_user(email=email)
    return user, resp.json()["access_token"]


class TestReleaseExam:
    async def test_release_success_with_no_blockers(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        student, _ = await _token_for(create_user, login_user, role=UserRole.STUDENT)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        scan = await _add_scan(db_session, exam, template, professor.id, status="completed")
        await _add_grade(db_session, exam, template, scan, status="graded", student_id=student.id)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["released"] is True

    async def test_release_blocked_by_needs_review_grade(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        scan = await _add_scan(db_session, exam, template, professor.id, status="completed")
        grade = await _add_grade(
            db_session, exam, template, scan, status="needs_review", flag_reason="name_no_match"
        )

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409, response.json()
        details = response.json()["error"]["details"]
        assert {"type": "grade", "id": str(grade.id), "reason": "name_no_match"} in details

    async def test_release_blocked_by_pending_scan(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        scan = await _add_scan(db_session, exam, template, professor.id, status="pending")

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409, response.json()
        details = response.json()["error"]["details"]
        assert {"type": "scan", "id": str(scan.id), "reason": "pending"} in details

    async def test_release_forbidden_for_non_owning_professor(self, create_user, login_user, client, db_session):
        professor, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, other_prof_token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {other_prof_token}"},
        )
        assert response.status_code == 403

    async def test_release_allowed_for_admin(self, create_user, login_user, client, db_session):
        professor, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, admin_token = await _token_for(create_user, login_user, role=UserRole.ADMIN)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200
        assert response.json()["released"] is True

    async def test_release_notifies_matched_students_only(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        student, _ = await _token_for(create_user, login_user, role=UserRole.STUDENT)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        matched_scan = await _add_scan(db_session, exam, template, professor.id)
        await _add_grade(db_session, exam, template, matched_scan, status="graded", student_id=student.id)

        unmatched_scan = await _add_scan(db_session, exam, template, professor.id)
        await _add_grade(db_session, exam, template, unmatched_scan, status="graded", student_id=None)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()

        notifications = (
            await db_session.execute(
                select(Notification).where(
                    Notification.recipient_user_id == student.id,
                    Notification.type == "grade_ready",
                )
            )
        ).scalars().all()
        assert len(notifications) == 1

    async def test_release_not_found(self, create_user, login_user, client):
        _, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)

        response = await client.post(
            f"/api/exams/{uuid.uuid4()}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestCloseExam:
    async def test_close_succeeds_even_with_needs_review_grades(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        exam.released = True
        await db_session.flush()
        scan = await _add_scan(db_session, exam, template, professor.id, status="completed")
        await _add_grade(db_session, exam, template, scan, status="needs_review", flag_reason="name_no_match")

        response = await client.post(
            f"/api/exams/{exam.id}/close",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()
        assert response.json()["released"] is False

    async def test_close_forbidden_for_non_owning_professor(self, create_user, login_user, client, db_session):
        professor, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, other_prof_token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/close",
            headers={"Authorization": f"Bearer {other_prof_token}"},
        )
        assert response.status_code == 403


class TestExamReleaseAuditTrail:
    async def _entries_for(self, db_session, exam_id):
        result = await db_session.execute(
            select(ExamReleaseAuditEntry)
            .where(ExamReleaseAuditEntry.exam_id == exam_id)
            .order_by(ExamReleaseAuditEntry.created_at)
        )
        return result.scalars().all()

    async def test_release_writes_audit_entry(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()

        entries = await self._entries_for(db_session, exam.id)
        assert len(entries) == 1
        assert entries[0].event_type == "released"
        assert entries[0].actor_user_id == professor.id

    async def test_release_then_close_appends_second_entry(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        response = await client.post(
            f"/api/exams/{exam.id}/close",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()

        entries = await self._entries_for(db_session, exam.id)
        assert [e.event_type for e in entries] == ["released", "closed"]
        assert all(e.actor_user_id == professor.id for e in entries)

    async def test_repeated_release_is_idempotent(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, _, exam = await _seed_exam(db_session, course_created_by=professor.id)
        headers = {"Authorization": f"Bearer {token}"}

        first = await client.post(f"/api/exams/{exam.id}/release", headers=headers)
        second = await client.post(f"/api/exams/{exam.id}/release", headers=headers)

        assert first.status_code == 200
        assert second.status_code == 200
        entries = await self._entries_for(db_session, exam.id)
        assert [entry.event_type for entry in entries] == ["released"]

    async def test_closing_unreleased_exam_is_idempotent(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, _, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/close",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        assert await self._entries_for(db_session, exam.id) == []

    async def test_exam_deletion_preserves_release_audit_entry(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, _, exam = await _seed_exam(db_session, course_created_by=professor.id)
        exam_id = exam.id

        response = await client.post(
            f"/api/exams/{exam_id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200

        await db_session.delete(exam)
        await db_session.commit()

        entries = await self._entries_for(db_session, exam_id)
        assert len(entries) == 1
        assert entries[0].actor_user_id == professor.id

    async def test_release_allowed_for_admin_records_admin_as_actor(
        self, create_user, login_user, client, db_session
    ):
        professor, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        admin, admin_token = await _token_for(create_user, login_user, role=UserRole.ADMIN)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert response.status_code == 200, response.json()

        entries = await self._entries_for(db_session, exam.id)
        assert len(entries) == 1
        assert entries[0].actor_user_id == admin.id

    async def test_release_blocked_writes_no_audit_entry(self, create_user, login_user, client, db_session):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        scan = await _add_scan(db_session, exam, template, professor.id, status="completed")
        await _add_grade(db_session, exam, template, scan, status="needs_review", flag_reason="name_no_match")

        response = await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409, response.json()

        entries = await self._entries_for(db_session, exam.id)
        assert entries == []


class TestExamReleaseHistoryEndpoint:
    async def test_history_returns_release_and_close_events(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, _, exam = await _seed_exam(db_session, course_created_by=professor.id)
        headers = {"Authorization": f"Bearer {token}"}

        first = await client.post(f"/api/exams/{exam.id}/release", headers=headers)
        assert first.status_code == 200
        second = await client.post(f"/api/exams/{exam.id}/close", headers=headers)
        assert second.status_code == 200

        response = await client.get(f"/api/exams/{exam.id}/release-history", headers=headers)
        assert response.status_code == 200, response.json()

        data = response.json()
        assert [entry["event_type"] for entry in data] == ["released", "closed"]
        assert data[0]["actor_user_id"] == str(professor.id)
        assert data[0]["actor_name"] == f"{professor.first_name} {professor.last_name}"

    async def test_history_for_unrelated_professor_is_forbidden(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, other_token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, _, exam = await _seed_exam(db_session, course_created_by=professor.id)
        await client.post(
            f"/api/exams/{exam.id}/release",
            headers={"Authorization": f"Bearer {token}"},
        )

        response = await client.get(
            f"/api/exams/{exam.id}/release-history",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403

    async def test_history_not_found(self, create_user, login_user, client):
        _, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        response = await client.get(
            f"/api/exams/{uuid.uuid4()}/release-history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
