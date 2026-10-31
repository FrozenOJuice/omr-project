from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from errors.exceptions import ConflictError
from models.canvas_assignment_link import CanvasAssignmentLink
from services import canvas_assignments, canvas_grades


class NestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


def integrity_error() -> IntegrityError:
    return IntegrityError("statement", {}, Exception("unique constraint"))


@pytest.mark.asyncio
async def test_assignment_resolution_reloads_a_concurrently_created_link(monkeypatch):
    course_id = uuid.uuid4()
    existing = CanvasAssignmentLink(
        id=uuid.uuid4(),
        course_id=course_id,
        canvas_assignment_id="7",
        name="Old name",
        published=False,
    )
    db = AsyncMock()
    db.add = Mock()
    db.begin_nested = Mock(return_value=NestedTransaction())
    db.flush.side_effect = [integrity_error(), None]
    monkeypatch.setattr(
        canvas_assignments,
        "connected_course",
        AsyncMock(return_value=(SimpleNamespace(), SimpleNamespace(), "42")),
    )
    monkeypatch.setattr(
        canvas_assignments,
        "call_canvas",
        AsyncMock(
            return_value=[
                {
                    "id": "7",
                    "name": "Current name",
                    "due_at": None,
                    "points_possible": 20,
                    "published": True,
                    "html_url": None,
                }
            ]
        ),
    )
    get_link = AsyncMock(side_effect=[None, existing])
    monkeypatch.setattr(
        canvas_assignments.canvas_assignment_links,
        "get_by_canvas_id",
        get_link,
    )

    result = await canvas_assignments.resolve(
        db, SimpleNamespace(id=uuid.uuid4()), course_id, "7"
    )

    assert result is existing
    assert result.name == "Current name"
    assert result.points_possible == 20
    assert result.published is True
    assert get_link.await_count == 2


@pytest.mark.asyncio
async def test_competing_exam_assignment_link_returns_a_conflict(monkeypatch):
    course_id = uuid.uuid4()
    exam = SimpleNamespace(id=uuid.uuid4(), course_id=course_id)
    course = SimpleNamespace(id=course_id, archived_at=None)
    assignment = CanvasAssignmentLink(
        id=uuid.uuid4(),
        course_id=course_id,
        canvas_assignment_id="7",
        name="Midterm",
        points_possible=20,
        published=True,
    )
    db = AsyncMock()
    db.add = Mock()
    db.flush.side_effect = integrity_error()
    monkeypatch.setattr(
        canvas_grades,
        "_manageable_exam",
        AsyncMock(return_value=(exam, course)),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_by_assignment",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_by_exam",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_running_attempt",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        canvas_grades,
        "_release_assignment",
        AsyncMock(return_value=None),
    )

    with pytest.raises(ConflictError) as error:
        await canvas_grades.set_assignment(
            db,
            SimpleNamespace(id=uuid.uuid4()),
            exam.id,
            "7",
            resolved_assignment=assignment,
        )

    assert error.value.code == "canvas_assignment_in_use"
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_assignment_cannot_change_while_grade_release_is_running(monkeypatch):
    course_id = uuid.uuid4()
    exam = SimpleNamespace(id=uuid.uuid4(), course_id=course_id)
    course = SimpleNamespace(id=course_id, archived_at=None)
    assignment = CanvasAssignmentLink(
        id=uuid.uuid4(),
        course_id=course_id,
        canvas_assignment_id="7",
        name="Midterm",
        points_possible=20,
        published=True,
    )
    release = SimpleNamespace(
        id=uuid.uuid4(),
        exam_id=exam.id,
        canvas_assignment_link_id=assignment.id,
        first_released_at=None,
    )
    db = AsyncMock()
    monkeypatch.setattr(
        canvas_grades,
        "_manageable_exam",
        AsyncMock(return_value=(exam, course)),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_by_assignment",
        AsyncMock(return_value=release),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_by_exam",
        AsyncMock(return_value=release),
    )
    monkeypatch.setattr(
        canvas_grades.canvas_grade_releases,
        "get_running_attempt",
        AsyncMock(
            return_value=SimpleNamespace(
                id=uuid.uuid4(), started_at=canvas_grades.utc_now()
            )
        ),
    )

    with pytest.raises(ConflictError) as error:
        await canvas_grades.set_assignment(
            db,
            SimpleNamespace(id=uuid.uuid4()),
            exam.id,
            "7",
            resolved_assignment=assignment,
        )

    assert error.value.code == "canvas_grade_release_in_progress"
    db.flush.assert_not_awaited()
