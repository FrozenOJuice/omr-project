import asyncio
from datetime import datetime
import logging
from typing import Any
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from errors.exceptions import AppError, ConflictError, NotFoundError
from integrations.canvas_client import normalize_canvas_id
from models.academic_term import AcademicTermYearFormat
from models.user import User
from repositories import canvas_course_links, course_roster_entries, courses
from schemas.canvas_schema import CanvasCourseResponse, CanvasRosterSyncResponse
from schemas.course_schema import (
    CanvasCourseImportResponse,
    CanvasCourseImportResult,
    CourseResponse,
)
from services.canvas_connection import call_canvas, get_connection, utc_now
from services.canvas_roster import parse_students_with_skips, reconcile_roster
from services import academic_terms as academic_term_service

logger = logging.getLogger(__name__)


async def list_courses(
    db: AsyncSession, user_id: uuid.UUID
) -> list[CanvasCourseResponse]:
    raw_courses = await call_canvas(
        db, user_id, lambda client, token: client.get_courses(token)
    )
    canvas_courses = [
        course for item in raw_courses if (course := _parse_course(item))
    ]
    links = await canvas_course_links.list_by_canvas_courses(
        db, user_id, [course.id for course in canvas_courses]
    )
    links_by_id = {link.canvas_course_id: link for link in links}
    for course in canvas_courses:
        if link := links_by_id.get(course.id):
            course.imported = True
            course.omr_course_id = link.course_id
    return sorted(canvas_courses, key=lambda course: course.name.casefold())


async def import_course(
    db: AsyncSession,
    user: User,
    canvas_course_id: str,
) -> CourseResponse:
    user_id = user.id
    raw_courses = await _available_courses(db, user_id)
    raw_course = raw_courses.get(canvas_course_id)
    canvas_course = _parse_course(raw_course) if raw_course else None
    if canvas_course is None:
        raise NotFoundError("Canvas course not found", code="canvas_course_not_found")
    if await canvas_course_links.get_by_canvas_course(
        db, user_id, canvas_course_id
    ):
        raise ConflictError(
            "This Canvas course has already been imported",
            code="canvas_course_already_imported",
        )

    connection = await get_connection(db, user_id)
    if connection is None or connection.access_token_encrypted is None:
        raise ConflictError(
            "Connect Canvas before using this feature",
            code="canvas_not_connected",
        )
    course, _ = await _import_resolved_course(
        db,
        user,
        connection.id,
        canvas_course,
        raw_course,
    )
    return course


async def import_courses(
    db: AsyncSession,
    user: User,
    canvas_course_ids: list[str],
) -> CanvasCourseImportResponse:
    user_id = user.id
    connection = await get_connection(db, user_id)
    if connection is None or connection.access_token_encrypted is None:
        raise ConflictError(
            "Connect Canvas before using this feature",
            code="canvas_not_connected",
        )

    requested_ids = list(dict.fromkeys(canvas_course_ids))
    deadline = (
        asyncio.get_running_loop().time()
        + settings.canvas_operation_timeout_seconds
    )
    raw_courses = await _available_courses(db, user_id)
    existing_links = {
        link.canvas_course_id: link
        for link in await canvas_course_links.list_by_canvas_courses(
            db, user_id, requested_ids
        )
    }
    results: list[CanvasCourseImportResult] = []
    connection_id = connection.id

    for index, canvas_course_id in enumerate(requested_ids):
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            results.extend(
                _timed_out_import(course_id)
                for course_id in requested_ids[index:]
            )
            break
        if link := existing_links.get(canvas_course_id):
            results.append(
                CanvasCourseImportResult(
                    canvas_course_id=canvas_course_id,
                    status="already_imported",
                    course=await _course_response(db, link.course_id),
                    message="This Canvas course was already imported.",
                )
            )
            continue

        raw_course = raw_courses.get(canvas_course_id)
        canvas_course = _parse_course(raw_course) if raw_course else None
        if canvas_course is None:
            results.append(
                CanvasCourseImportResult(
                    canvas_course_id=canvas_course_id,
                    status="failed",
                    message="Canvas course not found.",
                )
            )
            continue

        try:
            async with asyncio.timeout(remaining):
                course, roster_sync = await _import_resolved_course(
                    db,
                    user,
                    connection_id,
                    canvas_course,
                    raw_course,
                )
            results.append(
                CanvasCourseImportResult(
                    canvas_course_id=canvas_course_id,
                    status="imported",
                    course=course,
                    roster_sync=roster_sync,
                )
            )
        except TimeoutError:
            await db.rollback()
            results.extend(
                _timed_out_import(course_id)
                for course_id in requested_ids[index:]
            )
            break
        except AppError as exc:
            await db.rollback()
            already_imported = exc.code == "canvas_course_already_imported"
            existing_course = None
            if already_imported:
                link = await canvas_course_links.get_by_canvas_course(
                    db, user_id, canvas_course_id
                )
                if link:
                    existing_course = await _course_response(db, link.course_id)
            results.append(
                CanvasCourseImportResult(
                    canvas_course_id=canvas_course_id,
                    status="already_imported" if already_imported else "failed",
                    course=existing_course,
                    message=exc.message,
                )
            )
        except Exception:
            await db.rollback()
            logger.exception("Unexpected Canvas course import failure")
            results.append(
                CanvasCourseImportResult(
                    canvas_course_id=canvas_course_id,
                    status="failed",
                    message="The course could not be imported.",
                )
            )

    return CanvasCourseImportResponse(results=results)


def _timed_out_import(canvas_course_id: str) -> CanvasCourseImportResult:
    return CanvasCourseImportResult(
        canvas_course_id=canvas_course_id,
        status="failed",
        message="The Canvas import time limit was reached.",
    )


async def _available_courses(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> dict[str, dict[str, Any]]:
    items = await call_canvas(
        db, user_id, lambda client, token: client.get_courses(token)
    )
    return {
        course_id: item
        for item in items
        if isinstance(item, dict) and (course_id := _course_id(item))
    }


async def _import_resolved_course(
    db: AsyncSession,
    user: User,
    connection_id: uuid.UUID,
    canvas_course: CanvasCourseResponse,
    raw_course: dict[str, Any],
) -> tuple[CourseResponse, CanvasRosterSyncResponse]:
    user_id = user.id
    students, skip_reasons = parse_students_with_skips(
        await call_canvas(
            db,
            user_id,
            lambda client, token: client.get_students(token, canvas_course.id),
        )
    )
    term_name, term_calendar_year = _course_period(raw_course)
    academic_term = await academic_term_service.resolve_imported_term(
        db,
        user,
        term_name,
    )
    academic_year_start = _academic_year_start(
        term_calendar_year,
        academic_term.year_format_enum,
    )
    synced_at = utc_now()
    try:
        course = await courses.create(
            db,
            _omr_course_name(canvas_course),
            academic_term,
            user_id,
            academic_year_start,
        )
        link = await canvas_course_links.create(
            db,
            course=course,
            canvas_connection_id=connection_id,
            canvas_course_id=canvas_course.id,
            synced_at=synced_at,
        )
        roster_sync = await reconcile_roster(
            db, course.id, students, synced_at, skip_reasons
        )
        link.last_synced_at = synced_at
        await db.commit()
        await db.refresh(course)
        return (
            CourseResponse.model_validate(course).model_copy(
                update={
                    "student_count": roster_sync.active,
                    "can_manage_canvas": True,
                }
            ),
            roster_sync,
        )
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "This Canvas course has already been imported",
            code="canvas_course_already_imported",
        ) from exc
    except Exception:
        await db.rollback()
        raise


def _course_id(item: Any) -> str | None:
    if not isinstance(item, dict):
        return None
    return normalize_canvas_id(item.get("id"))


async def _course_response(
    db: AsyncSession, course_id: uuid.UUID
) -> CourseResponse | None:
    course = await courses.get_by_id(db, course_id)
    if course is None:
        return None
    return CourseResponse.model_validate(course).model_copy(
        update={
            "student_count": await course_roster_entries.count_active_by_course(
                db, course.id
            ),
            "can_manage_canvas": True,
        }
    )


def _parse_course(item: Any) -> CanvasCourseResponse | None:
    course_id = _course_id(item)
    if course_id is None or not isinstance(item, dict):
        return None
    return CanvasCourseResponse(
        id=course_id,
        name=str(item.get("name") or item.get("course_code") or course_id),
        course_code=_optional_string(item.get("course_code")),
    )


def _course_period(item: dict[str, Any]) -> tuple[str, int]:
    term = item.get("term")
    if not isinstance(term, dict):
        return "Canvas", utc_now().year
    name = _optional_string(term.get("name")) or "Canvas"
    start_at = _optional_string(term.get("start_at"))
    if start_at:
        try:
            return name, datetime.fromisoformat(start_at.replace("Z", "+00:00")).year
        except ValueError:
            pass
    return name, utc_now().year


def _academic_year_start(
    term_calendar_year: int,
    year_format: AcademicTermYearFormat,
) -> int:
    if year_format == AcademicTermYearFormat.FOLLOWING_YEAR:
        return term_calendar_year - 1
    return term_calendar_year


def _omr_course_name(course: CanvasCourseResponse) -> str:
    code = course.course_code or f"Canvas {course.id}"
    return course.name if course.name.startswith(f"{code} - ") else f"{code} - {course.name}"


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
