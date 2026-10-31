from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade


async def list_course_exam_grade_rows(
    db: AsyncSession,
    course_id: UUID,
) -> list[tuple[UUID, str, float | None, float | None]]:
    result = await db.execute(
        select(
            Exam.id,
            Exam.name,
            ExamGrade.total_score,
            ExamGrade.max_score,
        )
        .select_from(Exam)
        .outerjoin(ExamAnswerKey, ExamAnswerKey.exam_id == Exam.id)
        .outerjoin(ExamGrade, ExamGrade.exam_answer_key_id == ExamAnswerKey.id)
        .where(Exam.course_id == course_id)
        .order_by(Exam.start_time.asc().nullslast(), Exam.name)
    )
    return list(result.all())
