from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from errors.exceptions import ConflictError
from models.course import Course
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.review_request import ReviewRequest
from models.scan import Scan
from repositories.exam_grades import exam_has_any_grade


def _is_archived(value: object) -> bool:
    """Return true only for the persisted archive timestamp.

    AsyncMock.scalar() produces another mock when older isolated unit tests do
    not configure the new lifecycle query. Treating every non-None object as an
    archive timestamp incorrectly makes those active-course fixtures read-only.
    """
    return isinstance(value, datetime)


def ensure_course_writable(course: Course) -> None:
    if _is_archived(getattr(course, "archived_at", None)):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def ensure_course_id_writable(db: AsyncSession, course_id: UUID) -> None:
    archived_at = await db.scalar(select(Course.archived_at).where(Course.id == course_id))
    if _is_archived(archived_at):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def ensure_exam_course_writable(db: AsyncSession, exam_id: UUID) -> None:
    archived_at = await db.scalar(
        select(Course.archived_at)
        .join(Exam, Exam.course_id == Course.id)
        .where(Exam.id == exam_id)
    )
    if _is_archived(archived_at):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def ensure_scan_course_writable(db: AsyncSession, scan_id: UUID) -> None:
    archived_at = await db.scalar(
        select(Course.archived_at)
        .join(Exam, Exam.course_id == Course.id)
        .join(Scan, Scan.exam_id == Exam.id)
        .where(Scan.id == scan_id)
    )
    if _is_archived(archived_at):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def ensure_grade_course_writable(db: AsyncSession, grade_id: UUID) -> None:
    archived_at = await db.scalar(
        select(Course.archived_at)
        .join(Exam, Exam.course_id == Course.id)
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamGrade.id == grade_id)
    )
    if _is_archived(archived_at):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )


async def ensure_exam_not_graded(db: AsyncSession, exam_id: UUID) -> None:
    if await exam_has_any_grade(db, exam_id):
        raise ConflictError(
            "This exam already has graded submissions. The answer key is locked to keep grades consistent with what was graded.",
            code="exam_already_graded",
        )


async def ensure_review_request_course_writable(
    db: AsyncSession, review_request_id: UUID
) -> None:
    archived_at = await db.scalar(
        select(Course.archived_at)
        .join(Exam, Exam.course_id == Course.id)
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .join(ReviewRequest, ReviewRequest.exam_grade_id == ExamGrade.id)
        .where(ReviewRequest.id == review_request_id)
    )
    if _is_archived(archived_at):
        raise ConflictError(
            "Archived courses are read-only. Restore the course before making changes.",
            code="course_archived_read_only",
        )
