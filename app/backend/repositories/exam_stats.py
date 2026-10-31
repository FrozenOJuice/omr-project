from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.review_request import ReviewRequest
from models.scan import Scan


async def list_exam_grade_rows(db: AsyncSession, exam_id: UUID):
    result = await db.execute(
        select(
            ExamGrade.total_score,
            ExamGrade.max_score,
            ExamGrade.question_results,
            ExamAnswerKey.exam_version,
        )
        .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamAnswerKey.exam_id == exam_id)
    )
    return result.all()


async def count_scans_for_exam(db: AsyncSession, exam_id: UUID) -> int:
    result = await db.execute(select(func.count()).select_from(Scan).where(Scan.exam_id == exam_id))
    return result.scalar_one()


async def count_students_for_exam_course(db: AsyncSession, exam_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(Enrolment)
        .join(Exam, Exam.course_id == Enrolment.course_id)
        .where(Exam.id == exam_id, Enrolment.role == "student")
    )
    return result.scalar_one()


async def count_pending_review_requests_for_exam(db: AsyncSession, exam_id: UUID) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ReviewRequest)
        .join(ExamGrade, ReviewRequest.exam_grade_id == ExamGrade.id)
        .join(ExamAnswerKey, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(ExamAnswerKey.exam_id == exam_id, ReviewRequest.status == "pending")
    )
    return result.scalar_one()
