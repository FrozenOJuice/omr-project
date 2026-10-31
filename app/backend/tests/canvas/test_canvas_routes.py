import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
import uuid

import pytest
from sqlalchemy import select

from core.tokens import decode_canvas_student_access_token
from integrations.canvas_client import CanvasRequestError
from errors.exceptions import ForbiddenError
from models.canvas_connection import CanvasConnection
from models.canvas_assignment_link import CanvasAssignmentLink
from models.canvas_course_link import CanvasCourseLink
from models.canvas_grade_release import CanvasGradeRelease
from models.canvas_grade_release_attempt import (
    CanvasGradeReleaseAttempt,
    CanvasGradeReleaseRecipient,
)
from models.course import Course
from models.academic_term import AcademicTermYearFormat, UBC_WINTER_SESSION_1_TERM_ID
from models.course_roster_entry import CourseRosterEntry
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import User
from models.user import UserRole
from services import canvas_courses as canvas_course_service
from services import canvas_assignments, canvas_roster, course_invites
from schemas.canvas_schema import CanvasConnectionResponse
from services import canvas_connection, canvas_grades
from services.email_service import EmailDeliveryError


def canvas_student(
    canvas_user_id: str | int,
    name: str,
    email: str,
    student_number: str,
) -> dict:
    return {
        "id": canvas_user_id,
        "name": name,
        "email": email,
        "login_id": email,
        "sis_user_id": student_number,
    }


async def professor_headers(create_user, login_user) -> dict[str, str]:
    await create_user(
        email="professor@example.com",
        role=UserRole.PROFESSOR,
        student_number=None,
    )
    response = await login_user(email="professor@example.com")
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def connected_professor_headers(create_user, login_user, db_session):
    headers = await professor_headers(create_user, login_user)
    professor = (
        await db_session.execute(
            select(User).where(User.email == "professor@example.com")
        )
    ).scalar_one()
    db_session.add(
        CanvasConnection(
            user_id=professor.id,
            access_token_encrypted="encrypted-token",
        )
    )
    await db_session.commit()
    return headers


def test_canvas_summer_term_maps_to_the_preceding_academic_year():
    term_name, calendar_year = canvas_course_service._course_period(
        {
            "term": {
                "name": "Summer Session 1",
                "start_at": "2027-05-01T00:00:00Z",
            }
        }
    )

    assert term_name == "Summer Session 1"
    assert calendar_year == 2027
    assert canvas_course_service._academic_year_start(
        calendar_year,
        AcademicTermYearFormat.FOLLOWING_YEAR,
    ) == 2026


@pytest.mark.asyncio
async def test_professor_can_connect_with_personal_access_token(
    client, create_user, login_user, monkeypatch
):
    connect = AsyncMock(
        return_value=CanvasConnectionResponse(
            connected=True,
            user_name="Canvas Professor",
            login_id="professor@example.com",
        )
    )
    monkeypatch.setattr(canvas_connection, "connect", connect)

    response = await client.post(
        "/api/canvas/connection",
        json={"access_token": "personal-secret-token"},
        headers=await professor_headers(create_user, login_user),
    )

    assert response.status_code == 200
    assert response.json()["user_name"] == "Canvas Professor"
    assert "access_token" not in response.json()
    assert connect.await_args.args[2] == "personal-secret-token"


@pytest.mark.asyncio
async def test_rejected_canvas_token_is_not_reflected_in_response(
    client, create_user, login_user
):
    access_token = "s" * 4097

    response = await client.post(
        "/api/canvas/connection",
        json={"access_token": access_token},
        headers=await professor_headers(create_user, login_user),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_canvas_access_token"
    assert access_token not in response.text


@pytest.mark.asyncio
async def test_canvas_calls_do_not_commit_the_callers_session(monkeypatch):
    db = AsyncMock()
    connection_db = AsyncMock()
    connection = CanvasConnection(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        access_token_encrypted=canvas_connection._cipher().encrypt("access-token"),
    )
    client = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = client
    operation = AsyncMock(return_value={"id": "9007199254740993"})

    @asynccontextmanager
    async def connection_session(_db):
        yield connection_db

    monkeypatch.setattr(
        canvas_connection, "get_connection", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(canvas_connection, "_connection_session", connection_session)
    monkeypatch.setattr(canvas_connection, "_client", lambda: context)

    result = await canvas_connection.call_canvas(db, connection.user_id, operation)

    assert result == {"id": "9007199254740993"}
    db.commit.assert_not_awaited()
    connection_db.commit.assert_awaited_once()


def test_canvas_permission_errors_do_not_request_reconnection():
    error = canvas_connection._service_error(
        CanvasRequestError("forbidden", status_code=403)
    )

    assert isinstance(error, ForbiddenError)
    assert error.code == "canvas_permission_denied"


@pytest.mark.asyncio
async def test_student_cannot_use_canvas_integration(client, authenticated_client):
    authenticated, token = await authenticated_client()

    response = await authenticated.get(
        "/api/canvas/connection",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_canvas_capability_reports_when_integration_is_unavailable(
    client, create_user, login_user, monkeypatch
):
    monkeypatch.setattr(canvas_connection, "is_configured", lambda: False)
    monkeypatch.setattr(canvas_connection, "settings_url", lambda: None)

    response = await client.get(
        "/api/canvas/capabilities",
        headers=await professor_headers(create_user, login_user),
    )

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "instructor_only": True,
        "settings_url": None,
    }


@pytest.mark.asyncio
async def test_canvas_roster_preserves_ids_above_javascript_safe_integer(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    large_id = "9007199254740993"
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    monkeypatch.setattr(
        canvas_roster,
        "call_canvas",
        AsyncMock(
            return_value=[
                canvas_student(
                    large_id,
                    "Large Id Student",
                    "large-id@example.com",
                    "10000001",
                )
            ]
        ),
    )

    response = await client.get(
        f"/api/canvas/courses/{large_id}/students", headers=headers
    )

    assert response.status_code == 200
    assert response.json()["course_id"] == large_id
    assert response.json()["students"][0]["id"] == large_id


@pytest.mark.asyncio
async def test_professor_can_import_a_canvas_course_once(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    existing_student = await create_user(
        email="one@example.com",
        role=UserRole.STUDENT,
        student_number="10000001",
    )
    canvas_courses = [
        {
            "id": 42,
            "name": "Integration Test Course",
            "course_code": "CANVAS 101",
            "term": {"name": "Winter Session 1", "start_at": "2026-09-01T00:00:00Z"},
        }
    ]
    canvas_roster = [
        canvas_student(1, "Test Student One", "one@example.com", "10000001"),
        canvas_student(2, "Test Student Two", "two@example.com", "10000002"),
    ]
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                canvas_courses,
                canvas_roster,
                canvas_courses,
                canvas_courses,
            ]
        ),
    )

    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    available = await client.get("/api/canvas/courses", headers=headers)
    duplicate = await client.post("/api/canvas/courses/42/import", headers=headers)

    assert imported.status_code == 201
    assert imported.json()["name"] == "CANVAS 101 - Integration Test Course"
    assert imported.json()["academic_term"]["name"] == "Winter Session 1"
    assert imported.json()["academic_term"]["term_type"] == "preset"
    assert imported.json()["academic_term"]["code"] == "winter-session-1"
    assert imported.json()["academic_year_start"] == 2026
    assert imported.json()["student_count"] == 2
    assert imported.json()["source"] == "canvas"
    assert imported.json()["can_manage_canvas"] is True
    assert imported.json()["canvas_link"]["canvas_course_id"] == "42"
    roster = await client.get(
        f"/api/courses/{imported.json()['id']}/students",
        headers=headers,
    )
    assert len(roster.json()) == 2
    linked_student = next(
        student for student in roster.json() if student["email"] == "one@example.com"
    )
    assert linked_student["user_id"] == str(existing_student.id)
    assert linked_student["account_status"] == "linked"
    assert linked_student["source"] == "canvas"
    removal = await client.delete(
        f"/api/courses/{imported.json()['id']}/students/{linked_student['id']}",
        headers=headers,
    )
    assert removal.status_code == 409
    assert removal.json()["error"]["code"] == "canvas_roster_managed"
    enrolment = await db_session.scalar(
        select(Enrolment).where(
            Enrolment.course_id == imported.json()["id"],
            Enrolment.user_id == existing_student.id,
        )
    )
    assert enrolment is not None
    assert available.json()[0]["imported"] is True
    assert available.json()[0]["omr_course_id"] == imported.json()["id"]
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "canvas_course_already_imported"


@pytest.mark.asyncio
async def test_import_rejects_a_course_not_returned_for_the_professor(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(return_value=[]),
    )

    response = await client.post("/api/canvas/courses/999/import", headers=headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "canvas_course_not_found"


@pytest.mark.asyncio
async def test_bulk_course_import_returns_per_course_results(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    canvas_call = AsyncMock(
        side_effect=[
            [
                {"id": 42, "name": "First Course"},
                {"id": 43, "name": "Second Course"},
            ],
            [canvas_student(1, "First Student", "one@example.com", "10000001")],
            [canvas_student(2, "Second Student", "two@example.com", "10000002")],
        ]
    )
    monkeypatch.setattr(canvas_course_service, "call_canvas", canvas_call)

    response = await client.post(
        "/api/canvas/courses/import",
        headers=headers,
        json={"course_ids": ["42", "43", "999"]},
    )

    assert response.status_code == 200, response.json()
    assert [result["status"] for result in response.json()["results"]] == [
        "imported",
        "imported",
        "failed",
    ]
    assert response.json()["results"][2]["message"] == "Canvas course not found."
    assert response.json()["results"][0]["roster_sync"]["added"] == 1
    assert response.json()["results"][0]["course"]["student_count"] == 1
    assert response.json()["results"][0]["course"]["academic_term"]["name"] == "Canvas"
    assert response.json()["results"][0]["course"]["academic_term"]["term_type"] == "custom"
    assert (
        response.json()["results"][0]["course"]["academic_term_id"]
        == response.json()["results"][1]["course"]["academic_term_id"]
    )
    assert canvas_call.await_count == 3


@pytest.mark.asyncio
async def test_bulk_course_import_stops_at_its_shared_deadline(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    calls = 0

    async def canvas_call(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [
                {"id": 42, "name": "First Course"},
                {"id": 43, "name": "Second Course"},
            ]
        await asyncio.Event().wait()

    monkeypatch.setattr(canvas_course_service, "call_canvas", canvas_call)
    monkeypatch.setattr(
        canvas_course_service.settings,
        "canvas_operation_timeout_seconds",
        0.01,
    )

    response = await client.post(
        "/api/canvas/courses/import",
        headers=headers,
        json={"course_ids": ["42", "43"]},
    )

    assert response.status_code == 200
    assert [result["status"] for result in response.json()["results"]] == [
        "failed",
        "failed",
    ]
    assert all(
        "time limit" in result["message"]
        for result in response.json()["results"]
    )


@pytest.mark.asyncio
async def test_canvas_sync_adopts_an_exact_matching_manual_roster_entry(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                [{"id": 42, "name": "Integration Test Course"}],
                [],
            ]
        ),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]
    manual = await client.post(
        f"/api/courses/{course_id}/students",
        headers=headers,
        json={
            "email": "manual@example.com",
            "first_name": "Manual",
            "last_name": "Student",
            "student_number": "10000005",
        },
    )
    monkeypatch.setattr(
        canvas_roster,
        "call_canvas",
        AsyncMock(
            return_value=[
                canvas_student(
                    "9007199254740993",
                    "Manual Student",
                    "manual@example.com",
                    "10000005",
                )
            ]
        ),
    )

    synced = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/sync",
        headers=headers,
    )
    roster = await client.get(f"/api/courses/{course_id}/students", headers=headers)

    assert manual.status_code == 201
    assert synced.status_code == 200, synced.json()
    assert synced.json()["added"] == 0
    assert synced.json()["updated"] == 1
    assert len(roster.json()) == 1
    assert roster.json()[0]["id"] == manual.json()["id"]
    assert roster.json()[0]["source"] == "canvas"
    saved = await db_session.get(CourseRosterEntry, uuid.UUID(manual.json()["id"]))
    assert saved.canvas_user_id == "9007199254740993"


@pytest.mark.asyncio
async def test_canvas_sync_does_not_merge_a_partial_identity_match(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                [{"id": 42, "name": "Integration Test Course"}],
                [],
            ]
        ),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]
    manual = await client.post(
        f"/api/courses/{course_id}/students",
        headers=headers,
        json={
            "email": "manual-conflict@example.com",
            "first_name": "Manual",
            "last_name": "Conflict",
            "student_number": "10000006",
        },
    )
    monkeypatch.setattr(
        canvas_roster,
        "call_canvas",
        AsyncMock(
            return_value=[
                canvas_student(
                    "12",
                    "Different Student",
                    "manual-conflict@example.com",
                    "10000007",
                )
            ]
        ),
    )

    synced = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/sync",
        headers=headers,
    )

    assert synced.status_code == 200
    assert synced.json()["skip_reasons"] == {"identity_conflict": 1}
    saved = await db_session.get(CourseRosterEntry, uuid.UUID(manual.json()["id"]))
    assert saved.source == "manual"
    assert saved.canvas_user_id is None


@pytest.mark.asyncio
async def test_canvas_roster_sync_reconciles_changes_without_deleting_history(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    removed_account = await create_user(
        email="two@example.com",
        role=UserRole.STUDENT,
        student_number="10000002",
    )
    canvas_courses = [{"id": 42, "name": "Integration Test Course"}]
    initial_roster = [
        canvas_student(1, "Test Student One", "one@example.com", "10000001"),
        canvas_student(2, "Test Student Two", "two@example.com", "10000002"),
    ]
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(side_effect=[canvas_courses, initial_roster]),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]

    updated_roster = [
        canvas_student(1, "Updated Student One", "one@example.com", "10000001"),
        canvas_student(3, "Test Student Three", "three@example.com", "10000003"),
        canvas_student(4, "Invalid Student", "not-an-email", "not-an-id"),
    ]
    monkeypatch.setattr(
        canvas_roster,
        "call_canvas",
        AsyncMock(return_value=updated_roster),
    )

    synced = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/sync",
        headers=headers,
    )
    roster_history = await client.get(
        f"/api/courses/{course_id}/students",
        headers=headers,
    )
    all_entries = list(
        (
            await db_session.execute(
                select(CourseRosterEntry).where(
                    CourseRosterEntry.course_id == course_id
                )
            )
        ).scalars()
    )

    assert synced.status_code == 200
    assert synced.json() | {"last_synced_at": None} == {
        "added": 1,
        "updated": 1,
        "removed": 1,
        "skipped": 1,
        "skip_reasons": {"invalid_email": 1},
        "active": 2,
        "last_synced_at": None,
    }
    assert {student["email"] for student in roster_history.json()} == {
        "one@example.com",
        "two@example.com",
        "three@example.com",
    }
    assert {
        student["email"]: student["active"]
        for student in roster_history.json()
    } == {
        "one@example.com": True,
        "two@example.com": False,
        "three@example.com": True,
    }
    removed = next(entry for entry in all_entries if entry.canvas_user_id == "2")
    assert removed.active is False
    assert await db_session.scalar(
        select(Enrolment).where(
            Enrolment.course_id == course_id,
            Enrolment.user_id == removed_account.id,
        )
    ) is None


@pytest.mark.asyncio
async def test_pending_canvas_invitations_are_retryable_and_idempotent(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    await create_user(
        email="linked@example.com",
        role=UserRole.STUDENT,
        student_number="10000001",
    )
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                [{"id": 42, "name": "Integration Test Course"}],
                [
                    canvas_student(1, "Linked Student", "linked@example.com", "10000001"),
                    canvas_student(2, "Pending Student", "pending@example.com", "10000002"),
                    canvas_student(3, "Retry Student", "retry@example.com", "10000003"),
                ],
            ]
        ),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]
    delivered: list[tuple[str, str]] = []

    async def deliver(email: str, **kwargs) -> None:
        delivered.append((email, kwargs["idempotency_token"]))
        if email == "retry@example.com":
            raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)
    first = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/invite-pending",
        headers=headers,
    )

    assert first.status_code == 200
    assert first.json() == {
        "sent": 1,
        "already_invited": 0,
        "linked": 1,
        "failed": 1,
        "pending": 1,
    }

    monkeypatch.setattr(
        course_invites,
        "send_course_invitation_email",
        AsyncMock(),
    )
    second = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/invite-pending",
        headers=headers,
    )
    third = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/invite-pending",
        headers=headers,
    )
    roster = await client.get(f"/api/courses/{course_id}/students", headers=headers)

    assert second.json() == {
        "sent": 1,
        "already_invited": 1,
        "linked": 1,
        "failed": 0,
        "pending": 0,
    }
    assert third.json() == {
        "sent": 0,
        "already_invited": 2,
        "linked": 1,
        "failed": 0,
        "pending": 0,
    }
    assert [email for email, _ in delivered] == [
        "pending@example.com",
        "retry@example.com",
    ]
    assert all(
        student["invited_at"] is not None
        for student in roster.json()
        if student["account_status"] == "pending"
    )

    monkeypatch.setattr(
        canvas_roster,
        "call_canvas",
        AsyncMock(return_value=[
            canvas_student(1, "Linked Student", "linked@example.com", "10000001"),
            canvas_student(
                2,
                "Pending Student",
                "new.pending@example.com",
                "10000002",
            ),
            canvas_student(3, "Retry Student", "retry@example.com", "10000003"),
        ]),
    )
    await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/sync",
        headers=headers,
    )
    changed_delivery = AsyncMock()
    monkeypatch.setattr(
        course_invites,
        "send_course_invitation_email",
        changed_delivery,
    )

    changed_invite = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/invite-pending",
        headers=headers,
    )

    assert changed_invite.json()["sent"] == 1
    changed_delivery.assert_awaited_once()
    changed_call = changed_delivery.await_args
    assert changed_call.args[0] == "new.pending@example.com"
    old_token = next(token for email, token in delivered if email == "pending@example.com")
    new_token = changed_call.kwargs["idempotency_token"]
    assert new_token != old_token
    assert new_token.endswith(":new.pending@example.com")


@pytest.mark.asyncio
async def test_can_invite_one_pending_canvas_student(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(
        create_user, login_user, db_session
    )
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                [{"id": 42, "name": "Integration Test Course"}],
                [
                    canvas_student(
                        2,
                        "Pending Student",
                        "pending@example.com",
                        "10000002",
                    )
                ],
            ]
        ),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]
    roster = await client.get(f"/api/courses/{course_id}/students", headers=headers)
    roster_entry_id = roster.json()[0]["id"]
    deliver = AsyncMock()
    monkeypatch.setattr(course_invites, "send_course_invitation_email", deliver)

    response = await client.post(
        f"/api/canvas/imported-courses/{course_id}/roster/{roster_entry_id}/invite",
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {
        "sent": 1,
        "already_invited": 0,
        "linked": 0,
        "failed": 0,
        "pending": 0,
    }
    deliver.assert_awaited_once()


@pytest.mark.asyncio
async def test_professor_links_one_canvas_assignment_to_an_exam(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    large_assignment_id = "9007199254740993"
    headers = await connected_professor_headers(create_user, login_user, db_session)
    monkeypatch.setattr(
        canvas_course_service,
        "call_canvas",
        AsyncMock(
            side_effect=[
                [{"id": 42, "name": "Integration Test Course"}],
                [],
            ]
        ),
    )
    imported = await client.post("/api/canvas/courses/42/import", headers=headers)
    course_id = imported.json()["id"]
    professor = await db_session.scalar(
        select(User).where(User.email == "professor@example.com")
    )
    template = ExamTemplate(
        name="Template",
        created_by=professor.id,
        question_config={"1": {"choices": ["A", "B"]}},
        sections=[],
        total_questions=1,
        n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()
    exam = Exam(
        name="Midterm",
        start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 1, 2, tzinfo=timezone.utc),
        role="student",
        course_id=course_id,
        created_by=professor.id,
        exam_template_id=template.id,
    )
    db_session.add(exam)
    await db_session.commit()
    assignments = [
        {
            "id": 10,
            "name": "Practice Quiz",
            "due_at": None,
            "points_possible": 10,
            "published": True,
            "html_url": "http://localhost:6700/courses/42/assignments/10",
        },
        {
            "id": large_assignment_id,
            "name": "Midterm Exam",
            "due_at": "2026-10-01T18:00:00Z",
            "points_possible": 100,
            "published": True,
            "html_url": "http://localhost:6700/courses/42/assignments/11",
        },
    ]
    monkeypatch.setattr(
        canvas_assignments,
        "call_canvas",
        AsyncMock(return_value=assignments),
    )

    available = await client.get(
        f"/api/canvas/imported-courses/{course_id}/assignments",
        headers=headers,
    )
    saved = await client.put(
        f"/api/canvas/exams/{exam.id}/canvas-assignment",
        json={"assignment_id": large_assignment_id},
        headers=headers,
    )
    refreshed = await client.get(
        f"/api/canvas/imported-courses/{course_id}/assignments",
        headers=headers,
    )
    invalid = await client.put(
        f"/api/canvas/exams/{exam.id}/canvas-assignment",
        json={"assignment_id": "999"},
        headers=headers,
    )

    assert available.status_code == 200
    assert all(assignment["linked_exam_id"] is None for assignment in available.json())
    assert saved.status_code == 200, saved.json()
    assert saved.json()["assignment_id"] == large_assignment_id
    assert next(item for item in refreshed.json() if item["id"] == large_assignment_id)["linked_exam_id"] == str(exam.id)
    assert next(item for item in refreshed.json() if item["id"] == "10")["linked_exam_id"] is None
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "canvas_assignment_not_found"
    links = list(
        (
            await db_session.execute(
                select(CanvasAssignmentLink).where(
                    CanvasAssignmentLink.course_id == course_id
                )
            )
        ).scalars()
    )
    assert [link.canvas_assignment_id for link in links] == [large_assignment_id]

    created = await client.post(
        "/api/exams",
        json={
            "name": "Client-supplied name",
            "description": None,
            "start_time": "2026-07-02T09:00:00Z",
            "end_time": "2026-07-02T10:00:00Z",
            "role": "student",
            "course_id": course_id,
            "exam_template_id": str(template.id),
            "canvas_assignment_id": "10",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.json()
    assert created.json()["name"] == "Practice Quiz"
    assert created.json()["canvas_assignment_id"] == "10"
    assert created.json()["canvas_assignment_name"] == "Practice Quiz"

    async def commit_during_failed_validation(db, _user_id, _operation):
        await db.commit()
        return []

    monkeypatch.setattr(
        canvas_assignments,
        "call_canvas",
        commit_during_failed_validation,
    )
    rejected = await client.post(
        "/api/exams",
        json={
            "name": "Ghost Exam",
            "description": None,
            "start_time": "2026-07-03T09:00:00Z",
            "end_time": "2026-07-03T10:00:00Z",
            "role": "student",
            "course_id": course_id,
            "exam_template_id": str(template.id),
            "canvas_assignment_id": "999",
        },
        headers=headers,
    )

    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "canvas_assignment_not_found"
    assert await db_session.scalar(
        select(Exam).where(Exam.name == "Ghost Exam")
    ) is None

    cleared = await client.delete(
        f"/api/canvas/exams/{exam.id}/canvas-assignment",
        headers=headers,
    )
    assert cleared.json()["assignment_id"] is None


@pytest.mark.asyncio
async def test_released_exam_grades_are_previewed_and_sent_to_canvas(
    client,
    create_user,
    login_user,
    db_session,
    monkeypatch,
):
    headers = await connected_professor_headers(create_user, login_user, db_session)
    professor = await db_session.scalar(
        select(User).where(User.email == "professor@example.com")
    )
    connection = await db_session.scalar(
        select(CanvasConnection).where(CanvasConnection.user_id == professor.id)
    )
    student = await create_user(
        email="canvas.student@example.com",
        role=UserRole.STUDENT,
        student_number="10000009",
    )
    course = Course(
        name="CANVAS 101 - Integration Test Course",
        academic_term_id=UBC_WINTER_SESSION_1_TERM_ID,
        academic_year_start=2026,
        created_by=professor.id,
        source="canvas",
    )
    db_session.add(course)
    await db_session.flush()
    db_session.add(
        CanvasCourseLink(
            course_id=course.id,
            canvas_connection_id=connection.id,
            owner_user_id=professor.id,
            canvas_course_id="42",
            last_synced_at=datetime.now(timezone.utc),
        )
    )
    db_session.add(
        CourseRosterEntry(
            course_id=course.id,
            user_id=student.id,
            email=student.email,
            first_name=student.first_name,
            last_name=student.last_name,
            student_number=student.student_number,
            source="canvas",
            canvas_user_id="9",
        )
    )
    template = ExamTemplate(
        name="Template",
        created_by=professor.id,
        question_config={"1": {"choices": ["A", "B"]}},
        sections=[],
        total_questions=1,
        n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()
    exam = Exam(
        name="Midterm",
        start_time=datetime(2026, 7, 1, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 1, 2, tzinfo=timezone.utc),
        role="student",
        course_id=course.id,
        created_by=professor.id,
        exam_template_id=template.id,
    )
    db_session.add(exam)
    await db_session.flush()
    scan = Scan(
        exam_id=exam.id,
        exam_template_id=template.id,
        uploader_user_id=professor.id,
        path=f"scans/{uuid.uuid4()}.pdf",
        status="completed",
    )
    answer_key = ExamAnswerKey(
        exam_id=exam.id,
        exam_template_id=template.id,
        answer_key={"1": {"correct_choices": ["A"]}},
    )
    omr_template = OMRTemplate(name="OMR", page_count=1)
    db_session.add_all([scan, answer_key, omr_template])
    await db_session.flush()
    marking = OMRMarking(
        scan_id=scan.id,
        omr_template_id=omr_template.id,
        status="completed",
    )
    assignment = CanvasAssignmentLink(
        course_id=course.id,
        canvas_assignment_id="7",
        name="Midterm",
        points_possible=50,
        published=True,
    )
    db_session.add_all([marking, assignment])
    await db_session.flush()
    db_session.add(
        CanvasGradeRelease(
            exam_id=exam.id,
            canvas_assignment_link_id=assignment.id,
        )
    )
    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results={},
        total_score=30,
        max_score=40,
        template_version=1,
        student_id=student.id,
        status="graded",
    )
    db_session.add(grade)
    await db_session.commit()

    blocked = await client.post(
        f"/api/canvas/exams/{exam.id}/grade-release",
        headers=headers,
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "exam_not_released"

    exam.released = True
    await db_session.commit()
    canvas_client = AsyncMock()
    canvas_client.update_grade.return_value = {"score": 37.5}

    async def call_canvas(_db, _user_id, operation):
        return await operation(canvas_client, "token")

    monkeypatch.setattr(canvas_grades, "call_canvas", call_canvas)
    monkeypatch.setattr(
        canvas_grades.settings,
        "frontend_origin",
        "https://omr.example.edu",
    )
    monkeypatch.setattr(
        canvas_assignments,
        "call_canvas",
        AsyncMock(return_value=[{
            "id": 7,
            "name": "Midterm",
            "due_at": None,
            "points_possible": 50,
            "published": True,
            "html_url": None,
        }]),
    )
    preview = await client.get(
        f"/api/canvas/exams/{exam.id}/grade-release", headers=headers
    )
    released = await client.post(
        f"/api/canvas/exams/{exam.id}/grade-release",
        headers=headers,
    )

    assert preview.json()["eligible_count"] == 1
    assert released.status_code == 200, released.json()
    assert released.json()["last_sent_count"] == 1
    assert released.json()["last_attempt_status"] == "completed"
    assert released.json()["last_attempted_at"] is not None
    canvas_client.update_grade.assert_awaited_once()
    update_call = canvas_client.update_grade.await_args
    assert update_call.args == ("token", "42", "7", "9", "75%")
    comment = update_call.kwargs["comment"]
    assert comment.startswith("Your marked exam result is ready in OMR.<br>")
    assert ">View your marked exam scan</a>" in comment
    assert comment.endswith("This student-specific link expires automatically.")
    result_url = comment.split('href="', 1)[1].split('"', 1)[0]
    assert comment.count(result_url) == 1
    parsed_result_url = urlparse(result_url)
    assert parsed_result_url.scheme == "https"
    assert parsed_result_url.netloc == "omr.example.edu"
    assert parsed_result_url.path == "/canvas/results"
    assert parsed_result_url.query == ""
    result_token = parse_qs(parsed_result_url.fragment)["token"][0]
    result_claims = decode_canvas_student_access_token(result_token)
    assert result_claims["sub"] == str(student.id)
    assert result_claims["exam_grade_id"] == str(grade.id)
    assert result_claims["canvas_user_id"] == "9"
    saved = await db_session.scalar(
        select(CanvasGradeRelease).where(CanvasGradeRelease.exam_id == exam.id)
    )
    assert saved.canvas_assignment_link_id == assignment.id
    attempt = await db_session.scalar(
        select(CanvasGradeReleaseAttempt).where(
            CanvasGradeReleaseAttempt.canvas_grade_release_id == saved.id
        )
    )
    recipient = await db_session.scalar(
        select(CanvasGradeReleaseRecipient).where(
            CanvasGradeReleaseRecipient.attempt_id == attempt.id
        )
    )
    assert attempt.status == "completed"
    assert attempt.sent_count == 1
    assert recipient.canvas_user_id == "9"
    assert recipient.percentage == 75
    assert recipient.status == "sent"

    canvas_client.update_grade.reset_mock()
    canvas_client.update_grade.side_effect = CanvasRequestError(
        "Canvas unavailable", status_code=503
    )
    failed_release = await client.post(
        f"/api/canvas/exams/{exam.id}/grade-release",
        headers=headers,
    )
    failed_status = await client.get(
        f"/api/canvas/exams/{exam.id}/grade-release",
        headers=headers,
    )
    failed_attempt = await db_session.scalar(
        select(CanvasGradeReleaseAttempt).where(
            CanvasGradeReleaseAttempt.canvas_grade_release_id == saved.id,
            CanvasGradeReleaseAttempt.status == "failed",
        )
    )
    failed_recipient = await db_session.scalar(
        select(CanvasGradeReleaseRecipient).where(
            CanvasGradeReleaseRecipient.attempt_id == failed_attempt.id
        )
    )

    assert failed_release.status_code == 502
    assert failed_release.json()["error"]["code"] == "canvas_grade_release_failed"
    assert failed_release.json()["error"]["details"] == {
        "sent": 0,
        "failed": 1,
        "skipped": 0,
    }
    assert failed_status.json()["last_attempt_status"] == "failed"
    assert failed_status.json()["last_failed_count"] == 1
    assert failed_attempt.status == "failed"
    assert failed_recipient.status == "failed"
    assert failed_recipient.error_code == "canvas_http_503"

    running_attempt = CanvasGradeReleaseAttempt(
        canvas_grade_release_id=saved.id,
        requested_by=professor.id,
        started_at=canvas_grades.utc_now(),
    )
    db_session.add(running_attempt)
    await db_session.commit()

    running_status = await client.get(
        f"/api/canvas/exams/{exam.id}/grade-release",
        headers=headers,
    )
    assert running_status.status_code == 200
    assert running_status.json()["last_attempt_status"] == "running"
    assert running_status.json()["last_attempted_at"] is not None
