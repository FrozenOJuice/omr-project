import csv
import io
import logging
import re
import uuid
from datetime import datetime
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import ConflictError, ForbiddenError
from models.exam import Exam
from models.user import User, UserRole
from repositories import canvas_grade_releases
from repositories import courses as course_repo
from repositories import exams as exam_repo
from repositories.exam_answer_keys import (
    delete_answer_keys_by_exam,
    list_answer_keys_by_exam,
    list_answer_keys_by_exam_ids,
)
from repositories.exam_grades import exam_has_any_grade, list_grades_by_exam
from repositories.exam_release_audit_entries import (
    create_release_audit_entry,
    list_release_audit_entries_by_exam,
)
from repositories.exam_templates import get_exam_template_by_id, get_exam_templates_by_ids
from repositories.scans import ScanRepository
from repositories.users import get_users_by_ids
from services import canvas_assignments, canvas_grades
from services.answer_key_status import answer_keys_are_complete
from services.notifications import notify_user

logger = logging.getLogger(__name__)


MISSING_TEMPLATE_WARNING = "This exam no longer has a bubble-sheet template attached."


def _template_warning_fields(exam: Exam) -> dict:
    missing = exam.exam_template_id is None
    return {
        "template_missing": missing,
        "template_warning": MISSING_TEMPLATE_WARNING if missing else None,
    }


def _exam_response_fields(exam: Exam, canvas_assignment=None) -> dict:
    return {
        'id': exam.id,
        'name': exam.name,
        'description': exam.description,
        'start_time': exam.start_time,
        'end_time': exam.end_time,
        'role': exam.role,
        'course_id': exam.course_id,
        'created_by': exam.created_by,
        'created_at': exam.created_at,
        'exam_template_id': exam.exam_template_id,
        'released': exam.released,
        'generated_pdf_path': exam.generated_pdf_path,
        'canvas_assignment_id': (
            canvas_assignment.canvas_assignment_id
            if canvas_assignment else None
        ),
        'canvas_assignment_name': (
            canvas_assignment.name if canvas_assignment else None
        ),
        **_template_warning_fields(exam),
    }


def _exam_readiness_fields(answer_keys: list, template) -> dict:
    return {
        "has_answer_key": bool(answer_keys),
        "answer_keys_complete": bool(
            template
            and answer_keys_are_complete(template.n_versions, answer_keys)
        ),
        "template_registered": bool(template and template.omr_template_id),
    }


async def _exam_response(db: AsyncSession, exam: Exam) -> dict:
    assignments = await canvas_grade_releases.assignments_by_exam(db, [exam.id])
    answer_keys = await list_answer_keys_by_exam(db, exam.id)
    template = (
        await get_exam_template_by_id(db, exam.exam_template_id)
        if exam.exam_template_id
        else None
    )
    return {
        **_exam_response_fields(exam, assignments.get(exam.id)),
        **_exam_readiness_fields(answer_keys, template),
        # Same "any grade exists" check the answer-key freeze guard uses,
        # exposed here so the answer-key page (which loads the exam directly,
        # not through the course exam list) can lock its own UI to match.
        # Deliberately a different name than list_exams_by_course's
        # `is_graded`, which means "every uploaded scan is graded," not "at
        # least one is."
        'has_any_grade': await exam_has_any_grade(db, exam.id),
    }


async def _require_course_access(db: AsyncSession, course_id: uuid.UUID, user: User) -> None:
    course = await course_repo.get_by_id(db, course_id)
    if not course:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Course {course_id} not found.",
        )
    if user.role_enum != UserRole.ADMIN and course.created_by != user.id:
        raise ForbiddenError("Not authorized to manage exams for this course", code="forbidden")
    _ensure_course_active(course)


def _ensure_course_active(course) -> None:
    if course and course.archived_at is not None:
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def _require_owned_template(db: AsyncSession, exam_template_id: uuid.UUID, user: User) -> None:
    template = await get_exam_template_by_id(db, exam_template_id)
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Exam template not found.",
        )
    if template.created_by != user.id:
        raise ForbiddenError("Not authorized to use this exam template", code="forbidden")
    if template.archived_at is not None:
        raise ConflictError(
            "Archived templates cannot be assigned to an exam. Restore the template first.",
            code="template_archived",
        )


async def get_exam(db: AsyncSession, exam_id: uuid.UUID) -> dict:
    exam = await exam_repo.get_exam_by_id(db, exam_id)
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam {exam_id} not found.",
        )
    return await _exam_response(db, exam)


async def list_exams_by_course(db: AsyncSession, course_id: uuid.UUID, user) -> list[dict]:
    exams = await exam_repo.get_exams_by_course(db, course_id)
    if not exams:
        return []
    exam_ids = [e.id for e in exams]

    scan_counts = await exam_repo.get_scan_counts_by_exam(db, exam_ids)
    graded_counts = await exam_repo.get_graded_counts_by_exam(db, exam_ids)
    failed_counts = await exam_repo.get_failed_counts_by_exam(db, exam_ids)
    answer_keys_by_exam = await list_answer_keys_by_exam_ids(db, exam_ids)
    template_ids = list({e.exam_template_id for e in exams if e.exam_template_id})
    templates_by_id = await get_exam_templates_by_ids(db, template_ids)
    pending_review_request_counts = await exam_repo.get_pending_review_request_counts_by_exam(db, exam_ids)
    ambiguous_grade_counts = await exam_repo.get_ambiguous_grade_counts_by_exam(db, exam_ids)
    canvas_assignments = await canvas_grade_releases.assignments_by_exam(db, exam_ids)

    if user.role_enum == UserRole.STUDENT:
        graded_ids = await exam_repo.get_graded_exam_ids_for_student(db, exam_ids, user.id)
        exam_by_id = {e.id: e for e in exams}

        def is_graded(exam_id: uuid.UUID) -> bool:
            # A grade existing isn't enough -- it must also be released, or
            # the badge would promise a student a result GET /grades won't
            # actually return yet (see grading_router.py's _can_access_grade).
            return exam_id in graded_ids and exam_by_id[exam_id].released
    else:
        def is_graded(exam_id: uuid.UUID) -> bool:
            # "Graded" means every currently-uploaded scan has been graded, not
            # just that at least one has — otherwise the badge would flip to
            # Graded while other scans in the same batch are still processing.
            total = scan_counts.get(exam_id, 0)
            return total > 0 and graded_counts.get(exam_id, 0) >= total

    return [
        {
            **_exam_response_fields(e, canvas_assignments.get(e.id)),
            'is_graded': is_graded(e.id),
            'has_scans': scan_counts.get(e.id, 0) > 0,
            'total_scans': scan_counts.get(e.id, 0),
            'graded_scans': graded_counts.get(e.id, 0),
            'failed_scans': failed_counts.get(e.id, 0),
            **_exam_readiness_fields(
                answer_keys_by_exam.get(e.id, []),
                templates_by_id.get(e.exam_template_id),
            ),
            'pending_review_request_count': pending_review_request_counts.get(e.id, 0),
            'ambiguous_grade_count': ambiguous_grade_counts.get(e.id, 0),
        }
        for e in exams
    ]


async def list_exams_by_creator(db: AsyncSession, user_id: uuid.UUID) -> list[dict]:
    exams = await exam_repo.get_exams_by_creator(db, user_id)
    if not exams:
        return []
    exam_ids = [exam.id for exam in exams]
    assignments = await canvas_grade_releases.assignments_by_exam(db, exam_ids)
    answer_keys_by_exam = await list_answer_keys_by_exam_ids(db, exam_ids)
    template_ids = list({e.exam_template_id for e in exams if e.exam_template_id})
    templates_by_id = await get_exam_templates_by_ids(db, template_ids)
    return [
        {
            **_exam_response_fields(exam, assignments.get(exam.id)),
            **_exam_readiness_fields(
                answer_keys_by_exam.get(exam.id, []),
                templates_by_id.get(exam.exam_template_id),
            ),
        }
        for exam in exams
    ]


async def create_new_exam(
    db: AsyncSession,
    name: str,
    description: Optional[str],
    start_time: Optional[datetime],
    end_time: Optional[datetime],
    role: str,
    course_id: uuid.UUID,
    exam_template_id: uuid.UUID,
    user: User,
    canvas_assignment_id: str | None = None,
) -> dict:
    _validate_exam_schedule(start_time, end_time)

    await _require_course_access(db, course_id, user)
    await _require_owned_template(db, exam_template_id, user)

    try:
        resolved_assignment = (
            await canvas_assignments.resolve(
                db, user, course_id, canvas_assignment_id
            )
            if canvas_assignment_id is not None
            else None
        )
        if resolved_assignment is not None:
            name = resolved_assignment.name
        new_exam = await exam_repo.create_exam(
            db,
            name,
            description,
            start_time,
            end_time,
            role,
            course_id,
            user.id,
            exam_template_id,
        )
        if canvas_assignment_id is not None:
            await canvas_grades.set_assignment(
                db,
                user,
                new_exam.id,
                canvas_assignment_id,
                resolved_assignment=resolved_assignment,
                commit=False,
            )
        await db.commit()
        await db.refresh(new_exam)
        return await _exam_response(db, new_exam)
    except Exception:
        await db.rollback()
        raise


def _validate_exam_schedule(
    start_time: Optional[datetime], end_time: Optional[datetime]
) -> None:
    if (start_time is None) != (end_time is None):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time and end_time must both be provided or both omitted.",
        )
    if start_time is not None and end_time is not None and end_time <= start_time:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="end_time must be after start_time.",
        )


async def update_existing_exam(
    db: AsyncSession,
    exam_id: uuid.UUID,
    user: User,
    name: Optional[str] = None,
    description: Optional[str] = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    role: Optional[str] = None,
    course_id: Optional[uuid.UUID] = None,
    exam_template_id: Optional[uuid.UUID] = None,
    delete_answer_keys: bool = False,
    schedule_provided: bool = False,
) -> dict:
    existing_exam = await exam_repo.get_exam_by_id(db, exam_id)
    if not existing_exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam {exam_id} not found.",
        )

    course = await course_repo.get_by_id(db, existing_exam.course_id)
    if user.role_enum != UserRole.ADMIN and course and course.created_by != user.id:
        raise ForbiddenError("Not authorized to update this exam", code="forbidden")
    _ensure_course_active(course)
    if course_id is not None:
        await _require_course_access(db, course_id, user)

    resolved_start = start_time if schedule_provided else existing_exam.start_time
    resolved_end = end_time if schedule_provided else existing_exam.end_time
    _validate_exam_schedule(resolved_start, resolved_end)

    if exam_template_id is not None:
        await _require_owned_template(db, exam_template_id, user)

    changing_template = (
        exam_template_id is not None
        and exam_template_id != existing_exam.exam_template_id
    )
    if changing_template:
        scan_counts = await exam_repo.get_scan_counts_by_exam(db, [exam_id])
        scan_count = scan_counts.get(exam_id, 0)
        # A force-deleted template leaves the exam detached. Allow assigning a
        # replacement so the exam is not permanently stranded.
        if scan_count and existing_exam.exam_template_id is not None:
            raise ConflictError(
                "Cannot change the template after scans have been uploaded.",
                code="exam_has_scans",
                details={"scan_count": scan_count},
            )

        answer_key_counts = await exam_repo.get_answer_key_counts_by_exam(
            db, [exam_id]
        )
        answer_key_count = answer_key_counts.get(exam_id, 0)
        if answer_key_count and not delete_answer_keys:
            raise ConflictError(
                "Changing the template requires deleting the existing answer keys.",
                code="answer_keys_require_reset",
                details={"answer_key_count": answer_key_count},
            )

    try:
        if changing_template and delete_answer_keys:
            await delete_answer_keys_by_exam(db, exam_id)
        updated_exam = await exam_repo.update_exam(
            db,
            existing_exam,
            name,
            description,
            start_time,
            end_time,
            role,
            course_id,
            exam_template_id,
            update_schedule=schedule_provided,
        )
        await db.commit()
        await db.refresh(updated_exam)
        return await _exam_response(db, updated_exam)
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Error updating exam: {str(e)}",
        )


async def delete_existing_exam(db: AsyncSession, exam_id: uuid.UUID, user: User) -> None:
    existing_exam = await exam_repo.get_exam_by_id(db, exam_id)
    if not existing_exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam {exam_id} not found.",
        )

    course = await course_repo.get_by_id(db, existing_exam.course_id)
    if user.role_enum != UserRole.ADMIN and course and course.created_by != user.id:
        raise ForbiddenError("Not authorized to delete this exam", code="forbidden")
    _ensure_course_active(course)

    try:
        await exam_repo.delete_exam(db, existing_exam)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Error deleting exam: {str(e)}",
        )


async def get_release_blockers(db: AsyncSession, exam_id: uuid.UUID) -> list[dict]:
    """Return every reason release should be refused: a grade still flagged
    needs_review (ambiguous marks, unmatched/ambiguous student identity, low
    OCR confidence -- see grading_service.py's flag reasons) or a scan that
    hasn't finished processing. Empty list means release is allowed.
    """
    grades = await list_grades_by_exam(db, exam_id)
    scans = await ScanRepository.get_by_exam(db, exam_id)

    blockers = [
        {"type": "grade", "id": str(grade.id), "reason": grade.flag_reason}
        for grade in grades
        if grade.status == "needs_review"
    ]
    blockers += [
        {"type": "scan", "id": str(scan.id), "reason": scan.status}
        for scan in scans
        if scan.status in ("pending", "failed")
    ]
    return blockers


async def _authorize_release(db: AsyncSession, exam: Exam, user: User) -> None:
    """Only an admin or the professor who owns the exam's course may
    release/close its results -- require_admin_or_prof only checks role, not
    course ownership, so a professor from another course would otherwise slip
    through (same gap apply_grade_corrections guards against).
    """
    course = await course_repo.get_by_id(db, exam.course_id)
    if user.role_enum != UserRole.ADMIN and (not course or course.created_by != user.id):
        raise ForbiddenError(
            "You do not have permission to release results for this exam",
            code="exam_release_forbidden",
        )
    _ensure_course_active(course)


async def _can_view_release_history(db: AsyncSession, exam: Exam, user: User) -> bool:
    if user.role_enum == UserRole.ADMIN:
        return True

    course = await course_repo.get_by_id(db, exam.course_id)
    if not course:
        return False
    if course.created_by == user.id:
        return True

    enrolment = await course_repo.get_enrolment(db, course.id, user.id)
    return enrolment is not None and enrolment.role == "professor"


async def _get_exam_or_404(
    db: AsyncSession, exam_id: uuid.UUID, *, for_update: bool = False
) -> Exam:
    exam = await exam_repo.get_exam_by_id(db, exam_id, for_update=for_update)
    if not exam:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Exam {exam_id} not found.",
        )
    return exam


async def get_release_history(db: AsyncSession, exam_id: uuid.UUID, user: User) -> list[dict]:
    exam = await _get_exam_or_404(db, exam_id)
    if not await _can_view_release_history(db, exam, user):
        raise ForbiddenError("Insufficient permissions", code="insufficient_permissions")

    entries = await list_release_audit_entries_by_exam(db, exam.id)
    actor_ids = {entry.actor_user_id for entry in entries if entry.actor_user_id is not None}
    actors = await get_users_by_ids(db, list(actor_ids))
    actor_names = {actor.id: actor.full_name for actor in actors}

    return [
        {
            "id": entry.id,
            "exam_id": entry.exam_id,
            "actor_user_id": entry.actor_user_id,
            "actor_name": actor_names.get(entry.actor_user_id),
            "event_type": entry.event_type,
            "created_at": entry.created_at,
        }
        for entry in entries
    ]


async def release_exam(db: AsyncSession, exam_id: uuid.UUID, user: User) -> dict:
    exam = await _get_exam_or_404(db, exam_id, for_update=True)
    await _authorize_release(db, exam, user)

    # Idempotent retries are not new release events and must not resend every
    # student's notification.
    if exam.released:
        await db.commit()
        await db.refresh(exam)
        return await _exam_response(db, exam)

    blockers = await get_release_blockers(db, exam_id)
    if blockers:
        raise ConflictError(
            "Exam has unresolved grades or scans blocking release",
            code="exam_release_blocked",
            details=blockers,
        )

    exam.released = True
    await create_release_audit_entry(
        db, exam_id=exam.id, actor_user_id=user.id, event_type="released"
    )
    await db.commit()
    await db.refresh(exam)

    await _notify_students_of_release(db, exam)
    return await _exam_response(db, exam)


async def _notify_students_of_release(db: AsyncSession, exam: Exam) -> None:
    """Fire grade_ready for every matched, graded ExamGrade on this exam --
    the sole place that notification originates now (grading_service no
    longer sends it the moment a scan is auto-graded). Runs after release is
    already committed, so a single failed notification can't undo it.
    """
    grades = await list_grades_by_exam(db, exam.id)
    for grade in grades:
        if grade.status != "graded" or grade.student_id is None:
            continue
        try:
            await notify_user(
                db,
                recipient_user_id=grade.student_id,
                type="grade_ready",
                title="Your exam has been graded",
                body=exam.name,
                course_id=exam.course_id,
                link_path="/courses",
                link_query=f"courseId={exam.course_id}&examId={exam.id}",
            )
        except Exception:
            logger.exception(
                "Failed to send grade_ready notification for grade %s", grade.id
            )


async def close_exam(db: AsyncSession, exam_id: uuid.UUID, user: User) -> dict:
    exam = await _get_exam_or_404(db, exam_id, for_update=True)
    await _authorize_release(db, exam, user)

    if not exam.released:
        await db.commit()
        await db.refresh(exam)
        return await _exam_response(db, exam)

    exam.released = False
    await create_release_audit_entry(
        db, exam_id=exam.id, actor_user_id=user.id, event_type="closed"
    )
    await db.commit()
    await db.refresh(exam)
    return await _exam_response(db, exam)


def _export_filename(exam_name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", exam_name).strip("-").lower() or "exam"
    return f"{slug}-results.csv"


def _question_sort_key(question_number: str) -> tuple:
    # Question numbers are dict keys, so "10" would sort before "2" as plain
    # strings; non-numeric keys sort after the numeric ones.
    if question_number.isdigit():
        return (0, int(question_number))
    return (1, question_number)


def _csv_safe(value: str) -> str:
    """Guard against CSV/formula injection: a cell starting with =, +, -, @,
    tab, or CR is treated as a formula by Excel/Sheets, so a student named
    "=HYPERLINK(...)" would execute on the instructor's machine. Prefixing
    with ' makes the spreadsheet render it as a literal string.
    """
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return f"'{value}"
    return value


async def export_exam_results_csv(
    db: AsyncSession, exam_id: uuid.UUID, user: User
) -> tuple[str, str]:
    """Serialize every grade for the exam into CSV rows: student identifier,
    exam version, per-question responses, scores, and exam metadata (FR9.2).
    needs_review grades are included with blank student fields so the export
    shows it is incomplete rather than silently dropping a scan.
    """
    exam = await _get_exam_or_404(db, exam_id)
    await _authorize_release(db, exam, user)

    course = await course_repo.get_by_id(db, exam.course_id)
    grades = await list_grades_by_exam(db, exam_id)
    answer_keys = await list_answer_keys_by_exam(db, exam_id)

    version_by_key = {key.id: key.exam_version for key in answer_keys}
    student_ids = [g.student_id for g in grades if g.student_id is not None]
    student_by_id = {s.id: s for s in await get_users_by_ids(db, student_ids)}

    # Every question any version defines, plus any grade results that no
    # longer match a key (e.g. the key was edited after grading).
    question_numbers: set[str] = {q for key in answer_keys for q in key.answer_key}
    for grade in grades:
        question_numbers.update((grade.question_results or {}).keys())
    ordered_questions = sorted(question_numbers, key=_question_sort_key)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["student_number", "student_name", "exam_version", "status", "flag_reason"]
        + [f"Q{q}" for q in ordered_questions]
        + ["total_score", "max_score", "exam_name", "course_name", "academic_term", "exam_date", "graded_at"]
    )
    for grade in grades:
        student = student_by_id.get(grade.student_id)
        results = grade.question_results or {}
        responses = [
            ",".join((results.get(q) or {}).get("student_answers") or [])
            for q in ordered_questions
        ]
        writer.writerow(
            [
                _csv_safe((student.student_number or "") if student else ""),
                _csv_safe(student.full_name if student else ""),
                _csv_safe(version_by_key.get(grade.exam_answer_key_id) or ""),
                grade.status,
                _csv_safe(grade.flag_reason or ""),
            ]
            + [_csv_safe(response) for response in responses]
            + [
                grade.total_score,
                grade.max_score,
                _csv_safe(exam.name),
                _csv_safe(course.name if course else ""),
                _csv_safe(
                    course.academic_term.name
                    if course and course.academic_term
                    else ""
                ),
                exam.start_time.date().isoformat() if exam.start_time else "",
                grade.graded_at.isoformat(),
            ]
        )

    return _export_filename(exam.name), buffer.getvalue()
