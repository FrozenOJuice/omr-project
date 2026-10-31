import uuid
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import BadRequestError, ConflictError
from integrations.canvas_client import normalize_canvas_id
from models.canvas_assignment_link import CanvasAssignmentLink
from models.user import User
from repositories import canvas_assignment_links, canvas_grade_releases
from schemas.canvas_schema import CanvasAssignmentResponse
from services.canvas_access import connected_course
from services.canvas_connection import call_canvas


async def list_available(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
) -> list[CanvasAssignmentResponse]:
    _, _, canvas_course_id = await connected_course(db, user, course_id)
    assignments = _parse_assignments(
        await call_canvas(
            db,
            user.id,
            lambda client, token: client.get_assignments(token, canvas_course_id),
        )
    )
    saved = {
        link.canvas_assignment_id: link
        for link in await canvas_assignment_links.list_by_course(db, course_id)
    }
    releases = await canvas_grade_releases.list_by_assignments(
        db, (link.id for link in saved.values())
    )
    linked_exams = {
        release.canvas_assignment_link_id: release.exam_id for release in releases
    }
    available_ids = {assignment.id for assignment in assignments}
    for assignment in assignments:
        link = saved.get(assignment.id)
        assignment.linked_exam_id = linked_exams.get(link.id) if link else None
    assignments.extend(
        _saved_assignment(
            link,
            linked_exam_id=linked_exams.get(link.id),
            available=False,
        )
        for assignment_id, link in saved.items()
        if assignment_id not in available_ids
    )
    return assignments


async def resolve(
    db: AsyncSession,
    user: User,
    course_id: uuid.UUID,
    assignment_id: str,
) -> CanvasAssignmentLink:
    _, _, canvas_course_id = await connected_course(db, user, course_id)
    available = {
        assignment.id: assignment
        for assignment in _parse_assignments(
            await call_canvas(
                db,
                user.id,
                lambda client, token: client.get_assignments(
                    token, canvas_course_id
                ),
            )
        )
    }
    assignment = available.get(assignment_id)
    if assignment is None:
        raise BadRequestError(
            "The Canvas assignment is no longer available",
            code="canvas_assignment_not_found",
        )
    link = await canvas_assignment_links.get_by_canvas_id(db, course_id, assignment_id)
    if link is None:
        try:
            async with db.begin_nested():
                link = CanvasAssignmentLink(
                    course_id=course_id,
                    canvas_assignment_id=assignment_id,
                    name=assignment.name,
                    due_at=assignment.due_at,
                    points_possible=assignment.points_possible,
                    published=assignment.published,
                    html_url=assignment.html_url,
                )
                db.add(link)
                await db.flush()
        except IntegrityError:
            link = await canvas_assignment_links.get_by_canvas_id(
                db, course_id, assignment_id
            )
            if link is None:
                raise ConflictError(
                    "The Canvas assignment link changed while it was being saved",
                    code="canvas_assignment_link_conflict",
                )
    link.name = assignment.name
    link.due_at = assignment.due_at
    link.points_possible = assignment.points_possible
    link.published = assignment.published
    link.html_url = assignment.html_url
    await db.flush()
    return link


def _parse_assignments(items: Any) -> list[CanvasAssignmentResponse]:
    assignments: dict[str, CanvasAssignmentResponse] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        assignment_id = normalize_canvas_id(item.get("id"))
        if assignment_id is None:
            continue
        assignments[assignment_id] = CanvasAssignmentResponse(
            id=assignment_id,
            name=str(item.get("name") or assignment_id),
            due_at=item.get("due_at"),
            points_possible=_optional_number(item.get("points_possible")),
            published=bool(item.get("published")),
            html_url=_optional_string(item.get("html_url")),
        )
    return sorted(
        assignments.values(),
        key=lambda assignment: (
            assignment.due_at is None,
            assignment.due_at,
            assignment.name.casefold(),
        ),
    )


def _saved_assignment(
    link: CanvasAssignmentLink,
    *,
    linked_exam_id: uuid.UUID | None = None,
    available: bool = True,
) -> CanvasAssignmentResponse:
    return CanvasAssignmentResponse(
        id=link.canvas_assignment_id,
        name=link.name,
        due_at=link.due_at,
        points_possible=link.points_possible,
        published=link.published,
        html_url=link.html_url,
        linked_exam_id=linked_exam_id,
        available=available,
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
