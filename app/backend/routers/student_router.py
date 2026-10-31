from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import require_student
from models.user import User
from services.course import CourseInviteService

router = APIRouter(prefix="/api/students", tags=["students"])

@router.post("/join/{invite_link}", status_code=status.HTTP_201_CREATED)
async def join_course_via_link(
    invite_link: str, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_student),
):
    await CourseInviteService.enroll_current_student_via_link(db, invite_link, current_user)
    return {"message": "Successfully joined course."}
