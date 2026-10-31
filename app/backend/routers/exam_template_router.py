from uuid import UUID
from fastapi import APIRouter, Depends, status, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from models.user import User
from constants.blueprints import UBCO_100_BLUEPRINT
from dependencies.auth_dep import require_admin_or_prof
from schemas.exam_templates import (
    CreateExamTemplateRequest,
    ExamTemplateResponse,
    ExamTemplateUsageResponse,
    UpdateExamTemplateRequest,
)
from services.exam_templates import (
    create_new_template,
    get_template,
    update_existing_template,
    create_template_from_ubco_blueprint,
    archive_template,
    remove_template,
    get_my_templates,
    get_template_usage,
    restore_template,
)

router = APIRouter(prefix="/api/exam-templates", tags=["Exam Templates"])


@router.post(
    "",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: CreateExamTemplateRequest | None = None,
    blueprint: str | None = None,
    version: int | None = None,
    version_from_q1: bool = False,
    n_versions: int | None = Query(default=None, ge=2, le=5),
    name: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    if blueprint == UBCO_100_BLUEPRINT:
        return await create_template_from_ubco_blueprint(
            db,
            current_user.id,
            version=version,
            version_from_q1=version_from_q1,
            n_versions=n_versions,
            name=name,
        )

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Payload body required if no blueprint query is provided.",
        )

    return await create_new_template(db, payload, current_user.id)


@router.get(
    "",
    response_model=list[ExamTemplateResponse],
    status_code=status.HTTP_200_OK,
)
async def list_templates(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await get_my_templates(
        db,
        current_user.id,
        include_archived=include_archived,
    )


@router.get(
    "/me",
    response_model=list[ExamTemplateResponse],
    status_code=status.HTTP_200_OK,
)
async def list_my_templates(
    include_archived: bool = Query(False),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await get_my_templates(
        db,
        current_user.id,
        include_archived=include_archived,
    )


@router.get(
    "/{template_id}",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def get_exam_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await get_template(db, template_id, current_user.id)


@router.get(
    "/{template_id}/usage",
    response_model=ExamTemplateUsageResponse,
    status_code=status.HTTP_200_OK,
)
async def get_exam_template_usage(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await get_template_usage(db, template_id, current_user.id)


@router.patch(
    "/{template_id}",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def update_template(
    template_id: UUID,
    payload: UpdateExamTemplateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await update_existing_template(db, template_id, payload, current_user.id)


@router.post(
    "/{template_id}/archive",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def archive_exam_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await archive_template(db, template_id, current_user.id)


@router.post(
    "/{template_id}/restore",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def restore_exam_template(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await restore_template(db, template_id, current_user.id)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    await remove_template(
        db=db,
        template_id=template_id,
        requesting_user_id=current_user.id,
        force=force,
    )
