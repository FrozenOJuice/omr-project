from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from db.session import get_db
from dependencies.auth_dep import get_current_user, require_admin_or_prof
from models.user import Institution, User
from schemas.academic_term import (
    AcademicTermListItemResponse,
    AcademicTermResponse,
    CreateAcademicTermRequest,
    UpdateAcademicTermRequest,
)
from services import academic_terms


router = APIRouter(prefix="/api/academic-terms", tags=["academic terms"])


@router.get("", response_model=list[AcademicTermListItemResponse])
async def list_academic_terms(
    institution: Institution | None = Query(default=None),
    include_archived: bool = Query(default=False),
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await academic_terms.list_terms(
        db,
        user,
        institution=institution,
        include_archived=include_archived,
    )


@router.post("", response_model=AcademicTermResponse, status_code=status.HTTP_201_CREATED)
async def create_academic_term(
    request: CreateAcademicTermRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await academic_terms.create_term(db, user, request)


@router.patch("/{term_id}", response_model=AcademicTermResponse)
async def update_academic_term(
    term_id: UUID,
    request: UpdateAcademicTermRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await academic_terms.update_term(db, term_id, user, request)


@router.delete("/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_academic_term(
    term_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await academic_terms.delete_term(db, term_id, user)
