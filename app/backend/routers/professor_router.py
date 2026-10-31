import uuid
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from schemas.course_schema import CourseInviteCodeResponse
from services.course import CourseInviteService
from dependencies.auth_dep import require_admin_or_prof
from models.user import User

router = APIRouter(prefix="/api/courses", tags=["courses"])

@router.post("/{course_id}/regenerate-link", response_model=CourseInviteCodeResponse)
async def request_new_course_link(
    course_id: uuid.UUID, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof)
):
    updated_course =  await CourseInviteService.regenerate_invite_link(
        db=db, 
        course_id=course_id, 
        current_user=current_user
    )
    return {
        "course_id": updated_course.id,
        "invite_link": updated_course.invite_link,
        "invite_link_expires_at": updated_course.invite_link_expires_at,
    }
