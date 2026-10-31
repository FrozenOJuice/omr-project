import hashlib
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade


def _student_grade_lock_key(exam_id: UUID, student_id: UUID) -> int:
    """Return a stable signed bigint for one exam/student assignment pair."""
    digest = hashlib.blake2b(
        exam_id.bytes + student_id.bytes,
        digest_size=8,
        person=b"exam-grade-v1",
    ).digest()
    return int.from_bytes(digest, byteorder="big", signed=True)


async def acquire_student_grade_lock(
    db: AsyncSession, exam_id: UUID, student_id: UUID
) -> None:
    """Serialize grade checks for one exam/student until transaction end.

    A plain "does a grade exist?" query is vulnerable to two concurrent
    transactions both observing no row and then assigning the same student.
    PostgreSQL transaction-level advisory locks give the pair a stable lock
    even before an ExamGrade row exists. The lock is released automatically
    by the service's commit or rollback.
    """
    await db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:lock_key AS BIGINT))"),
        {"lock_key": _student_grade_lock_key(exam_id, student_id)},
    )


async def create_grade(
    db: AsyncSession,
    omr_marking_id: UUID,
    exam_answer_key_id: UUID,
    question_results: dict,
    total_score: float,
    max_score: float,
    template_version: int,
    student_id: UUID | None = None,
    status: str = "graded",
    flag_reason: str | None = None,
    flush: bool = True,
) -> ExamGrade:
    grade = ExamGrade(
        id=uuid4(),
        omr_marking_id=omr_marking_id,
        exam_answer_key_id=exam_answer_key_id,
        question_results=question_results,
        total_score=total_score,
        max_score=max_score,
        template_version=template_version,
        student_id=student_id,
        status=status,
        flag_reason=flag_reason,
    )
    db.add(grade)
    if flush:
        await db.flush()
    return grade


async def get_grade_by_id(
    db: AsyncSession, grade_id: UUID, for_update: bool = False
) -> ExamGrade | None:
    statement = select(ExamGrade).where(ExamGrade.id == grade_id)
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    return result.scalar_one_or_none()


async def get_grade_by_omr_marking(
    db: AsyncSession, omr_marking_id: UUID
) -> ExamGrade | None:
    result = await db.execute(
        select(ExamGrade).where(ExamGrade.omr_marking_id == omr_marking_id)
    )
    return result.scalar_one_or_none()


async def list_grades_by_answer_key(
    db: AsyncSession, exam_answer_key_id: UUID
) -> list[ExamGrade]:
    result = await db.execute(
        select(ExamGrade)
        .where(ExamGrade.exam_answer_key_id == exam_answer_key_id)
        .order_by(ExamGrade.graded_at)
    )
    return list(result.scalars().all())


async def list_grades_by_exam(db: AsyncSession, exam_id: UUID) -> list[ExamGrade]:
    result = await db.execute(
        select(ExamGrade)
        .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamAnswerKey.exam_id == exam_id)
        .order_by(ExamGrade.graded_at)
    )
    return list(result.scalars().all())


async def get_exam_for_grade(db: AsyncSession, exam_answer_key_id: UUID) -> Exam | None:
    result = await db.execute(
        select(Exam)
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .where(ExamAnswerKey.id == exam_answer_key_id)
    )
    return result.scalar_one_or_none()


async def student_has_grade_for_exam(db: AsyncSession, exam_id: UUID, student_id: UUID) -> bool:
    result = await db.execute(
        select(ExamGrade.id)
        .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamAnswerKey.exam_id == exam_id, ExamGrade.student_id == student_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def exam_has_any_grade(db: AsyncSession, exam_id: UUID) -> bool:
    """Whether any submission has been graded for this exam yet.

    Used to freeze answer-key edits once grading has started, since changing
    correct answers after students have already been scored would silently
    desync the key from what was actually graded.
    """
    result = await db.execute(
        select(ExamGrade.id)
        .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamAnswerKey.exam_id == exam_id)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
