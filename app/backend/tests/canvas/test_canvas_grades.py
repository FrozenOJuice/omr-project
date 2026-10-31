import asyncio
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse
import uuid

import pytest

from core.tokens import decode_canvas_student_access_token
from errors.exceptions import ServiceUnavailableError
from integrations.canvas_client import CanvasRequestError
from services import canvas_grades


def release_records(recipient_ids: list[str]):
    release = SimpleNamespace(
        id=uuid.uuid4(),
        exam_id=uuid.uuid4(),
        canvas_assignment_link_id=uuid.uuid4(),
        last_sent_count=0,
        last_skipped_count=0,
        last_failed_count=0,
        first_released_at=None,
        last_released_at=None,
    )
    attempt = SimpleNamespace(
        id=uuid.uuid4(),
        canvas_grade_release_id=release.id,
        status="running",
        skipped_count=0,
        started_at=canvas_grades.utc_now(),
        completed_at=None,
    )
    recipients = [
        SimpleNamespace(
            attempt_id=attempt.id,
            canvas_user_id=canvas_user_id,
            percentage=75,
            status="pending",
            error_code=None,
        )
        for canvas_user_id in recipient_ids
    ]
    assignment = SimpleNamespace(
        id=release.canvas_assignment_link_id,
        course_id=uuid.uuid4(),
        canvas_assignment_id="7",
        name="Midterm",
        published=True,
    )
    candidates = [
        canvas_grades.GradeCandidate(
            canvas_user_id=recipient.canvas_user_id,
            student_id=uuid.uuid4(),
            exam_grade_id=uuid.uuid4(),
            percentage=recipient.percentage,
        )
        for recipient in recipients
    ]
    return release, attempt, recipients, candidates, assignment


@pytest.mark.asyncio
async def test_grade_candidates_only_use_active_canvas_roster_entries(monkeypatch):
    student_id = uuid.uuid4()
    exam = SimpleNamespace(id=uuid.uuid4(), course_id=uuid.uuid4())
    grade = SimpleNamespace(
        status="graded",
        student_id=student_id,
        total_score=8,
        max_score=10,
    )
    inactive_entry = SimpleNamespace(
        user_id=student_id,
        canvas_user_id="42",
        active=False,
    )
    list_active = AsyncMock(return_value=[])
    list_all = AsyncMock(return_value=[inactive_entry])
    monkeypatch.setattr(
        canvas_grades.exam_grades,
        "list_grades_by_exam",
        AsyncMock(return_value=[grade]),
    )
    monkeypatch.setattr(
        canvas_grades.course_roster_entries,
        "list_active_by_course",
        list_active,
    )
    monkeypatch.setattr(
        canvas_grades.course_roster_entries,
        "list_by_course",
        list_all,
    )

    candidates, skipped = await canvas_grades._grade_candidates(AsyncMock(), exam)

    assert candidates == []
    assert skipped == {"not_linked_to_canvas": 1}
    list_active.assert_awaited_once()
    list_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_grade_candidates_keep_student_and_grade_scope_for_result_link(
    monkeypatch,
):
    student_id = uuid.uuid4()
    grade_id = uuid.uuid4()
    exam = SimpleNamespace(id=uuid.uuid4(), course_id=uuid.uuid4())
    grade = SimpleNamespace(
        id=grade_id,
        status="graded",
        student_id=student_id,
        total_score=8,
        max_score=10,
    )
    active_entry = SimpleNamespace(
        user_id=student_id,
        canvas_user_id="42",
        active=True,
    )
    monkeypatch.setattr(
        canvas_grades.exam_grades,
        "list_grades_by_exam",
        AsyncMock(return_value=[grade]),
    )
    monkeypatch.setattr(
        canvas_grades.course_roster_entries,
        "list_active_by_course",
        AsyncMock(return_value=[active_entry]),
    )

    candidates, skipped = await canvas_grades._grade_candidates(AsyncMock(), exam)

    assert candidates == [
        canvas_grades.GradeCandidate(
            canvas_user_id="42",
            student_id=student_id,
            exam_grade_id=grade_id,
            percentage=80,
        )
    ]
    assert skipped == {}


def test_student_result_comment_uses_fragment_and_scoped_token(monkeypatch):
    monkeypatch.setattr(
        canvas_grades.settings,
        "jwt_access_secret",
        "canvas-result-test-secret-with-at-least-32-bytes",
    )
    candidate = canvas_grades.GradeCandidate(
        canvas_user_id="9007199254740993",
        student_id=uuid.uuid4(),
        exam_grade_id=uuid.uuid4(),
        percentage=80,
    )

    comment = canvas_grades._student_result_comment(
        "https://omr.example.edu", candidate
    )

    assert comment.startswith("Your marked exam result is ready in OMR.<br>")
    assert ">View your marked exam scan</a>" in comment
    assert comment.endswith("This student-specific link expires automatically.")
    result_url = comment.split('href="', 1)[1].split('"', 1)[0]
    assert comment.count(result_url) == 1
    parsed = urlparse(result_url)
    assert parsed.path == "/canvas/results"
    assert parsed.query == ""
    payload = decode_canvas_student_access_token(parse_qs(parsed.fragment)["token"][0])
    assert payload["sub"] == str(candidate.student_id)
    assert payload["exam_grade_id"] == str(candidate.exam_grade_id)
    assert payload["canvas_user_id"] == candidate.canvas_user_id


@pytest.mark.parametrize(
    "origin",
    [
        None,
        "ftp://omr.example.edu",
        "https://user:password@omr.example.edu",
        "https://omr.example.edu/path",
        "https://omr.example.edu?tenant=1",
        "https://omr.example.edu#fragment",
    ],
)
def test_student_result_base_url_rejects_unsafe_origins(monkeypatch, origin):
    monkeypatch.setattr(canvas_grades.settings, "frontend_origin", origin)

    with pytest.raises(ServiceUnavailableError) as exc_info:
        canvas_grades._student_result_base_url()

    assert exc_info.value.code == "canvas_student_result_access_not_configured"


@pytest.mark.asyncio
async def test_grade_release_preserves_successes_and_recipient_failures(monkeypatch):
    release, attempt, recipients, candidates, assignment = release_records(
        ["1", "2", "3"]
    )
    client = AsyncMock()

    async def update_grade(
        _token, _course, _assignment, user_id, _grade, *, comment
    ):
        assert "/canvas/results#token=" in comment
        if user_id == "2":
            raise CanvasRequestError("forbidden", 403)
        if user_id == "3":
            raise CanvasRequestError("rate limited", 429)
        return {"ok": True}

    client.update_grade.side_effect = update_grade

    async def call_canvas(_db, _user_id, operation):
        await operation(client, "token")

    monkeypatch.setattr(canvas_grades, "call_canvas", call_canvas)
    db = AsyncMock()

    await canvas_grades._publish_attempt(
        db,
        uuid.uuid4(),
        "42",
        assignment,
        attempt,
        recipients,
        candidates,
        "https://omr.example.edu",
        release,
    )

    assert [recipient.status for recipient in recipients] == [
        "sent",
        "failed",
        "failed",
    ]
    assert recipients[1].error_code == "canvas_http_403"
    assert recipients[2].error_code == "canvas_http_429"
    assert attempt.status == "partial"
    assert attempt.sent_count == 1
    assert attempt.failed_count == 2


@pytest.mark.asyncio
async def test_grade_release_retries_only_unauthorized_recipients(monkeypatch):
    release, attempt, recipients, candidates, assignment = release_records(
        ["1", "2", "3"]
    )
    client = AsyncMock()
    calls: list[tuple[str, str]] = []

    async def update_grade(
        token, _course, _assignment, user_id, _grade, *, comment
    ):
        assert "/canvas/results#token=" in comment
        calls.append((token, user_id))
        if user_id == "2" and token == "expired-token":
            raise CanvasRequestError("expired", 401)
        if user_id == "3":
            raise CanvasRequestError("forbidden", 403)
        return {"ok": True}

    client.update_grade.side_effect = update_grade

    async def call_canvas(_db, _user_id, operation):
        with pytest.raises(CanvasRequestError):
            await operation(client, "expired-token")
        await operation(client, "refreshed-token")

    monkeypatch.setattr(canvas_grades, "call_canvas", call_canvas)

    await canvas_grades._publish_attempt(
        AsyncMock(),
        uuid.uuid4(),
        "42",
        assignment,
        attempt,
        recipients,
        candidates,
        "https://omr.example.edu",
        release,
    )

    assert calls == [
        ("expired-token", "1"),
        ("expired-token", "2"),
        ("expired-token", "3"),
        ("refreshed-token", "2"),
    ]
    assert [recipient.status for recipient in recipients] == [
        "sent",
        "sent",
        "failed",
    ]
    assert recipients[2].error_code == "canvas_http_403"
    assert attempt.status == "partial"
    assert attempt.sent_count == 2
    assert attempt.failed_count == 1


@pytest.mark.asyncio
async def test_cancelled_grade_release_is_finalized(monkeypatch):
    release, attempt, recipients, candidates, assignment = release_records(["1"])
    monkeypatch.setattr(
        canvas_grades,
        "call_canvas",
        AsyncMock(side_effect=asyncio.CancelledError()),
    )
    db = AsyncMock()

    with pytest.raises(asyncio.CancelledError):
        await canvas_grades._publish_attempt(
            db,
            uuid.uuid4(),
            "42",
            assignment,
            attempt,
            recipients,
            candidates,
            "https://omr.example.edu",
            release,
        )

    assert attempt.status == "failed"
    assert recipients[0].status == "failed"
    assert recipients[0].error_code == "release_interrupted"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stale_grade_release_is_failed_before_retry(monkeypatch):
    release, attempt, recipients, _, _ = release_records(["1", "2"])
    attempt.started_at = canvas_grades.utc_now() - timedelta(
        seconds=(
            canvas_grades.settings.canvas_operation_timeout_seconds
            + canvas_grades.GRADE_RELEASE_LEASE_GRACE_SECONDS
            + 1
        )
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_running_attempt",
        AsyncMock(return_value=attempt),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "list_recipients",
        AsyncMock(return_value=recipients),
    )
    db = AsyncMock()

    await canvas_grades._require_idle_release(db, release)

    assert attempt.status == "failed"
    assert all(recipient.status == "failed" for recipient in recipients)
    assert all(recipient.error_code == "release_stale" for recipient in recipients)
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_running_grade_release_can_be_returned(monkeypatch):
    release, attempt, _, _, assignment = release_records([])
    exam = SimpleNamespace(id=release.exam_id, course_id=assignment.course_id)
    monkeypatch.setattr(
        canvas_grades, "_grade_candidates", AsyncMock(return_value=([], {}))
    )
    monkeypatch.setattr(
        canvas_grades, "_release_assignment", AsyncMock(return_value=assignment)
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_latest_attempt",
        AsyncMock(return_value=attempt),
    )

    response = await canvas_grades._response(AsyncMock(), exam, release)

    assert response.last_attempt_status == "running"
    assert response.last_attempted_at == attempt.started_at
