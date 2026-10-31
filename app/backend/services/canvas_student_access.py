from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.tokens import decode_canvas_student_access_token
from errors.exceptions import UnauthorizedError
from models.exam_grade import ExamGrade
from models.user import AccountStatus, User, UserRole
from repositories import course_roster_entries
from repositories.exam_grades import get_exam_for_grade, get_grade_by_id
from repositories.users import get_by_id as get_user_by_id


@dataclass(frozen=True)
class CanvasStudentResultAccess:
    grade: ExamGrade
    student: User


async def authorize(
    db: AsyncSession,
    access_token: str,
) -> CanvasStudentResultAccess:
    token = access_token.strip()
    if not token or len(token) > 4096:
        raise _invalid_access()

    try:
        payload = decode_canvas_student_access_token(token)
        student_id = UUID(payload["sub"])
        grade_id = UUID(payload["exam_grade_id"])
        canvas_user_id = payload["canvas_user_id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise _invalid_access() from exc

    grade = await get_grade_by_id(db, grade_id)
    if (
        grade is None
        or grade.status != "graded"
        or grade.student_id != student_id
    ):
        raise _invalid_access()

    exam = await get_exam_for_grade(db, grade.exam_answer_key_id)
    if exam is None or not exam.released:
        raise _invalid_access()

    student = await get_user_by_id(db, student_id)
    if (
        student is None
        or student.role_enum != UserRole.STUDENT
        or student.status_enum != AccountStatus.ACTIVE
    ):
        raise _invalid_access()

    mapping = await course_roster_entries.get_active_canvas_mapping(
        db,
        exam.course_id,
        student.id,
        canvas_user_id,
    )
    if mapping is None:
        raise _invalid_access()

    return CanvasStudentResultAccess(grade=grade, student=student)


def _invalid_access() -> UnauthorizedError:
    return UnauthorizedError(
        "This Canvas result link is invalid or has expired",
        code="invalid_canvas_student_access",
    )
