import uuid
from datetime import datetime, timezone

import pytest
from tests.auth.conftest import register_user, create_user, login_user

from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import UserRole

pytestmark = pytest.mark.db


async def _create_template(client, token):
    resp = await client.post(
        "/api/exam-templates?blueprint=ubco_100",
        headers={"Authorization": f"Bearer {token}"},
    )
    return resp.json()["id"]


async def _create_exam(client, token, course_id, template_id, name="Midterm"):
    return await client.post(
        "/api/exams",
        json={
            "name": name,
            "description": "2026S midterm 1",
            "start_time": "2026-06-01T09:00:00+00:00",
            "end_time": "2026-06-01T11:00:00+00:00",
            "role": "student",
            "course_id": course_id,
            "exam_template_id": template_id,
        },
        headers={"Authorization": f"Bearer {token}"},
    )


async def _create_switchable_exam(client, token):
    headers = {"Authorization": f"Bearer {token}"}
    course = await client.post(
        "/api/courses",
        json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers=headers,
    )
    original_template_id = await _create_template(client, token)
    replacement_template_id = await _create_template(client, token)
    exam = await _create_exam(
        client, token, course.json()["id"], original_template_id
    )
    return headers, exam.json(), original_template_id, replacement_template_id


class TestCreateExam:
    async def test_create_exam_success(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "description": "2026S midterm 1",
                "start_time": "2026-06-01T09:00:00",
                "end_time": "2026-06-01T11:00:00",
                "role": "student",
                "course_id": course_id,
                "exam_template_id": template_id,
            },
            headers=headers,
        )
        assert response.status_code == 201
        assert response.json()["name"] == "Midterm"
        assert response.json()["start_time"].startswith("2026-06-01T09:00:00")

    async def test_create_exam_without_schedule(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template_id = await _create_template(client, token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Practice Exam",
                "description": "Schedule to be announced",
                "role": "student",
                "course_id": course.json()["id"],
                "exam_template_id": template_id,
            },
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["start_time"] is None
        assert response.json()["end_time"] is None

    async def test_professor_cannot_create_exam_for_another_professors_course(
        self, staff_client
    ):
        client, owner_token = await staff_client()
        _, other_token = await staff_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        template_id = await _create_template(client, other_token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "description": "2026S midterm 1",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
                "course_id": course.json()["id"],
                "exam_template_id": template_id,
            },
            headers=other_headers,
        )

        assert response.status_code == 403

    async def test_professor_cannot_create_exam_with_another_professors_template(
        self, staff_client
    ):
        client, owner_token = await staff_client()
        _, other_token = await staff_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        other_template_id = await _create_template(client, other_token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "description": "2026S midterm 1",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
                "course_id": course.json()["id"],
                "exam_template_id": other_template_id,
            },
            headers=owner_headers,
        )

        assert response.status_code == 403

    async def test_create_exam_missing_name(self, authenticated_client, client):
        client, token = await authenticated_client()

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {token}"},
        )
        course_id = course.json()["id"]

        response = await client.post(
            "/api/exams",
            json={
                "description": "No name",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
                "course_id": course_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_exam_missing_course_id(self, authenticated_client, client):
        client, token = await authenticated_client()

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_exam_invalid_course_id(self, authenticated_client, client):
        client, token = await authenticated_client()

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
                "course_id": "67",
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_exam_end_before_start(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-01T11:00:00+00:00",
                "end_time": "2026-06-01T09:00:00+00:00",
                "role": "student",
                "course_id": course_id,
                "exam_template_id": template_id,
            },
            headers=headers,
        )
        assert response.status_code == 422

    async def test_create_exam_rejects_partial_schedule(
        self, authenticated_client, client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template_id = await _create_template(client, token)

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-01T09:00:00+00:00",
                "role": "student",
                "course_id": course.json()["id"],
                "exam_template_id": template_id,
            },
            headers=headers,
        )

        assert response.status_code == 422
        assert response.json()["error"]["message"] == (
            "start_time and end_time must both be provided or both omitted."
        )

    async def test_create_exam_unauthenticated(self, client):
        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-01T09:00:00+00:00",
                "end_time": "2026-06-01T11:00:00+00:00",
                "role": "student",
                "course_id": str(uuid.uuid4()),
            },
        )
        assert response.status_code == 401


class TestListExamsByCourse:
    async def test_list_exams_by_course(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        await _create_exam(client, token, course_id, template_id, "Exam 1")
        await _create_exam(client, token, course_id, template_id, "Exam 2")

        response = await client.get(
            f"/api/exams/course/{course_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 2

    async def test_list_exams_by_course_empty(self, authenticated_client, client):
        client, token = await authenticated_client()

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {token}"},
        )
        course_id = course.json()["id"]

        response = await client.get(
            f"/api/exams/course/{course_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_answer_keys_complete_is_separate_from_having_a_key(
        self, authenticated_client, client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Three versions",
                "question_config": {"1": {"choices": ["A", "B"]}},
                "n_versions": 3,
            },
            headers=headers,
        )
        exam = await _create_exam(
            client,
            token,
            course.json()["id"],
            template.json()["id"],
        )

        async def create_key(version: str, choices: list[str]):
            return await client.post(
                f"/api/exams/{exam.json()['id']}/answer-keys",
                json={
                    "exam_template_id": template.json()["id"],
                    "exam_version": version,
                    "answer_key": {
                        "1": {
                            "grading_type": "single",
                            "correct_choices": choices,
                        }
                    },
                },
                headers=headers,
            )

        first_key = await create_key("A", [])
        assert first_key.status_code == 201

        response = await client.get(
            f"/api/exams/course/{course.json()['id']}", headers=headers
        )
        listed = response.json()[0]
        assert listed["has_answer_key"] is True
        assert listed["answer_keys_complete"] is False

        for version in ("B", "C"):
            assert (await create_key(version, ["A"])).status_code == 201
        await client.patch(
            f"/api/answer-keys/{first_key.json()['id']}",
            json={
                "answer_key": {
                    "1": {
                        "grading_type": "single",
                        "correct_choices": ["A"],
                    }
                }
            },
            headers=headers,
        )

        response = await client.get(
            f"/api/exams/course/{course.json()['id']}", headers=headers
        )
        assert response.json()[0]["answer_keys_complete"] is True

        single_response = await client.get(
            f"/api/exams/{exam.json()['id']}", headers=headers
        )
        assert single_response.json()["answer_keys_complete"] is True

    async def test_list_exams_by_course_has_scans_reflects_uploaded_scans(
        self, authenticated_client, client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        scanned_exam = (await _create_exam(client, token, course_id, template_id, "Exam With Scans")).json()
        unscanned_exam = (await _create_exam(client, token, course_id, template_id, "Exam Without Scans")).json()

        from models.user import User
        from sqlalchemy import select
        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()

        db_session.add(Scan(
            exam_id=uuid.UUID(scanned_exam["id"]),
            exam_template_id=uuid.UUID(template_id),
            uploader_user_id=uploader.id,
            path="scans/test.pdf",
        ))
        await db_session.flush()

        response = await client.get(f"/api/exams/course/{course_id}", headers=headers)

        assert response.status_code == 200
        by_id = {exam["id"]: exam for exam in response.json()}
        assert by_id[scanned_exam["id"]]["has_scans"] is True
        assert by_id[unscanned_exam["id"]]["has_scans"] is False

    async def test_list_exams_by_course_is_graded_only_when_all_scans_graded(
        self, authenticated_client, client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam_resp = (await _create_exam(client, token, course_id, template_id, "Partially Graded Exam")).json()
        exam_id = uuid.UUID(exam_resp["id"])
        template_uuid = uuid.UUID(template_id)

        from models.user import User
        from sqlalchemy import select
        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()

        omr_template = OMRTemplate(name="OMR", page_count=2)
        db_session.add(omr_template)
        await db_session.flush()

        answer_key = ExamAnswerKey(
            exam_id=exam_id,
            exam_template_id=template_uuid,
            answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
        )
        db_session.add(answer_key)
        await db_session.flush()

        scan_graded = Scan(
            exam_id=exam_id, exam_template_id=template_uuid,
            uploader_user_id=uploader.id, path="scans/graded.pdf",
        )
        scan_pending = Scan(
            exam_id=exam_id, exam_template_id=template_uuid,
            uploader_user_id=uploader.id, path="scans/pending.pdf",
        )
        db_session.add_all([scan_graded, scan_pending])
        await db_session.flush()

        marking = OMRMarking(scan_id=scan_graded.id, omr_template_id=omr_template.id, status="completed")
        db_session.add(marking)
        await db_session.flush()
        db_session.add(ExamGrade(
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results={},
            total_score=1.0,
            max_score=1.0,
            template_version=1,
            student_id=None,
            status="graded",
        ))
        await db_session.flush()

        response = await client.get(f"/api/exams/course/{course_id}", headers=headers)
        assert response.status_code == 200
        exam_data = next(e for e in response.json() if e["id"] == exam_resp["id"])
        assert exam_data["total_scans"] == 2
        assert exam_data["graded_scans"] == 1
        assert exam_data["has_scans"] is True
        assert exam_data["is_graded"] is False

        # Grade the remaining scan too — only now should the exam flip to "Graded".
        marking2 = OMRMarking(scan_id=scan_pending.id, omr_template_id=omr_template.id, status="completed")
        db_session.add(marking2)
        await db_session.flush()
        db_session.add(ExamGrade(
            omr_marking_id=marking2.id,
            exam_answer_key_id=answer_key.id,
            question_results={},
            total_score=1.0,
            max_score=1.0,
            template_version=1,
            student_id=None,
            status="graded",
        ))
        await db_session.flush()

        response2 = await client.get(f"/api/exams/course/{course_id}", headers=headers)
        exam_data2 = next(e for e in response2.json() if e["id"] == exam_resp["id"])
        assert exam_data2["total_scans"] == 2
        assert exam_data2["graded_scans"] == 2
        assert exam_data2["is_graded"] is True

    async def test_list_exams_by_course_reports_pending_review_request_count(
        self, authenticated_client, client, db_session
    ):
        from models.review_request import ReviewRequest
        from models.user import User
        from sqlalchemy import select

        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam_resp = (await _create_exam(client, token, course_id, template_id, "Exam With Regrades")).json()
        exam_id = uuid.UUID(exam_resp["id"])
        template_uuid = uuid.UUID(template_id)

        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()

        # Re-grade requests are only counted for released exams (a student
        # can't see -- let alone request a re-grade on -- an unreleased grade).
        exam = await db_session.get(Exam, exam_id)
        exam.released = True

        answer_key = ExamAnswerKey(
            exam_id=exam_id,
            exam_template_id=template_uuid,
            answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
        )
        db_session.add(answer_key)
        await db_session.flush()

        scan = Scan(
            exam_id=exam_id, exam_template_id=template_uuid,
            uploader_user_id=uploader.id, path="scans/graded.pdf",
        )
        db_session.add(scan)
        await db_session.flush()

        omr_template = OMRTemplate(name="OMR", page_count=2)
        db_session.add(omr_template)
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
            student_id=uploader.id,
            status="graded",
        )
        db_session.add(grade)
        await db_session.flush()

        db_session.add(ReviewRequest(
            exam_grade_id=grade.id,
            student_id=uploader.id,
            question_number="1",
            student_comment="Please recheck",
        ))
        resolved_review = ReviewRequest(
            exam_grade_id=grade.id,
            student_id=uploader.id,
            question_number="2",
            student_comment="Already resolved",
            status="resolved",
        )
        db_session.add(resolved_review)
        await db_session.flush()

        response = await client.get(f"/api/exams/course/{course_id}", headers=headers)
        assert response.status_code == 200
        exam_data = next(e for e in response.json() if e["id"] == exam_resp["id"])
        assert exam_data["pending_review_request_count"] == 1

        # Closing the exam again should hide the badge, even though the
        # review request row itself is untouched.
        exam.released = False
        await db_session.flush()

        response2 = await client.get(f"/api/exams/course/{course_id}", headers=headers)
        exam_data2 = next(e for e in response2.json() if e["id"] == exam_resp["id"])
        assert exam_data2["pending_review_request_count"] == 0

    async def test_list_exams_by_course_reports_ambiguous_grade_count(
        self, authenticated_client, client, db_session
    ):
        from models.user import User
        from sqlalchemy import select

        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam_resp = (await _create_exam(client, token, course_id, template_id, "Exam With Ambiguous Marks")).json()
        exam_id = uuid.UUID(exam_resp["id"])
        template_uuid = uuid.UUID(template_id)

        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()

        answer_key = ExamAnswerKey(
            exam_id=exam_id,
            exam_template_id=template_uuid,
            answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
        )
        db_session.add(answer_key)
        await db_session.flush()

        omr_template = OMRTemplate(name="OMR", page_count=2)
        db_session.add(omr_template)
        await db_session.flush()

        scan_ambiguous = Scan(
            exam_id=exam_id, exam_template_id=template_uuid,
            uploader_user_id=uploader.id, path="scans/ambiguous.pdf",
        )
        scan_clean = Scan(
            exam_id=exam_id, exam_template_id=template_uuid,
            uploader_user_id=uploader.id, path="scans/clean.pdf",
        )
        db_session.add_all([scan_ambiguous, scan_clean])
        await db_session.flush()

        marking_ambiguous = OMRMarking(scan_id=scan_ambiguous.id, omr_template_id=omr_template.id, status="completed")
        marking_clean = OMRMarking(scan_id=scan_clean.id, omr_template_id=omr_template.id, status="completed")
        db_session.add_all([marking_ambiguous, marking_clean])
        await db_session.flush()

        db_session.add(ExamGrade(
            omr_marking_id=marking_ambiguous.id,
            exam_answer_key_id=answer_key.id,
            question_results={"1": {"grading_type": "single", "student_answers": ["A", "B"], "ambiguous": True}},
            total_score=1.0,
            max_score=1.0,
            template_version=1,
            student_id=uploader.id,
            status="graded",
        ))
        db_session.add(ExamGrade(
            omr_marking_id=marking_clean.id,
            exam_answer_key_id=answer_key.id,
            question_results={"1": {"grading_type": "single", "student_answers": ["A"], "ambiguous": False}},
            total_score=1.0,
            max_score=1.0,
            template_version=1,
            student_id=None,
            status="graded",
        ))
        await db_session.flush()

        response = await client.get(f"/api/exams/course/{course_id}", headers=headers)
        assert response.status_code == 200
        exam_data = next(e for e in response.json() if e["id"] == exam_resp["id"])
        assert exam_data["ambiguous_grade_count"] == 1

    async def test_list_exams_by_course_unauthenticated(self, client):
        response = await client.get(f"/api/exams/course/{uuid.uuid4()}")
        assert response.status_code == 401

    async def test_student_sees_all_course_exams_with_only_own_grade_marked_graded(
        self, create_user, login_user, client, db_session
    ):
        professor = await create_user(
            email=f"prof_{uuid.uuid4().hex[:6]}@test.com",
            role=UserRole.PROFESSOR,
            student_number=None,
        )
        student = await create_user(email=f"student_{uuid.uuid4().hex[:6]}@test.com")

        course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=professor.id)
        db_session.add(course)
        await db_session.flush()

        db_session.add(Enrolment(course_id=course.id, user_id=student.id, role="student"))

        template = ExamTemplate(
            name="Template",
            created_by=professor.id,
            question_config={"1": {"choices": ["A", "B"]}},
            total_questions=1,
            version=1,
            n_versions=1,
        )
        db_session.add(template)
        await db_session.flush()

        graded_exam = Exam(
            name="Released Midterm",
            description=None,
            start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
            role="student",
            course_id=course.id,
            created_by=professor.id,
            exam_template_id=template.id,
        )
        hidden_exam = Exam(
            name="Unreleased Final",
            description=None,
            start_time=datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc),
            end_time=datetime(2026, 6, 2, 11, 0, tzinfo=timezone.utc),
            role="student",
            course_id=course.id,
            created_by=professor.id,
            exam_template_id=template.id,
        )
        db_session.add_all([graded_exam, hidden_exam])
        await db_session.flush()
        graded_exam.released = True
        await db_session.flush()

        answer_key = ExamAnswerKey(
            exam_id=graded_exam.id,
            exam_template_id=template.id,
            answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
        )
        omr_template = OMRTemplate(name="OMR", page_count=2)
        db_session.add_all([answer_key, omr_template])
        await db_session.flush()

        scan = Scan(
            exam_id=graded_exam.id,
            exam_template_id=template.id,
            uploader_user_id=professor.id,
            path="scans/test.pdf",
        )
        db_session.add(scan)
        await db_session.flush()

        marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_template.id, status="completed")
        db_session.add(marking)
        await db_session.flush()

        db_session.add(ExamGrade(
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results={
                "1": {
                    "grading_type": "single",
                    "student_answers": ["A"],
                    "correct_answers": ["A"],
                    "correct": True,
                    "score": 1.0,
                    "max_score": 1.0,
                }
            },
            total_score=1.0,
            max_score=1.0,
            template_version=1,
            student_id=student.id,
            status="graded",
        ))
        await db_session.flush()

        token = (await login_user(email=student.email)).json()["access_token"]
        response = await client.get(
            f"/api/exams/course/{course.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200
        data = response.json()
        by_name = {exam["name"]: exam for exam in data}
        assert set(by_name) == {"Released Midterm", "Unreleased Final"}
        assert by_name["Released Midterm"]["is_graded"] is True
        assert by_name["Unreleased Final"]["is_graded"] is False


class TestListMyExams:
    async def test_list_my_exams(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        await _create_exam(client, token, course_id, template_id)

        response = await client.get(
            "/api/exams/my",
            headers=headers,
        )
        assert response.status_code == 200
        assert len(response.json()) == 1

    async def test_list_my_exams_only_own(self, authenticated_client, client):
        client_a, token_a = await authenticated_client(email="a@example.com")
        client_b, token_b = await authenticated_client(email="b@example.com")

        course = await client_a.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers={"Authorization": f"Bearer {token_a}"},
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client_a, token_a)

        await _create_exam(client_a, token_a, course_id, template_id)

        response = await client_b.get(
            "/api/exams/my",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    async def test_list_my_exams_unauthenticated(self, client):
        response = await client.get("/api/exams/my")
        assert response.status_code == 401


class TestGetExam:
    async def test_get_exam_success(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam = await _create_exam(client, token, course_id, template_id)
        exam_id = exam.json()["id"]

        response = await client.get(
            f"/api/exams/{exam_id}",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["id"] == exam_id

    async def test_get_exam_not_found(self, authenticated_client, client):
        client, token = await authenticated_client()

        response = await client.get(
            f"/api/exams/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_get_exam_unauthenticated(self, client):
        response = await client.get(f"/api/exams/{uuid.uuid4()}")
        assert response.status_code == 401


class TestUpdateExam:
    async def test_update_exam_name(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam = await _create_exam(client, token, course_id, template_id)
        exam_id = exam.json()["id"]

        response = await client.patch(
            f"/api/exams/{exam_id}",
            json={"name": "Final"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Final"

    async def test_update_and_clear_exam_schedule(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template_id = await _create_template(client, token)
        exam = await _create_exam(client, token, course.json()["id"], template_id)

        updated = await client.patch(
            f"/api/exams/{exam.json()['id']}",
            json={
                "start_time": "2026-06-02T13:00:00+00:00",
                "end_time": "2026-06-02T14:30:00+00:00",
            },
            headers=headers,
        )
        cleared = await client.patch(
            f"/api/exams/{exam.json()['id']}",
            json={"start_time": None, "end_time": None},
            headers=headers,
        )

        assert updated.status_code == 200
        assert updated.json()["start_time"] == "2026-06-02T13:00:00Z"
        assert updated.json()["end_time"] == "2026-06-02T14:30:00Z"
        assert cleared.status_code == 200
        assert cleared.json()["start_time"] is None
        assert cleared.json()["end_time"] is None

    async def test_update_exam_rejects_partial_schedule(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template_id = await _create_template(client, token)
        exam = await _create_exam(client, token, course.json()["id"], template_id)

        response = await client.patch(
            f"/api/exams/{exam.json()['id']}",
            json={"start_time": None},
            headers=headers,
        )

        assert response.status_code == 422

    async def test_professor_cannot_update_another_professors_exam(
        self, staff_client
    ):
        client, owner_token = await staff_client()
        _, other_token = await staff_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, owner_token)
        exam = await _create_exam(client, owner_token, course_id, template_id)

        response = await client.patch(
            f"/api/exams/{exam.json()['id']}",
            json={"name": "Final"},
            headers=other_headers,
        )

        assert response.status_code == 403

    async def test_professor_cannot_assign_another_professors_template(
        self, staff_client
    ):
        client, owner_token = await staff_client()
        _, other_token = await staff_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = course.json()["id"]
        own_template_id = await _create_template(client, owner_token)
        other_template_id = await _create_template(client, other_token)
        exam = await _create_exam(client, owner_token, course_id, own_template_id)

        response = await client.patch(
            f"/api/exams/{exam.json()['id']}",
            json={"exam_template_id": other_template_id},
            headers=owner_headers,
        )

        assert response.status_code == 403

    async def test_can_change_template_before_keys_or_scans_exist(
        self, authenticated_client, client
    ):
        client, token = await authenticated_client()
        headers, exam, _, replacement_template_id = await _create_switchable_exam(
            client, token
        )

        response = await client.patch(
            f"/api/exams/{exam['id']}",
            json={"exam_template_id": replacement_template_id},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["exam_template_id"] == replacement_template_id

    async def test_changing_template_requires_and_honors_key_deletion_confirmation(
        self, authenticated_client, client, db_session
    ):
        client, token = await authenticated_client()
        headers, exam, original_template_id, replacement_template_id = (
            await _create_switchable_exam(client, token)
        )
        answer_key = ExamAnswerKey(
            exam_id=uuid.UUID(exam["id"]),
            exam_template_id=uuid.UUID(original_template_id),
            answer_key={"1": {"grading_type": "single", "correct_choices": ["A"]}},
        )
        db_session.add(answer_key)
        await db_session.flush()

        unconfirmed = await client.patch(
            f"/api/exams/{exam['id']}",
            json={"exam_template_id": replacement_template_id},
            headers=headers,
        )

        assert unconfirmed.status_code == 409
        assert unconfirmed.json()["error"]["code"] == "answer_keys_require_reset"
        assert await db_session.get(ExamAnswerKey, answer_key.id) is not None

        confirmed = await client.patch(
            f"/api/exams/{exam['id']}",
            json={
                "exam_template_id": replacement_template_id,
                "delete_answer_keys": True,
            },
            headers=headers,
        )

        assert confirmed.status_code == 200
        assert confirmed.json()["exam_template_id"] == replacement_template_id
        assert await db_session.get(ExamAnswerKey, answer_key.id) is None

    async def test_cannot_change_template_after_scans_exist(
        self, authenticated_client, client, db_session
    ):
        client, token = await authenticated_client()
        headers, exam, original_template_id, replacement_template_id = (
            await _create_switchable_exam(client, token)
        )
        exam_record = await db_session.get(Exam, uuid.UUID(exam["id"]))
        db_session.add(
            Scan(
                exam_id=exam_record.id,
                exam_template_id=uuid.UUID(original_template_id),
                uploader_user_id=exam_record.created_by,
                path="scans/template-switch-blocked.pdf",
            )
        )
        await db_session.flush()

        response = await client.patch(
            f"/api/exams/{exam['id']}",
            json={
                "exam_template_id": replacement_template_id,
                "delete_answer_keys": True,
            },
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "exam_has_scans"
        await db_session.refresh(exam_record)
        assert str(exam_record.exam_template_id) == original_template_id

    async def test_can_assign_replacement_when_scanned_exam_template_is_missing(
        self, authenticated_client, client, db_session
    ):
        client, token = await authenticated_client()
        headers, exam, original_template_id, replacement_template_id = (
            await _create_switchable_exam(client, token)
        )
        exam_record = await db_session.get(Exam, uuid.UUID(exam["id"]))
        db_session.add(
            Scan(
                exam_id=exam_record.id,
                exam_template_id=None,
                uploader_user_id=exam_record.created_by,
                path="scans/detached-template.pdf",
            )
        )
        exam_record.exam_template_id = None
        await db_session.flush()

        response = await client.patch(
            f"/api/exams/{exam['id']}",
            json={"exam_template_id": replacement_template_id},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["exam_template_id"] == replacement_template_id

    async def test_update_exam_not_found(self, authenticated_client, client):
        client, token = await authenticated_client()

        response = await client.patch(
            f"/api/exams/{uuid.uuid4()}",
            json={"name": "X"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_update_exam_invalid_times(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam = await _create_exam(client, token, course_id, template_id)
        exam_id = exam.json()["id"]

        response = await client.patch(
            f"/api/exams/{exam_id}",
            json={
                "start_time": "2026-06-01T11:00:00+00:00",
                "end_time": "2026-06-01T09:00:00+00:00",
            },
            headers=headers,
        )
        assert response.status_code == 422

    async def test_update_exam_unauthenticated(self, client):
        response = await client.patch(
            f"/api/exams/{uuid.uuid4()}",
            json={"name": "X"},
        )
        assert response.status_code == 401


class TestDeleteExam:
    async def test_delete_exam_success(self, authenticated_client, client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam = await _create_exam(client, token, course_id, template_id)
        exam_id = exam.json()["id"]

        response = await client.delete(
            f"/api/exams/{exam_id}",
            headers=headers,
        )
        assert response.status_code == 204

        await client.delete(f"/api/exams/{exam_id}", headers=headers)
        response = await client.get(f"/api/exams/{exam_id}", headers=headers)
        assert response.status_code == 404

    async def test_professor_can_delete_own_course_exam(self, staff_client):
        client, token = await staff_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, token)

        exam = await _create_exam(client, token, course_id, template_id)
        exam_id = exam.json()["id"]

        response = await client.delete(f"/api/exams/{exam_id}", headers=headers)

        assert response.status_code == 204

    async def test_professor_cannot_delete_another_professors_exam(
        self, staff_client
    ):
        client, owner_token = await staff_client()
        _, other_token = await staff_client()
        owner_headers = {"Authorization": f"Bearer {owner_token}"}
        other_headers = {"Authorization": f"Bearer {other_token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=owner_headers,
        )
        course_id = course.json()["id"]
        template_id = await _create_template(client, owner_token)
        exam = await _create_exam(client, owner_token, course_id, template_id)

        response = await client.delete(
            f"/api/exams/{exam.json()['id']}",
            headers=other_headers,
        )

        assert response.status_code == 403

    async def test_delete_exam_not_found(self, authenticated_client, client):
        client, token = await authenticated_client()

        response = await client.delete(
            f"/api/exams/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_delete_exam_unauthenticated(self, client):
        response = await client.delete(f"/api/exams/{uuid.uuid4()}")
        assert response.status_code == 401
