"""Integration tests for review request endpoints.

POST  /api/grades/{grade_id}/review-requests
GET   /api/review-requests
GET   /api/review-requests/me
GET   /api/review-requests/{id}
PATCH /api/review-requests/{id}
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import select

import pytest

from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.grade_audit_entry import GradeAuditEntry
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.review_request_audit_entry import ReviewRequestAuditEntry
from models.scan import Scan
from models.user import User, UserRole

pytestmark = pytest.mark.db

_START = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)
_END = datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc)

_ANSWER_KEY = {
    "1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0},
}

_QUESTION_RESULTS = {
    "1": {
        "grading_type": "single",
        "student_answers": ["B"],
        "correct_answers": ["A"],
        "correct": False,
        "score": 0.0,
        "max_score": 1.0,
    }
}

# For a test needing a real multi-question batch, so each question's own
# correct/incorrect decision can differ from its sibling's.
_TWO_QUESTION_RESULTS = {
    **_QUESTION_RESULTS,
    "2": {
        "grading_type": "single",
        "student_answers": ["A"],
        "correct_answers": ["A"],
        "correct": True,
        "score": 1.0,
        "max_score": 1.0,
    },
}


async def _get_user_id(db_session, email: str) -> uuid.UUID:
    result = await db_session.execute(select(User).where(User.email == email))
    return result.scalar_one().id


async def _seed_grade(
    db_session,
    user_id: uuid.UUID,
    student_id: uuid.UUID | None = None,
    question_results: dict | None = None,
) -> ExamGrade:
    """Create the minimal chain up to an ExamGrade record."""
    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=user_id)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Test Template",
        created_by=user_id,
        question_config={"1": {"choices": ["A", "B", "C", "D"]}},
        total_questions=1, version=1, n_versions=4,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(course_id=course.id, created_by=user_id, name="Midterm",
                start_time=_START, end_time=_END, role="student",
                exam_template_id=template.id, released=True)
    db_session.add(exam)
    await db_session.flush()

    omr_tmpl = OMRTemplate(name="OMR", page_count=2)
    db_session.add(omr_tmpl)
    await db_session.flush()

    answer_key = ExamAnswerKey(
        exam_id=exam.id, exam_template_id=template.id, answer_key=_ANSWER_KEY
    )
    db_session.add(answer_key)
    await db_session.flush()

    scan = Scan(exam_id=exam.id, exam_template_id=template.id,
                uploader_user_id=user_id, path="scans/test.pdf")
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_tmpl.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    resolved_question_results = question_results or _QUESTION_RESULTS
    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results=resolved_question_results,
        total_score=round(sum(r["score"] for r in resolved_question_results.values()), 4),
        max_score=round(sum(r["max_score"] for r in resolved_question_results.values()), 4),
        template_version=1,
        student_id=student_id or user_id,
    )
    db_session.add(grade)
    await db_session.flush()

    return grade


class TestSubmitReviewRequest:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.post(
            f"/api/grades/{uuid.uuid4()}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
        )
        assert response.status_code == 401

    async def test_student_role_can_submit(self, register_user, authenticated_client, db_session, client):
        """A plain student (non-staff) can submit a review request."""
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        _, _ = await authenticated_client(email=email)
        course_owner_id = await _get_user_id(db_session, email)

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]
        student_id = await _get_user_id(db_session, "alice@example.com")
        grade = await _seed_grade(db_session, course_owner_id, student_id)

        response = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "I disagree.", "proposed_scores": {"1": 1.0}},
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 201

    async def test_grade_must_belong_to_requesting_student(
        self, register_user, db_session, client
    ):
        owner_email = f"student_owner_{uuid.uuid4().hex[:6]}@test.com"
        await register_user(email=owner_email)
        owner_id = await _get_user_id(db_session, owner_email)
        grade = await _seed_grade(db_session, owner_id)

        other_student_resp = await register_user(
            email=f"other_student_{uuid.uuid4().hex[:6]}@test.com"
        )
        other_student_token = other_student_resp.json()["access_token"]

        response = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "Not my grade.", "proposed_scores": {"1": 1.0}},
            headers={"Authorization": f"Bearer {other_student_token}"},
        )

        assert response.status_code == 403
        assert response.json()["error"]["code"] == "insufficient_permissions"

    async def test_unknown_grade_returns_404(self, authenticated_client):
        client, token = await authenticated_client()

        response = await client.post(
            f"/api/grades/{uuid.uuid4()}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 404
        assert response.json()["error"]["code"] == "grade_not_found"

    async def test_submit_creates_review_request(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)

        response = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "I think my answer is correct.", "proposed_scores": {"1": 1.0}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 201
        data = response.json()[0]
        assert data["exam_grade_id"] == str(grade.id)
        assert data["question_number"] == "1"
        assert data["status"] == "pending"
        assert data["resolved_at"] is None


class TestMyReviewRequests:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/review-requests/me")
        assert response.status_code == 401

    async def test_returns_own_requests(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )

        response = await client.get("/api/review-requests/me", headers=headers)
        assert response.status_code == 200
        assert len(response.json()) == 1
        assert response.json()[0]["exam_grade_id"] == str(grade.id)


class TestGetReviewRequestById:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get(f"/api/review-requests/{uuid.uuid4()}")
        assert response.status_code == 401

    async def test_student_role_forbidden(self, register_user, client):
        resp = await register_user()
        token = resp.json()["access_token"]
        response = await client.get(
            f"/api/review-requests/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_not_found_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.get(
            f"/api/review-requests/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "review_request_not_found"

    async def test_returns_review_request(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "Wrong answer?", "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.get(f"/api/review-requests/{review_id}", headers=headers)
        assert response.status_code == 200
        assert response.json()["id"] == review_id


class TestResolveReviewRequest:
    async def test_student_role_forbidden(self, register_user, client):
        resp = await register_user()
        token = resp.json()["access_token"]
        response = await client.patch(
            f"/api/review-requests/{uuid.uuid4()}",
            json={"status": "resolved"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403

    async def test_not_found_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.patch(
            f"/api/review-requests/{uuid.uuid4()}",
            json={"status": "resolved", "instructor_response": "N/A", "proposed_correct": {"1": True}},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_resolve_sets_status_and_response(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={"status": "resolved", "instructor_response": "Score stands.", "proposed_correct": {"1": True}},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()[0]
        assert data["status"] == "resolved"
        assert data["instructor_response"] == "Score stands."
        assert data["proposed_correct"] is True
        assert data["resolved_at"] is not None

    async def test_resolve_without_proposed_correct_returns_400(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={"status": "resolved", "instructor_response": "Missing a decision."},
            headers=headers,
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "proposed_correct_required"

    async def test_resolve_writes_audit_entry(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={"status": "resolved", "instructor_response": "Score stands.", "proposed_correct": {"1": True}},
            headers=headers,
        )
        assert response.status_code == 200

        result = await db_session.execute(
            select(ReviewRequestAuditEntry).where(
                ReviewRequestAuditEntry.review_request_id == uuid.UUID(review_id)
            )
        )
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].event_type == "resolved"
        assert entries[0].actor_user_id == user_id

    async def test_reject_sets_status(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={"status": "rejected", "instructor_response": "No change."},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()[0]["status"] == "rejected"

    async def test_pending_status_is_rejected(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}
        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )

        response = await client.patch(
            f"/api/review-requests/{created.json()[0]['id']}",
            json={"status": "pending"},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_forbidden_for_staff_unrelated_to_course(
        self, client, create_user, login_user, db_session
    ):
        prof = await create_user(
            email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        prof_login = await login_user(email=prof.email)
        prof_headers = {"Authorization": f"Bearer {prof_login.json()['access_token']}"}

        grade = await _seed_grade(db_session, prof.id)
        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=prof_headers,
        )
        review_id = created.json()[0]["id"]

        outsider = await create_user(
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        outsider_login = await login_user(email=outsider.email)
        outsider_headers = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={"status": "resolved", "instructor_response": "Not my course."},
            headers=outsider_headers,
        )
        assert response.status_code == 403

    async def test_resolve_persists_proposed_score(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]
        assert created.json()[0]["current_score"] == grade.total_score

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={
                "status": "resolved",
                "instructor_response": "Adjusted.",
                "proposed_correct": {"1": True},
                "proposed_scores": {"1": 1.0},
            },
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()[0]["proposed_score"] == 1.0

        await db_session.refresh(grade)
        assert grade.total_score == 1.0
        assert grade.question_results["1"]["correct"] is True

        result = await db_session.execute(
            select(GradeAuditEntry).where(GradeAuditEntry.exam_grade_id == grade.id)
        )
        entries = result.scalars().all()
        assert len(entries) == 1
        assert entries[0].event_type == "manual_correction"
        assert entries[0].previous_total_score == 0.0
        assert entries[0].new_total_score == 1.0

    async def test_resolve_batch_with_independent_decisions(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id, question_results=_TWO_QUESTION_RESULTS)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1", "2"], "student_comment": "Please recheck both."},
            headers=headers,
        )
        assert created.status_code == 201
        review_id = created.json()[0]["id"]

        response = await client.patch(
            f"/api/review-requests/{review_id}",
            json={
                "status": "resolved",
                "instructor_response": "Q1 gets credit, Q2 stays wrong.",
                "proposed_correct": {"1": True, "2": False},
            },
            headers=headers,
        )
        assert response.status_code == 200
        by_question = {row["question_number"]: row for row in response.json()}
        assert by_question["1"]["proposed_correct"] is True
        assert by_question["2"]["proposed_correct"] is False

        await db_session.refresh(grade)
        assert grade.question_results["1"]["correct"] is True
        assert grade.question_results["1"]["score"] == 1.0
        assert grade.question_results["2"]["correct"] is False
        assert grade.question_results["2"]["score"] == 0.0
        # Q1 went 0/1 -> 1/1 (+1), Q2 went 1/1 -> 0/1 (-1): net unchanged.
        assert grade.total_score == 1.0


class TestListReviewRequestsForStaff:
    async def test_unauthenticated_returns_401(self, client):
        response = await client.get("/api/review-requests")
        assert response.status_code == 401

    async def test_student_role_forbidden(self, register_user, client):
        resp = await register_user()
        token = resp.json()["access_token"]
        response = await client.get(
            "/api/review-requests", headers={"Authorization": f"Bearer {token}"}
        )
        assert response.status_code == 403

    async def test_returns_enriched_requests_for_course_creator(
        self, client, create_user, login_user, db_session
    ):
        # Uses an explicit PROFESSOR (not the tests/exams ADMIN-promoting
        # authenticated_client override) so this genuinely exercises the
        # course-scoping path rather than the admin bypass.
        prof = await create_user(
            email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        login_resp = await login_user(email=prof.email)
        token = login_resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        grade = await _seed_grade(db_session, prof.id)
        await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "Please look again.", "proposed_scores": {"1": 1.0}},
            headers=headers,
        )

        response = await client.get("/api/review-requests", headers=headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["course_code"] == "COSC 499"
        assert data[0]["term"] == "Winter Session 1"
        assert data[0]["exam_name"] == "Midterm"

    async def test_excludes_requests_from_other_staffs_courses(
        self, client, create_user, login_user, db_session
    ):
        prof = await create_user(
            email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        prof_login = await login_user(email=prof.email)
        prof_headers = {"Authorization": f"Bearer {prof_login.json()['access_token']}"}

        grade = await _seed_grade(db_session, prof.id)
        await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=prof_headers,
        )

        # A second staff member (professor) with no relation to this course.
        outsider = await create_user(
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        outsider_login = await login_user(email=outsider.email)
        outsider_headers = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}

        response = await client.get("/api/review-requests", headers=outsider_headers)
        assert response.status_code == 200
        assert response.json() == []


class TestReviewRequestHistory:
    async def test_staff_can_read_review_request_history(self, authenticated_client, db_session):
        email = f"prof_{uuid.uuid4().hex[:6]}@test.com"
        client, token = await authenticated_client(email=email)
        user_id = await _get_user_id(db_session, email)
        grade = await _seed_grade(db_session, user_id)
        headers = {"Authorization": f"Bearer {token}"}

        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "Please review", "proposed_scores": {"1": 1.0}},
            headers=headers,
        )
        review_id = created.json()[0]["id"]

        resolved = await client.patch(
            f"/api/review-requests/{review_id}",
            json={
                "status": "resolved",
                "instructor_response": "Updated.",
                "proposed_correct": {"1": True},
                "proposed_scores": {"1": 1.0},
            },
            headers=headers,
        )
        assert resolved.status_code == 200

        response = await client.get(f"/api/review-requests/{review_id}/history", headers=headers)
        assert response.status_code == 200, response.json()
        history = response.json()
        assert len(history) == 1
        assert history[0]["event_type"] == "resolved"
        assert history[0]["actor_user_id"] == str(user_id)
        assert history[0]["actor_name"] is not None
        assert history[0]["changes"]["status"] == {"before": "pending", "after": "resolved"}

    async def test_student_can_read_own_history_but_not_actor(self, client, create_user, login_user, db_session):
        prof = await create_user(
            email=f"prof_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        prof_login = await login_user(email=prof.email)
        prof_headers = {"Authorization": f"Bearer {prof_login.json()['access_token']}"}

        student = await create_user(
            email=f"student_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.STUDENT
        )
        student_login = await login_user(email=student.email)
        student_headers = {"Authorization": f"Bearer {student_login.json()['access_token']}"}

        grade = await _seed_grade(db_session, prof.id, student.id)
        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "student_comment": "Please review", "proposed_scores": {"1": 1.0}},
            headers=student_headers,
        )
        review_id = created.json()[0]["id"]

        resolved = await client.patch(
            f"/api/review-requests/{review_id}",
            json={
                "status": "resolved",
                "instructor_response": "Reviewed.",
                "proposed_correct": {"1": True},
                "proposed_scores": {"1": 1.0},
            },
            headers=prof_headers,
        )
        assert resolved.status_code == 200

        response = await client.get(
            f"/api/review-requests/{review_id}/history",
            headers=student_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["actor_user_id"] is None
        assert data[0]["actor_name"] is None

    async def test_unrelated_staff_forbidden(self, client, create_user, login_user, db_session):
        owner = await create_user(
            email=f"owner_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        owner_login = await login_user(email=owner.email)
        owner_headers = {"Authorization": f"Bearer {owner_login.json()['access_token']}"}

        outsider = await create_user(
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com", role=UserRole.PROFESSOR
        )
        outsider_login = await login_user(email=outsider.email)
        outsider_headers = {"Authorization": f"Bearer {outsider_login.json()['access_token']}"}

        grade = await _seed_grade(db_session, owner.id)
        created = await client.post(
            f"/api/grades/{grade.id}/review-requests",
            json={"question_numbers": ["1"], "proposed_scores": {"1": 1.0}},
            headers=owner_headers,
        )
        review_id = created.json()[0]["id"]

        response = await client.get(
            f"/api/review-requests/{review_id}/history",
            headers=outsider_headers,
        )
        assert response.status_code == 403
