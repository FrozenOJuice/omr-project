import uuid
from typing import Optional

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.review_request import ReviewRequest
from models.scan import Scan


async def get_exam_by_id(
    db: AsyncSession, exam_id: uuid.UUID, *, for_update: bool = False
) -> Optional[Exam]:
    query = select(Exam).where(Exam.id == exam_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_graded_exam_ids_for_student(
    db: AsyncSession,
    exam_ids: list[uuid.UUID],
    student_id: uuid.UUID,
) -> set[uuid.UUID]:
    if not exam_ids:
        return set()
    result = await db.execute(
        select(Exam.id)
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(
            Exam.id.in_(exam_ids),
            ExamGrade.student_id == student_id,
            ExamGrade.status == "graded",
        )
        .distinct()
    )
    return set(result.scalars().all())



async def get_scan_counts_by_exam(db: AsyncSession, exam_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(Scan.exam_id, func.count(Scan.id))
        .where(Scan.exam_id.in_(exam_ids))
        .group_by(Scan.exam_id)
    )
    return dict(result.all())


async def get_failed_counts_by_exam(db: AsyncSession, exam_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(Scan.exam_id, func.count(Scan.id))
        .where(Scan.exam_id.in_(exam_ids), Scan.status == "failed")
        .group_by(Scan.exam_id)
    )
    return dict(result.all())


async def get_graded_counts_by_exam(db: AsyncSession, exam_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(Exam.id, func.count(ExamGrade.id))
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(Exam.id.in_(exam_ids))
        .group_by(Exam.id)
    )
    return dict(result.all())


async def get_answer_key_counts_by_exam(db: AsyncSession, exam_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(ExamAnswerKey.exam_id, func.count(ExamAnswerKey.id))
        .where(ExamAnswerKey.exam_id.in_(exam_ids))
        .group_by(ExamAnswerKey.exam_id)
    )
    return dict(result.all())


async def get_pending_review_request_counts_by_exam(
    db: AsyncSession, exam_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(Exam.id, func.count(ReviewRequest.id))
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .join(ReviewRequest, ReviewRequest.exam_grade_id == ExamGrade.id)
        .where(
            Exam.id.in_(exam_ids),
            Exam.released.is_(True),
            ReviewRequest.status == "pending",
        )
        .group_by(Exam.id)
    )
    return dict(result.all())


# A grade "has ambiguous marks" when any of its question_results flagged the
# student's bubbling itself as unclear (see grading_service.py's _is_ambiguous)
# -- distinct from status="needs_review", which flags identity/version
# mismatches instead.
_AMBIGUOUS_QUESTION_RESULT = text(
    "jsonb_path_exists(exam_grades.question_results, '$.*.ambiguous ? (@ == true)')"
)


async def get_ambiguous_grade_counts_by_exam(
    db: AsyncSession, exam_ids: list[uuid.UUID]
) -> dict[uuid.UUID, int]:
    if not exam_ids:
        return {}
    result = await db.execute(
        select(Exam.id, func.count(ExamGrade.id))
        .join(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .join(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(Exam.id.in_(exam_ids), _AMBIGUOUS_QUESTION_RESULT)
        .group_by(Exam.id)
    )
    return dict(result.all())


async def get_exams_by_course(db: AsyncSession, course_id: uuid.UUID) -> list[Exam]:
    result = await db.execute(select(Exam).where(Exam.course_id == course_id))
    return list(result.scalars().all())


async def get_exams_by_creator(db: AsyncSession, user_id: uuid.UUID) -> list[Exam]:
    result = await db.execute(select(Exam).where(Exam.created_by == user_id))
    return list(result.scalars().all())


async def create_exam(
    db: AsyncSession,
    name: str,
    description: Optional[str],
    start_time,
    end_time,
    role: str,
    course_id: uuid.UUID,
    created_by: uuid.UUID,
    exam_template_id: uuid.UUID,
) -> Exam:
    exam = Exam(
        name=name,
        description=description,
        start_time=start_time,
        end_time=end_time,
        role=role,
        course_id=course_id,
        created_by=created_by,
        exam_template_id=exam_template_id,
    )
    db.add(exam)
    await db.flush()
    return exam


async def update_exam(
    db: AsyncSession,
    exam: Exam,
    name: Optional[str] = None,
    description: Optional[str] = None,
    start_time=None,
    end_time=None,
    role: Optional[str] = None,
    course_id: Optional[uuid.UUID] = None,
    exam_template_id: Optional[uuid.UUID] = None,
    update_schedule: bool = False,
) -> Exam:
    if name is not None:
        exam.name = name
    if description is not None:
        exam.description = description
    if update_schedule:
        exam.start_time = start_time
        exam.end_time = end_time
    if role is not None:
        exam.role = role
    if course_id is not None:
        exam.course_id = course_id
    if exam_template_id is not None:
        exam.exam_template_id = exam_template_id
    await db.flush()
    return exam


async def delete_exam(db: AsyncSession, exam: Exam) -> None:
    await db.delete(exam)
    await db.flush()
