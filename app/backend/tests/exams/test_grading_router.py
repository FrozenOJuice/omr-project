"""Integration tests for the grading endpoints.

POST  /api/markings/{marking_id}/grade
GET   /api/markings/{marking_id}/grade
GET   /api/grades/{grade_id}
PATCH /api/grades/{grade_id}

OMR records (markings, detected marks) are inserted directly via db_session
since there is no API for the Go OMR service in the Python backend.
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

import pytest

from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.omr_detected_mark import MarkFieldType, OMRDetectedMark
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import User, UserRole

pytestmark = pytest.mark.db

_START = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
_END = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

_ANSWER_KEY = {
    "1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0},
    "2": {"grading_type": "single", "correct_choices": ["B"], "points": 1.0},
}


async def _get_user_id(db_session, email: str) -> uuid.UUID:
    result = await db_session.execute(select(User).where(User.email == email))
    return result.scalar_one().id


async def _seed(db_session, user_id: uuid.UUID):
    """Insert the chain required to grade a marking."""
    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=user_id)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Test Template",
        created_by=user_id,
        question_config={"1": {"choices": ["A", "B", "C", "D"]}, "2": {"choices": ["A", "B", "C", "D"]}},
        sections=[
            {
                "id": "multiple-choice",
                "name": "Multiple Choice",
                "type": "multiple_choice",
                "question_ids": ["1"],
            },
            {
                "id": "true-false",
                "name": "True / False",
                "type": "true_false",
                "question_ids": ["2"],
            },
        ],
        total_questions=2, version=1, n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()

    omr_tmpl = OMRTemplate(name="OMR", page_count=2, mark_template_id="mark-template-1")
    db_session.add(omr_tmpl)
    await db_session.flush()

    template.omr_template_id = omr_tmpl.id
    await db_session.flush()

    exam = Exam(course_id=course.id, created_by=user_id, name="Midterm",
                start_time=_START, end_time=_END, role="student",
                exam_template_id=template.id)
    db_session.add(exam)
    await db_session.flush()

    answer_key = ExamAnswerKey(
        exam_id=exam.id, exam_template_id=template.id, answer_key=_ANSWER_KEY
    )
    db_session.add(answer_key)
    await db_session.flush()

    scan = Scan(exam_id=exam.id, exam_template_id=template.id,
                uploader_user_id=user_id, path="scans/test.pdf",
                omr_scan_id="omr-scan-1")
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_tmpl.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    for q_num, value, page_index, x in [(1, "A", 0, 10), (2, "B", 1, 20)]:
        db_session.add(OMRDetectedMark(
            marking_id=marking.id,
            field_type=MarkFieldType.QUESTION,
            field_index=q_num,
            detected_value=value,
            page_index=page_index,
            bounds={"x": x - 5, "y": 25, "width": 200, "height": 60},
            boxes=[
                {"label": value, "selected": True, "x": x, "y": 30, "width": 40, "height": 50},
                {"label": "Z", "selected": False, "x": x + 60, "y": 30, "width": 40, "height": 50},
            ],
            confidence_score=0.85,
        ))
    await db_session.flush()

    return marking, answer_key, exam


class TestGradeEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(f"/api/markings/{uuid.uuid4()}/grade")
        assert response.status_code == 401

    async def test_student_role_returns_403(self, register_user, client):
        resp = await register_user()
        token = resp.json()["access_token"]
        response = await client.post(
            f"/api/markings/{uuid.uuid4()}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_unknown_marking_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            f"/api/markings/{uuid.uuid4()}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "marking_not_found"

    async def test_marking_not_completed_returns_400(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        marking.status = "processing"
        await db_session.flush()

        response = await client.post(
            f"/api/markings/{marking.id}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "marking_not_completed"

    async def test_grade_happy_path(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, exam = await _seed(db_session, user_id)

        response = await client.post(
            f"/api/markings/{marking.id}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["omr_marking_id"] == str(marking.id)
        assert data["exam_answer_key_id"] == str(answer_key.id)
        assert data["total_score"] == 2.0
        assert data["max_score"] == 2.0
        assert data["page_count"] == 2
        assert data["exam_id"] == str(exam.id)
        assert data["question_results"]["1"]["correct"] is True
        assert data["question_results"]["2"]["correct"] is True
        assert data["section_results"] == [
            {
                "id": "multiple-choice",
                "name": "Multiple Choice",
                "type": "multiple_choice",
                "question_ids": ["1"],
                "score": 1.0,
                "max_score": 1.0,
            },
            {
                "id": "true-false",
                "name": "True / False",
                "type": "true_false",
                "question_ids": ["2"],
                "score": 1.0,
                "max_score": 1.0,
            },
        ]

    async def test_incomplete_answer_key_cannot_be_graded(
        self, authenticated_client, db_session
    ):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, _ = await _seed(db_session, user_id)
        answer_key.answer_key = {
            **_ANSWER_KEY,
            "2": {**_ANSWER_KEY["2"], "correct_choices": []},
        }
        await db_session.flush()

        response = await client.post(
            f"/api/markings/{marking.id}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "answer_keys_incomplete"
        assert response.json()["error"]["details"]["versions"] == ["unversioned"]



class TestGetGradeForMarkingEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/markings/{uuid.uuid4()}/grade")
        assert response.status_code == 401

    async def test_no_grade_yet_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.get(
            f"/api/markings/{uuid.uuid4()}/grade",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grade_not_found"

    async def test_returns_grade_after_grading(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(f"/api/markings/{marking.id}/grade", headers=headers)

        response = await client.get(f"/api/markings/{marking.id}/grade", headers=headers)
        assert response.status_code == 200
        assert response.json()["omr_marking_id"] == str(marking.id)


class TestGetGradeByIdEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}")
        assert response.status_code == 401

    async def test_unknown_grade_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.get(
            f"/api/grades/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grade_not_found"

    async def test_returns_grade_by_id(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == grade_id

    async def test_unassigned_nonnumeric_question_does_not_break_section_results(
        self, authenticated_client, db_session
    ):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}
        grade_data = (
            await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        ).json()
        grade = await db_session.get(ExamGrade, uuid.UUID(grade_data["id"]))
        grade.question_results = {
            **grade.question_results,
            "bonus": {
                "grading_type": "single",
                "student_answers": [],
                "correct_answers": ["A"],
                "correct": False,
                "score": 0.0,
                "max_score": 1.0,
                "ambiguous": False,
            },
        }
        await db_session.flush()

        response = await client.get(f"/api/grades/{grade.id}", headers=headers)

        assert response.status_code == 200
        assert response.json()["section_results"][-1]["question_ids"] == ["bonus"]


class TestListExamGradesEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/exams/{uuid.uuid4()}/grades")
        assert response.status_code == 401

    async def test_returns_grades_for_exam(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, exam = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]
        answer_key.exam_version = "B"
        await db_session.flush()

        response = await client.get(f"/api/exams/{exam.id}/grades", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == grade_id
        assert data[0]["exam_version"] == "B"


async def _seed_enrolled_student(db_session, course_id: uuid.UUID) -> User:
    student = User(
        email=f"student_{uuid.uuid4().hex[:6]}@test.com",
        first_name="Sam",
        last_name="Student",
        password_hash="not-a-real-hash",
        role="student",
    )
    db_session.add(student)
    await db_session.flush()
    db_session.add(Enrolment(user_id=student.id, course_id=course_id, role="student"))
    await db_session.flush()
    return student


class TestUpdateGradeEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.patch(
            f"/api/grades/{uuid.uuid4()}", json={"resolve_flag": True}
        )
        assert response.status_code == 401

    async def test_student_role_returns_403(self, register_user, client):
        resp = await register_user()
        token = resp.json()["access_token"]
        response = await client.patch(
            f"/api/grades/{uuid.uuid4()}",
            json={"resolve_flag": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_unknown_grade_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.patch(
            f"/api/grades/{uuid.uuid4()}",
            json={"resolve_flag": True},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grade_not_found"

    async def test_empty_payload_returns_422(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.patch(
            f"/api/grades/{uuid.uuid4()}",
            json={},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_corrected_answers_rescore(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]
        assert grade_resp.json()["total_score"] == 2.0

        # Q1 corrected to a wrong answer (lowercase, should normalize), Q2 to blank.
        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["b"], "2": []}},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question_results"]["1"]["student_answers"] == ["B"]
        assert data["question_results"]["1"]["correct"] is False
        assert data["question_results"]["2"]["student_answers"] == []
        assert data["total_score"] == 0.0
        assert [section["score"] for section in data["section_results"]] == [0.0, 0.0]

        # Correcting Q1 back to the right answer recomputes the total again.
        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["A"]}},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question_results"]["1"]["correct"] is True
        assert data["total_score"] == 1.0
        assert [section["score"] for section in data["section_results"]] == [1.0, 0.0]

    async def test_corrected_multi_mark_is_not_reflagged_ambiguous(self, authenticated_client, db_session):
        # A professor confirming via manual review that a student really did
        # mark two bubbles on a "single" question should score 0 (same as
        # any other mismatch) but must not come back out the other end still
        # flagged "ambiguous" -- that flag exists so a human looks at it, and
        # a human just did.
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["A", "C"]}},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["question_results"]["1"]["student_answers"] == ["A", "C"]
        assert data["question_results"]["1"]["correct"] is False
        assert data["question_results"]["1"]["ambiguous"] is False

    async def test_unknown_question_returns_400(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"99": ["A"]}},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "question_not_in_key"

    async def test_assign_student_and_resolve(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, exam = await _seed(db_session, user_id)
        student = await _seed_enrolled_student(db_session, exam.course_id)
        headers = {"Authorization": f"Bearer {token}"}

        # The seeded scan has no name/id marks, so grading flags it for review.
        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade = grade_resp.json()
        assert grade["status"] == "needs_review"
        assert grade["student_id"] is None

        response = await client.patch(
            f"/api/grades/{grade['id']}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["student_id"] == str(student.id)
        assert data["status"] == "graded"
        assert data["flag_reason"] is None

    async def test_second_student_assignment_requires_explicit_confirmation(
        self, authenticated_client, db_session
    ):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, answer_key, exam = await _seed(db_session, user_id)
        student = await _seed_enrolled_student(db_session, exam.course_id)
        headers = {"Authorization": f"Bearer {token}"}

        first_response = await client.post(
            f"/api/markings/{marking.id}/grade", headers=headers
        )
        first_grade_id = first_response.json()["id"]
        await client.patch(
            f"/api/grades/{first_grade_id}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=headers,
        )

        second_scan = Scan(
            exam_id=exam.id,
            exam_template_id=exam.exam_template_id,
            uploader_user_id=user_id,
            path="scans/duplicate.pdf",
            omr_scan_id="omr-scan-duplicate",
        )
        db_session.add(second_scan)
        await db_session.flush()
        second_marking = OMRMarking(
            scan_id=second_scan.id,
            omr_template_id=marking.omr_template_id,
            status="completed",
        )
        db_session.add(second_marking)
        await db_session.flush()
        second_grade = ExamGrade(
            omr_marking_id=second_marking.id,
            exam_answer_key_id=answer_key.id,
            question_results={},
            total_score=0,
            max_score=2,
            template_version=1,
            status="needs_review",
            flag_reason="duplicate_student_grade",
        )
        db_session.add(second_grade)
        await db_session.flush()

        blocked = await client.patch(
            f"/api/grades/{second_grade.id}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=headers,
        )
        assert blocked.status_code == 409
        assert blocked.json()["error"]["code"] == "duplicate_student_assignment"
        assert blocked.json()["error"]["details"]["grade_ids"] == [first_grade_id]

        confirmed = await client.patch(
            f"/api/grades/{second_grade.id}",
            json={
                "student_id": str(student.id),
                "resolve_flag": True,
                "confirm_duplicate_assignment": True,
            },
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["student_id"] == str(student.id)
        assert confirmed.json()["status"] == "graded"

    async def test_assign_unenrolled_student_returns_400(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        outsider = User(
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com",
            first_name="Out",
            last_name="Sider",
            password_hash="not-a-real-hash",
            role="student",
        )
        db_session.add(outsider)
        await db_session.flush()

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"student_id": str(outsider.id)},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "student_not_enrolled"

    async def test_resolve_without_student_returns_400(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"resolve_flag": True},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "student_required_to_resolve"

    async def test_owning_professor_can_update(
        self, client, create_user, login_user, db_session
    ):
        prof = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, _ = await _seed(db_session, prof.id)
        login = await login_user(email=prof.email, password="Password123!")
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["A"]}},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["question_results"]["1"]["correct"] is True

    async def test_non_owning_professor_returns_403(
        self, client, create_user, login_user, db_session
    ):
        # The course (and its grade) belongs to `owner`.
        owner = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, _ = await _seed(db_session, owner.id)
        owner_login = await login_user(email=owner.email, password="Password123!")
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=owner_headers)
        grade_id = grade_resp.json()["id"]

        # A different professor, who does not own the course, may not touch it.
        other = await create_user(
            email=f"other_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        other_login = await login_user(email=other.email, password="Password123!")
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["A"]}},
            headers=other_headers,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "grade_update_forbidden"


class TestGetGradeHistoryEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/history")
        assert response.status_code == 401

    async def test_unknown_grade_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.get(
            f"/api/grades/{uuid.uuid4()}/history",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grade_not_found"

    async def test_staff_sees_initial_grade_entry(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}/history", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["event_type"] == "initial_grade"
        assert data[0]["actor_user_id"] is None
        assert data[0]["actor_name"] is None
        assert data[0]["previous_total_score"] is None
        assert data[0]["new_total_score"] == 2.0
        assert "1" in data[0]["changes"]["questions"]

    async def test_correction_appends_entry_with_actor_and_diff(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["B"]}},
            headers=headers,
        )

        response = await client.get(f"/api/grades/{grade_id}/history", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["event_type"] == "initial_grade"
        correction = data[1]
        assert correction["event_type"] == "manual_correction"
        assert correction["actor_user_id"] == str(user_id)
        assert correction["actor_name"]
        assert correction["previous_total_score"] == 2.0
        assert correction["new_total_score"] == 1.0
        assert list(correction["changes"]["questions"].keys()) == ["1"]
        assert "student_id" not in correction["changes"]

    async def test_flag_only_resolution_has_no_questions_diff(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, exam = await _seed(db_session, user_id)
        student = await _seed_enrolled_student(db_session, exam.course_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        await client.patch(
            f"/api/grades/{grade_id}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=headers,
        )

        response = await client.get(f"/api/grades/{grade_id}/history", headers=headers)
        data = response.json()
        correction = data[1]
        assert correction["event_type"] == "manual_correction"
        assert "questions" not in correction["changes"]
        assert correction["changes"]["student_id"]["after"] == str(student.id)
        assert correction["changes"]["status"] == {"before": "needs_review", "after": "graded"}
        assert correction["previous_total_score"] == correction["new_total_score"]

    async def test_student_sees_own_grade_history(
        self, client, create_user, login_user, db_session
    ):
        prof = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, exam = await _seed(db_session, prof.id)
        student = await create_user(
            email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT
        )
        db_session.add(Enrolment(user_id=student.id, course_id=exam.course_id, role="student"))
        await db_session.flush()

        prof_login = await login_user(email=prof.email, password="Password123!")
        prof_headers = {"Authorization": f"Bearer {prof_login.json()['access_token']}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=prof_headers)
        grade_id = grade_resp.json()["id"]
        await client.patch(
            f"/api/grades/{grade_id}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=prof_headers,
        )
        exam.released = True
        await db_session.flush()

        student_login = await login_user(email=student.email, password="Password123!")
        student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

        response = await client.get(f"/api/grades/{grade_id}/history", headers=student_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_student_forbidden_before_exam_is_released(
        self, client, create_user, login_user, db_session
    ):
        """A student must not be able to see a correction's before/after
        scores via the history endpoint before the exam is released, even
        though the grade itself is already assigned to them -- otherwise the
        history endpoint would leak what /grades hides pre-release."""
        prof = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, exam = await _seed(db_session, prof.id)
        student = await create_user(
            email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT
        )
        db_session.add(Enrolment(user_id=student.id, course_id=exam.course_id, role="student"))
        await db_session.flush()

        prof_login = await login_user(email=prof.email, password="Password123!")
        prof_headers = {"Authorization": f"Bearer {prof_login.json()['access_token']}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=prof_headers)
        grade_id = grade_resp.json()["id"]
        await client.patch(
            f"/api/grades/{grade_id}",
            json={"student_id": str(student.id), "resolve_flag": True},
            headers=prof_headers,
        )

        student_login = await login_user(email=student.email, password="Password123!")
        student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

        response = await client.get(f"/api/grades/{grade_id}/history", headers=student_headers)
        assert response.status_code == 403

    async def test_other_student_returns_403(self, authenticated_client, register_user, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        other_resp = await register_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com")
        other_token = other_resp.json()["access_token"]

        response = await client.get(
            f"/api/grades/{grade_id}/history",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "insufficient_permissions"

    async def test_unrelated_professor_returns_403(
        self, client, create_user, login_user, db_session
    ):
        """A professor with no relationship to the course must not be able to
        view another course's grade history -- staff access is scoped to the
        course that owns the grade, not staff-role-in-general."""
        owner = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, _ = await _seed(db_session, owner.id)
        owner_login = await login_user(email=owner.email, password="Password123!")
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=owner_headers)
        grade_id = grade_resp.json()["id"]

        other = await create_user(
            email=f"other_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        other_login = await login_user(email=other.email, password="Password123!")
        other_headers = {"Authorization": f"Bearer {other_login.json()['access_token']}"}

        response = await client.get(f"/api/grades/{grade_id}/history", headers=other_headers)
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "insufficient_permissions"

    async def test_course_co_professor_can_view_history(
        self, client, create_user, login_user, db_session
    ):
        """A professor enrolled in the course that owns the grade (but not the
        course owner) is in scope and may view its history, unlike a professor
        from an unrelated course."""
        owner = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        marking, _, exam = await _seed(db_session, owner.id)
        owner_login = await login_user(email=owner.email, password="Password123!")
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}
        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=owner_headers)
        grade_id = grade_resp.json()["id"]

        co_prof = await create_user(email=f"coprof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR)
        db_session.add(Enrolment(user_id=co_prof.id, course_id=exam.course_id, role="professor"))
        await db_session.flush()
        co_prof_login = await login_user(email=co_prof.email, password="Password123!")
        co_prof_headers = {"Authorization": f"Bearer {co_prof_login.json()['access_token']}"}

        response = await client.get(f"/api/grades/{grade_id}/history", headers=co_prof_headers)
        assert response.status_code == 200
        assert len(response.json()) == 1


class TestGradeQuestionSnippetEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/questions/1/snippet")
        assert response.status_code == 401

    async def test_returns_question_snippet(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        with patch(
            "services.grading_service.get_question_snippet",
            new_callable=AsyncMock,
            return_value=b"jpeg-bytes",
        ) as mock_get_snippet:
            response = await client.get(f"/api/grades/{grade_id}/questions/1/snippet", headers=headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.content == b"jpeg-bytes"
        mock_get_snippet.assert_awaited_once_with("mark-template-1", "omr-scan-1", "Q1")


class TestGradePageAnnotationsEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/pages/0/annotations")
        assert response.status_code == 401

    async def test_returns_only_the_requested_page_questions(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}/pages/0/annotations", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["question_id"] == "1"
        assert data[0]["bounds"] == {"x": 5, "y": 25, "width": 200, "height": 60}
        assert data[0]["boxes"] == [
            {"label": "A", "selected": True, "x": 10, "y": 30, "width": 40, "height": 50},
            {"label": "Z", "selected": False, "x": 70, "y": 30, "width": 40, "height": 50},
        ]
        assert data[0]["confidence"] == 0.85
        assert data[0]["correct"] is True
        assert data[0]["student_answers"] == ["A"]
        assert data[0]["correct_answers"] == ["A"]

        response = await client.get(f"/api/grades/{grade_id}/pages/1/annotations", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["question_id"] == "2"

    async def test_correction_moves_the_selected_box(self, authenticated_client, db_session):
        """A manual correction should flip which box shows as selected, not
        just the color. The raw OMR detection (A) is stale once corrected
        to a different option (Z, the fixture's other seeded box)."""
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.patch(
            f"/api/grades/{grade_id}",
            json={"corrected_answers": {"1": ["Z"]}},
            headers=headers,
        )
        assert response.status_code == 200

        response = await client.get(f"/api/grades/{grade_id}/pages/0/annotations", headers=headers)
        assert response.status_code == 200
        boxes = {box["label"]: box["selected"] for box in response.json()[0]["boxes"]}
        assert boxes == {"A": False, "Z": True}


class TestGradePageIdentityEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/pages/0/identity")
        assert response.status_code == 401

    async def test_returns_decoded_identity_and_boxes(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        db_session.add_all([
            OMRDetectedMark(
                marking_id=marking.id,
                field_type=MarkFieldType.LAST_NAME,
                field_index=1,
                detected_value="S",
                page_index=2,
                bounds={"x": 0, "y": 0, "width": 20, "height": 20},
                boxes=[{"label": "S", "selected": True, "x": 0, "y": 0, "width": 20, "height": 20}],
                confidence_score=0.9,
            ),
            OMRDetectedMark(
                marking_id=marking.id,
                field_type=MarkFieldType.STUDENT_ID,
                field_index=1,
                detected_value="7",
                page_index=2,
                bounds={"x": 30, "y": 0, "width": 20, "height": 20},
                boxes=[{"label": "7", "selected": True, "x": 30, "y": 0, "width": 20, "height": 20}],
                confidence_score=0.9,
            ),
        ])
        await db_session.flush()

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}/pages/2/identity", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["last_name"] == "S"
        assert data["student_id"] == "7"
        assert data["first_name"] == ""
        assert data["page_index"] == 2
        assert len(data["fields"]) == 2
        assert {f["field_type"] for f in data["fields"]} == {"last_name", "student_id"}
        assert {f["confidence"] for f in data["fields"]} == {0.9}

        # Page 0 only has answer questions, so no identity fields to report.
        response = await client.get(f"/api/grades/{grade_id}/pages/0/identity", headers=headers)
        assert response.status_code == 200
        assert response.json() == {
            "fields": [], "last_name": "", "first_name": "", "student_id": "", "page_index": None,
        }


class TestGradeIdentityEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/identity")
        assert response.status_code == 401

    async def test_resolves_regardless_of_page(self, authenticated_client, db_session):
        """Unlike the page-scoped endpoint, this should find the identity
        fields without the caller needing to already know which page they're
        on. That's what a persistent "identify student" card needs."""
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        db_session.add(OMRDetectedMark(
            marking_id=marking.id,
            field_type=MarkFieldType.LAST_NAME,
            field_index=1,
            detected_value="S",
            page_index=2,
            bounds={"x": 0, "y": 0, "width": 20, "height": 20},
            boxes=[{"label": "S", "selected": True, "x": 0, "y": 0, "width": 20, "height": 20}],
            confidence_score=0.9,
        ))
        await db_session.flush()

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}/identity", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["last_name"] == "S"
        assert data["page_index"] == 2


class TestGradePageVersionEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/pages/0/version")
        assert response.status_code == 401

    async def test_returns_decoded_version_and_box(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        db_session.add(OMRDetectedMark(
            marking_id=marking.id,
            field_type=MarkFieldType.VERSION,
            field_index=1,
            detected_value="B",
            page_index=0,
            bounds={"x": 0, "y": 0, "width": 20, "height": 20},
            boxes=[{"label": "B", "selected": True, "x": 0, "y": 0, "width": 20, "height": 20}],
            confidence_score=0.9,
        ))
        await db_session.flush()

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        response = await client.get(f"/api/grades/{grade_id}/pages/0/version", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert data["detected_version"] == "B"
        assert data["field"]["field_type"] == "version"
        assert data["field"]["boxes"] == [
            {"label": "B", "selected": True, "x": 0, "y": 0, "width": 20, "height": 20}
        ]
        assert data["field"]["confidence"] == 0.9

        # Page 1 has no version mark on it for this fixture.
        response = await client.get(f"/api/grades/{grade_id}/pages/1/version", headers=headers)
        assert response.status_code == 200
        assert response.json() == {"field": None, "detected_version": None}


class TestGradePageImageEndpoint:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/grades/{uuid.uuid4()}/pages/0/image")
        assert response.status_code == 401

    async def test_returns_page_image(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        marking, _, _ = await _seed(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        grade_resp = await client.post(f"/api/markings/{marking.id}/grade", headers=headers)
        grade_id = grade_resp.json()["id"]

        with patch(
            "services.grading_service.get_scan_page_image",
            new_callable=AsyncMock,
            return_value=b"jpeg-bytes",
        ) as mock_get_image:
            response = await client.get(f"/api/grades/{grade_id}/pages/0/image", headers=headers)

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/jpeg")
        assert response.content == b"jpeg-bytes"
        mock_get_image.assert_awaited_once_with("omr-scan-1", 0)


async def _seed_graded_exam(db_session, *, professor_id, student_id, released):
    """Same chain as _seed, but writes a matched, graded ExamGrade directly
    (rather than going through the marking->grade endpoint, which needs
    identity marks to resolve a student) and lets the caller control the
    exam's released flag.
    """
    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=professor_id)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Test Template", created_by=professor_id,
        question_config={"1": {"choices": ["A", "B"]}},
        total_questions=1, version=1, n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(course_id=course.id, created_by=professor_id, name="Midterm",
                start_time=_START, end_time=_END, role="student",
                exam_template_id=template.id, released=released)
    db_session.add(exam)
    await db_session.flush()

    answer_key = ExamAnswerKey(
        exam_id=exam.id, exam_template_id=template.id, answer_key=_ANSWER_KEY
    )
    omr_template = OMRTemplate(name="OMR", page_count=2)
    db_session.add_all([answer_key, omr_template])
    await db_session.flush()

    scan = Scan(exam_id=exam.id, exam_template_id=template.id,
                uploader_user_id=professor_id, path="scans/test.pdf")
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_template.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    grade = ExamGrade(
        omr_marking_id=marking.id, exam_answer_key_id=answer_key.id,
        question_results={}, total_score=1.0, max_score=1.0, template_version=1,
        student_id=student_id, status="graded",
    )
    db_session.add(grade)
    await db_session.flush()
    return exam, grade


class TestReleaseGating:
    async def test_student_lists_no_grades_before_release(self, create_user, login_user, client, db_session):
        professor = await create_user(email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR)
        student = await create_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT)
        exam, grade = await _seed_graded_exam(
            db_session, professor_id=professor.id, student_id=student.id, released=False
        )

        token = (await login_user(email=student.email)).json()["access_token"]
        response = await client.get(
            f"/api/exams/{exam.id}/grades", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_student_gets_403_by_id_before_release(self, create_user, login_user, client, db_session):
        professor = await create_user(email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR)
        student = await create_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT)
        exam, grade = await _seed_graded_exam(
            db_session, professor_id=professor.id, student_id=student.id, released=False
        )

        token = (await login_user(email=student.email)).json()["access_token"]
        response = await client.get(
            f"/api/grades/{grade.id}", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    async def test_student_sees_grade_after_release(self, create_user, login_user, client, db_session):
        professor = await create_user(email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR)
        student = await create_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT)
        exam, grade = await _seed_graded_exam(
            db_session, professor_id=professor.id, student_id=student.id, released=True
        )

        token = (await login_user(email=student.email)).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        list_response = await client.get(f"/api/exams/{exam.id}/grades", headers=headers)
        assert list_response.status_code == 200
        assert [g["id"] for g in list_response.json()] == [str(grade.id)]

        by_id_response = await client.get(f"/api/grades/{grade.id}", headers=headers)
        assert by_id_response.status_code == 200
        assert by_id_response.json()["id"] == str(grade.id)

    async def test_staff_sees_grade_regardless_of_release(self, create_user, login_user, client, db_session):
        professor = await create_user(email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR)
        student = await create_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT)
        exam, grade = await _seed_graded_exam(
            db_session, professor_id=professor.id, student_id=student.id, released=False
        )

        token = (await login_user(email=professor.email)).json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        list_response = await client.get(f"/api/exams/{exam.id}/grades", headers=headers)
        assert list_response.status_code == 200
        assert [g["id"] for g in list_response.json()] == [str(grade.id)]

        by_id_response = await client.get(f"/api/grades/{grade.id}", headers=headers)
        assert by_id_response.status_code == 200
