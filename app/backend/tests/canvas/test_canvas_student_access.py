import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from core import tokens
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.course_roster_entry import CourseRosterEntry
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.omr_detected_mark import MarkFieldType, OMRDetectedMark
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import UserRole
from services import grading_service


pytestmark = pytest.mark.db


async def _seed_canvas_result(
    db_session,
    create_user,
    *,
    released: bool = True,
    mapping_active: bool = True,
):
    professor = await create_user(
        email=f"professor-{uuid.uuid4()}@example.com",
        role=UserRole.PROFESSOR,
        student_number=None,
    )
    student = await create_user(
        email=f"student-{uuid.uuid4()}@example.com",
        role=UserRole.STUDENT,
    )
    course = Course(
        name="Canvas Course",
        academic_term_id=UBC_WINTER_SESSION_1_TERM_ID,
        source="canvas",
        created_by=professor.id,
    )
    db_session.add(course)
    await db_session.flush()

    omr_template = OMRTemplate(
        name="Canvas result template",
        page_count=1,
        mark_template_id="mark-template-1",
    )
    db_session.add(omr_template)
    await db_session.flush()

    exam_template = ExamTemplate(
        name="Canvas result template",
        created_by=professor.id,
        question_config={"1": {"choices": ["A", "B", "C", "D"]}},
        sections=[],
        total_questions=1,
        version=1,
        n_versions=1,
        omr_template_id=omr_template.id,
    )
    db_session.add(exam_template)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    exam = Exam(
        name="Canvas Midterm",
        start_time=now,
        end_time=now + timedelta(hours=1),
        role="student",
        released=released,
        course_id=course.id,
        created_by=professor.id,
        exam_template_id=exam_template.id,
    )
    db_session.add(exam)
    await db_session.flush()

    answer_key = ExamAnswerKey(
        exam_id=exam.id,
        exam_template_id=exam_template.id,
        answer_key={
            "1": {
                "grading_type": "single",
                "correct_choices": ["A"],
                "points": 1.0,
            }
        },
    )
    db_session.add(answer_key)
    await db_session.flush()

    scan = Scan(
        exam_id=exam.id,
        exam_template_id=exam_template.id,
        uploader_user_id=professor.id,
        path="scans/canvas-result.pdf",
        omr_scan_id="canvas-result-scan",
        status="completed",
    )
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(
        scan_id=scan.id,
        omr_template_id=omr_template.id,
        status="completed",
    )
    db_session.add(marking)
    await db_session.flush()

    db_session.add(
        OMRDetectedMark(
            marking_id=marking.id,
            field_type=MarkFieldType.QUESTION,
            field_index=1,
            detected_value="A",
            page_index=0,
            bounds={"x": 10, "y": 20, "width": 100, "height": 40},
            boxes=[
                {
                    "label": "A",
                    "selected": True,
                    "x": 15,
                    "y": 25,
                    "width": 20,
                    "height": 20,
                }
            ],
            confidence_score=0.99,
        )
    )

    grade = ExamGrade(
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
                "ambiguous": False,
            }
        },
        total_score=1.0,
        max_score=1.0,
        template_version=1,
        student_id=student.id,
        status="graded",
    )
    db_session.add(grade)

    mapping = CourseRosterEntry(
        course_id=course.id,
        user_id=student.id,
        email=student.email,
        first_name=student.first_name,
        last_name=student.last_name,
        student_number=student.student_number,
        source="canvas",
        canvas_user_id="42",
        active=mapping_active,
    )
    db_session.add(mapping)
    await db_session.flush()

    access_token = tokens.create_canvas_student_access_token(
        student.id,
        grade.id,
        mapping.canvas_user_id,
    )
    return {
        "student": student,
        "exam": exam,
        "grade": grade,
        "mapping": mapping,
        "access_token": access_token,
    }


def _request(access_token: str) -> dict[str, str]:
    return {"access_token": access_token}


def _assert_private_response(response) -> None:
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"


@pytest.mark.asyncio
async def test_student_can_open_own_released_result_without_login(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(db_session, create_user)

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(seeded["access_token"]),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(seeded["grade"].id)
    assert response.json()["student_id"] == str(seeded["student"].id)
    assert response.json()["question_results"]["1"]["correct_answers"] == []
    _assert_private_response(response)


@pytest.mark.asyncio
async def test_student_result_access_rejects_regular_login_token(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(db_session, create_user)
    login_token = tokens.create_access_token(str(seeded["student"].id))

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(login_token),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_canvas_student_access"
    assert login_token not in response.text


@pytest.mark.asyncio
async def test_student_result_access_rejects_unreleased_exam(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(
        db_session,
        create_user,
        released=False,
    )

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(seeded["access_token"]),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_canvas_student_access"


@pytest.mark.asyncio
async def test_student_result_access_rejects_inactive_canvas_mapping(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(
        db_session,
        create_user,
        mapping_active=False,
    )

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(seeded["access_token"]),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_canvas_student_access"


@pytest.mark.asyncio
async def test_student_result_access_rejects_changed_canvas_identity(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(db_session, create_user)
    seeded["mapping"].canvas_user_id = "84"
    await db_session.flush()

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(seeded["access_token"]),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_canvas_student_access"


@pytest.mark.asyncio
async def test_student_result_access_rejects_token_for_another_result(
    client,
    db_session,
    create_user,
):
    seeded = await _seed_canvas_result(db_session, create_user)
    wrong_result_token = tokens.create_canvas_student_access_token(
        seeded["student"].id,
        uuid.uuid4(),
        seeded["mapping"].canvas_user_id,
    )

    response = await client.post(
        "/api/canvas/student-results/access",
        json=_request(wrong_result_token),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_canvas_student_access"


@pytest.mark.asyncio
async def test_canvas_token_authorizes_only_its_result_resources(
    client,
    db_session,
    create_user,
    monkeypatch,
):
    seeded = await _seed_canvas_result(db_session, create_user)
    page_image = AsyncMock(return_value=b"student-page-image")
    monkeypatch.setattr(grading_service, "get_scan_page_image", page_image)
    body = _request(seeded["access_token"])

    annotations = await client.post(
        "/api/canvas/student-results/pages/0/annotations",
        json=body,
    )
    identity = await client.post(
        "/api/canvas/student-results/identity",
        json=body,
    )
    page_identity = await client.post(
        "/api/canvas/student-results/pages/0/identity",
        json=body,
    )
    version = await client.post(
        "/api/canvas/student-results/pages/0/version",
        json=body,
    )
    image = await client.post(
        "/api/canvas/student-results/pages/0/image",
        json=body,
    )

    assert annotations.status_code == 200
    assert annotations.json()[0]["correct_answers"] == []
    assert identity.status_code == 200
    assert identity.json()["fields"] == []
    assert page_identity.status_code == 200
    assert version.status_code == 200
    assert version.json() == {"field": None, "detected_version": None}
    assert image.status_code == 200
    assert image.content == b"student-page-image"
    assert image.headers["content-type"] == "image/jpeg"
    for response in (annotations, identity, page_identity, version, image):
        _assert_private_response(response)


@pytest.mark.asyncio
async def test_validation_error_does_not_reflect_canvas_access_token(client):
    secret = "student-result-secret-that-must-not-be-reflected"

    response = await client.post(
        "/api/canvas/student-results/access",
        json={"access_token": {"unexpected": secret}},
    )

    assert response.status_code == 422
    assert secret not in response.text
