import asyncio
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from html import escape
import math
from typing import Any
from urllib.parse import quote, urlparse
import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from core.tokens import create_canvas_student_access_token
from errors.exceptions import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from integrations.canvas_client import CanvasClient, CanvasRequestError
from models.canvas_assignment_link import CanvasAssignmentLink
from models.canvas_grade_release import CanvasGradeRelease
from models.canvas_grade_release_attempt import (
    CanvasGradeReleaseAttempt,
    CanvasGradeReleaseRecipient,
)
from models.course import Course
from models.exam import Exam
from models.user import User
from repositories import (
    canvas_assignment_links,
    canvas_grade_releases,
    course_roster_entries,
    exam_grades,
    exams,
)
from schemas.canvas_schema import CanvasGradeReleaseResponse
from services import canvas_assignments
from services.canvas_access import connected_course, manageable_course
from services.canvas_batch import BatchResult, bounded_map
from services.canvas_connection import call_canvas, utc_now


GRADE_RELEASE_LEASE_GRACE_SECONDS = 5


@dataclass(frozen=True)
class GradeCandidate:
    canvas_user_id: str
    student_id: uuid.UUID
    exam_grade_id: uuid.UUID
    percentage: float


async def get_grade_release(
    db: AsyncSession,
    user: User,
    exam_id: uuid.UUID,
) -> CanvasGradeReleaseResponse:
    exam, _ = await _manageable_exam(db, user, exam_id)
    release = await canvas_grade_releases.get_by_exam(db, exam.id)
    return await _response(db, exam, release)


async def release_grades(
    db: AsyncSession,
    user: User,
    exam_id: uuid.UUID,
) -> CanvasGradeReleaseResponse:
    exam, course = await _manageable_exam(db, user, exam_id)
    if course.archived_at is not None:
        raise ConflictError(
            "Restore the course before sending grades to Canvas",
            code="course_archived",
        )
    if not exam.released:
        raise ConflictError(
            "Release the exam results in OMR before sending them to Canvas",
            code="exam_not_released",
        )

    _, _, canvas_course_id = await connected_course(db, user, course.id)
    release = await canvas_grade_releases.get_by_exam(db, exam.id)
    saved_assignment = await _release_assignment(db, course.id, release)
    if release is None or saved_assignment is None:
        raise ConflictError(
            "Link this exam to a Canvas assignment before sending grades",
            code="canvas_assignment_not_linked",
        )
    assignment = await canvas_assignments.resolve(
        db, user, course.id, saved_assignment.canvas_assignment_id
    )
    if assignment.points_possible is None or assignment.points_possible <= 0:
        raise BadRequestError(
            "Set a positive point value for the Canvas assignment first",
            code="canvas_assignment_has_no_points",
        )

    candidates, skipped = await _grade_candidates(db, exam)
    if not candidates:
        raise ConflictError(
            "No exam grades are linked to active Canvas students",
            code="no_canvas_grades",
            details=dict(skipped),
        )
    result_base_url = _student_result_base_url()

    release = await canvas_grade_releases.get_by_exam(db, exam.id, for_update=True)
    if (
        release is None
        or release.canvas_assignment_link_id != assignment.id
    ):
        raise ConflictError(
            "The linked Canvas assignment changed. Review it and try again.",
            code="canvas_assignment_changed",
        )
    await _require_idle_release(db, release)

    attempt = CanvasGradeReleaseAttempt(
        canvas_grade_release_id=release.id,
        requested_by=user.id,
        skipped_count=sum(skipped.values()),
        started_at=utc_now(),
    )
    db.add(attempt)
    await db.flush()
    recipients = [
        CanvasGradeReleaseRecipient(
            attempt_id=attempt.id,
            canvas_user_id=candidate.canvas_user_id,
            percentage=candidate.percentage,
        )
        for candidate in candidates
    ]
    db.add_all(recipients)
    await db.commit()

    await _publish_attempt(
        db,
        user.id,
        canvas_course_id,
        assignment,
        attempt,
        recipients,
        candidates,
        result_base_url,
        release,
    )
    if attempt.status == "failed":
        raise ServiceUnavailableError(
            "Canvas did not accept any grades",
            code="canvas_grade_release_failed",
            details={
                "sent": attempt.sent_count,
                "failed": attempt.failed_count,
                "skipped": attempt.skipped_count,
            },
        )
    return await _response(db, exam, release)


async def set_assignment(
    db: AsyncSession,
    user: User,
    exam_id: uuid.UUID,
    assignment_id: str,
    *,
    resolved_assignment: CanvasAssignmentLink | None = None,
    commit: bool = True,
) -> CanvasGradeReleaseResponse:
    exam, course = await _manageable_exam(db, user, exam_id)
    if course.archived_at is not None:
        raise ConflictError(
            "Restore the course before changing its Canvas assignments",
            code="course_archived",
        )

    assignment = resolved_assignment or await canvas_assignments.resolve(
        db, user, course.id, assignment_id
    )
    if (
        assignment.course_id != course.id
        or assignment.canvas_assignment_id != assignment_id
    ):
        raise BadRequestError(
            "The Canvas assignment is no longer available",
            code="canvas_assignment_not_found",
        )
    used_by = await canvas_grade_releases.get_by_assignment(db, assignment.id)
    if used_by and used_by.exam_id != exam.id:
        raise ConflictError(
            "This Canvas assignment is already linked to another exam",
            code="canvas_assignment_in_use",
        )

    release = await canvas_grade_releases.get_by_exam(
        db, exam.id, for_update=True
    )
    if (
        release
        and release.first_released_at
        and release.canvas_assignment_link_id != assignment.id
    ):
        raise ConflictError(
            "Canvas grades were already sent to a different assignment",
            code="canvas_release_target_locked",
        )
    if release:
        await _require_idle_release(db, release)

    old_assignment = await _release_assignment(db, course.id, release)
    if release is None:
        release = CanvasGradeRelease(
            exam_id=exam.id,
            canvas_assignment_link_id=assignment.id,
        )
        db.add(release)
    else:
        release.canvas_assignment_link_id = assignment.id
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictError(
            "This Canvas assignment is already linked to another exam",
            code="canvas_assignment_in_use",
        ) from exc
    if old_assignment and old_assignment.id != assignment.id:
        await db.delete(old_assignment)
    if commit:
        await db.commit()
    return await _response(db, exam, release)


async def clear_assignment(
    db: AsyncSession,
    user: User,
    exam_id: uuid.UUID,
) -> CanvasGradeReleaseResponse:
    exam, course = await _manageable_exam(db, user, exam_id)
    release = await canvas_grade_releases.get_by_exam(
        db, exam.id, for_update=True
    )
    if release is None:
        return await _response(db, exam, None)
    if release.first_released_at:
        raise ConflictError(
            "The Canvas assignment cannot change after grades have been sent",
            code="canvas_release_target_locked",
        )
    await _require_idle_release(db, release)

    assignment = await _release_assignment(db, course.id, release)
    await db.delete(release)
    await db.flush()
    if assignment:
        await db.delete(assignment)
    await db.commit()
    return await _response(db, exam, None)


async def _manageable_exam(
    db: AsyncSession,
    user: User,
    exam_id: uuid.UUID,
) -> tuple[Exam, Course]:
    exam = await exams.get_exam_by_id(db, exam_id)
    if exam is None:
        raise NotFoundError("Exam not found", code="exam_not_found")
    return exam, await manageable_course(db, user, exam.course_id)


async def _require_idle_release(
    db: AsyncSession, release: CanvasGradeRelease
) -> None:
    attempt = await canvas_grade_releases.get_running_attempt(db, release.id)
    if attempt is None:
        return
    lease = timedelta(
        seconds=(
            settings.canvas_operation_timeout_seconds
            + GRADE_RELEASE_LEASE_GRACE_SECONDS
        )
    )
    if attempt.started_at + lease > utc_now():
        raise ConflictError(
            "A Canvas grade release is already in progress",
            code="canvas_grade_release_in_progress",
        )
    recipients = await canvas_grade_releases.list_recipients(db, attempt.id)
    _mark_attempt_finished(
        attempt,
        recipients,
        release,
        interrupted=True,
        interruption_code="release_stale",
    )
    await db.flush()


async def _grade_candidates(
    db: AsyncSession,
    exam: Exam,
) -> tuple[list[GradeCandidate], Counter[str]]:
    skipped: Counter[str] = Counter()
    grades_by_student: dict[uuid.UUID, list[Any]] = defaultdict(list)
    for grade in await exam_grades.list_grades_by_exam(db, exam.id):
        if grade.status != "graded" or grade.student_id is None:
            skipped["unresolved_grade"] += 1
        elif (
            not math.isfinite(grade.total_score)
            or not math.isfinite(grade.max_score)
            or grade.max_score <= 0
        ):
            skipped["invalid_score"] += 1
        else:
            grades_by_student[grade.student_id].append(grade)

    canvas_ids = {
        entry.user_id: entry.canvas_user_id
        for entry in await course_roster_entries.list_active_by_course(
            db, exam.course_id
        )
        if entry.user_id is not None and entry.canvas_user_id is not None
    }
    candidates: list[GradeCandidate] = []
    for student_id, grades in grades_by_student.items():
        if len(grades) > 1:
            skipped["duplicate_student_grades"] += len(grades)
        elif canvas_user_id := canvas_ids.get(student_id):
            grade = grades[0]
            candidates.append(
                GradeCandidate(
                    canvas_user_id=canvas_user_id,
                    student_id=student_id,
                    exam_grade_id=grade.id,
                    percentage=grade.total_score / grade.max_score * 100,
                )
            )
        else:
            skipped["not_linked_to_canvas"] += 1
    return candidates, skipped


def _student_result_base_url() -> str:
    origin = (settings.frontend_origin or "").strip()
    parsed = urlparse(origin)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
    ):
        raise ServiceUnavailableError(
            "Configure a valid frontend origin before sending result links to Canvas",
            code="canvas_student_result_access_not_configured",
        )
    return origin.rstrip("/")


def _student_result_comment(base_url: str, candidate: GradeCandidate) -> str:
    access_token = create_canvas_student_access_token(
        candidate.student_id,
        candidate.exam_grade_id,
        candidate.canvas_user_id,
    )
    encoded_token = quote(access_token, safe="")
    result_url = f"{base_url}/canvas/results#token={encoded_token}"
    return (
        "Your marked exam result is ready in OMR.<br>"
        f'<a href="{escape(result_url, quote=True)}">'
        "View your marked exam scan</a><br><br>"
        "This student-specific link expires automatically."
    )


async def _release_assignment(
    db: AsyncSession,
    course_id: uuid.UUID,
    release: CanvasGradeRelease | None,
):
    if release is None:
        return None
    return next(
        (
            link
            for link in await canvas_assignment_links.list_by_course(db, course_id)
            if link.id == release.canvas_assignment_link_id
        ),
        None,
    )


def _recipient_counts(
    recipients: list[CanvasGradeReleaseRecipient],
) -> tuple[int, int]:
    return (
        sum(recipient.status == "sent" for recipient in recipients),
        sum(recipient.status == "failed" for recipient in recipients),
    )


def _grade_error_code(error: Exception) -> str:
    if isinstance(error, TimeoutError):
        return "canvas_operation_timeout"
    if isinstance(error, CanvasRequestError):
        return (
            f"canvas_http_{error.status_code}"
            if error.status_code
            else "canvas_request_failed"
        )
    return "canvas_request_failed"


def _apply_recipient_results(
    recipients: list[CanvasGradeReleaseRecipient],
    indices: list[int],
    results: list[BatchResult[dict[str, Any]]],
) -> None:
    for index, result in zip(indices, results, strict=True):
        recipient = recipients[index]
        if result.error is None:
            recipient.status = "sent"
            recipient.error_code = None
        else:
            recipient.status = "failed"
            recipient.error_code = _grade_error_code(result.error)


async def _publish_attempt(
    db: AsyncSession,
    user_id: uuid.UUID,
    canvas_course_id: str,
    assignment: CanvasAssignmentLink,
    attempt: CanvasGradeReleaseAttempt,
    recipients: list[CanvasGradeReleaseRecipient],
    candidates: list[GradeCandidate],
    result_base_url: str,
    release: CanvasGradeRelease,
) -> None:
    if len(recipients) != len(candidates):
        raise ValueError("Canvas release recipients do not match grade candidates")
    retry_indices: list[int] | None = None

    async def publish(client: CanvasClient, token: str) -> None:
        nonlocal retry_indices
        indices = retry_indices or list(range(len(recipients)))

        async def send(
            publication: tuple[CanvasGradeReleaseRecipient, GradeCandidate],
        ) -> dict[str, Any]:
            recipient, candidate = publication
            return await client.update_grade(
                token,
                canvas_course_id,
                assignment.canvas_assignment_id,
                recipient.canvas_user_id,
                f"{recipient.percentage:.10g}%",
                comment=_student_result_comment(result_base_url, candidate),
            )

        results = await bounded_map(
            [(recipients[index], candidates[index]) for index in indices],
            send,
            concurrency=settings.canvas_batch_concurrency,
            timeout=settings.canvas_operation_timeout_seconds,
        )
        _apply_recipient_results(recipients, indices, results)
        if retry_indices is None:
            unauthorized = [
                index
                for index, result in zip(indices, results, strict=True)
                if isinstance(result.error, CanvasRequestError)
                and result.error.status_code == 401
            ]
            if unauthorized:
                retry_indices = unauthorized
                raise next(
                    result.error
                    for result in results
                    if isinstance(result.error, CanvasRequestError)
                    and result.error.status_code == 401
                )

    try:
        await call_canvas(db, user_id, publish)
    except asyncio.CancelledError:
        await _finish_attempt(db, attempt, recipients, release, interrupted=True)
        raise
    except Exception:
        await _finish_attempt(db, attempt, recipients, release, interrupted=True)
        raise
    await _finish_attempt(db, attempt, recipients, release)


def _mark_attempt_finished(
    attempt: CanvasGradeReleaseAttempt,
    recipients: list[CanvasGradeReleaseRecipient],
    release: CanvasGradeRelease,
    *,
    interrupted: bool = False,
    interruption_code: str = "release_interrupted",
) -> None:
    if interrupted:
        for recipient in recipients:
            if recipient.status == "pending":
                recipient.status = "failed"
                recipient.error_code = interruption_code
    sent, failed = _recipient_counts(recipients)
    attempt.sent_count = sent
    attempt.failed_count = failed
    attempt.status = "completed" if not failed and not interrupted else (
        "partial" if sent else "failed"
    )
    completed_at = utc_now()
    attempt.completed_at = completed_at
    release.last_sent_count = sent
    release.last_skipped_count = attempt.skipped_count
    release.last_failed_count = failed
    if sent and release.first_released_at is None:
        release.first_released_at = completed_at
    if sent:
        release.last_released_at = completed_at


async def _finish_attempt(
    db: AsyncSession,
    attempt: CanvasGradeReleaseAttempt,
    recipients: list[CanvasGradeReleaseRecipient],
    release: CanvasGradeRelease,
    *,
    interrupted: bool = False,
) -> None:
    _mark_attempt_finished(attempt, recipients, release, interrupted=interrupted)
    await db.commit()


async def _response(
    db: AsyncSession,
    exam: Exam,
    release: CanvasGradeRelease | None,
) -> CanvasGradeReleaseResponse:
    candidates, skipped = await _grade_candidates(db, exam)
    assignment = await _release_assignment(db, exam.course_id, release)
    attempt = (
        await canvas_grade_releases.get_latest_attempt(db, release.id)
        if release
        else None
    )
    return CanvasGradeReleaseResponse(
        exam_id=exam.id,
        assignment_id=assignment.canvas_assignment_id if assignment else None,
        assignment_name=assignment.name if assignment else None,
        eligible_count=len(candidates),
        skipped_count=sum(skipped.values()),
        skipped_reasons=dict(skipped),
        target_locked=bool(release and release.first_released_at),
        last_sent_count=release.last_sent_count if release else 0,
        last_skipped_count=release.last_skipped_count if release else 0,
        last_failed_count=release.last_failed_count if release else 0,
        last_attempted_at=(attempt.completed_at or attempt.started_at) if attempt else None,
        last_attempt_status=attempt.status if attempt else None,
    )
