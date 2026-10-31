import io
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import get_current_user, require_staff
from models.user import User
from schemas.exam_grades import (
    ExamGradeResponse,
    GradeAuditEntryResponse,
    IdentityAnnotations,
    QuestionAnnotation,
    UpdateExamGradeRequest,
    VersionAnnotation,
)
from services.grading_service import (
    apply_grade_corrections,
    build_grade_response,
    get_grade_for_marking_view,
    get_grade_history_view,
    get_grade_identity_view,
    get_grade_page_annotations_view,
    get_grade_page_identity_view,
    get_grade_page_image_bytes,
    get_grade_page_version_view,
    get_grade_question_snippet_bytes,
    get_grade_view,
    grade_marking,
    list_exam_grades_view,
)

router = APIRouter(prefix="/api", tags=["Grading"])


@router.post(
    "/markings/{marking_id}/grade",
    response_model=ExamGradeResponse,
    status_code=status.HTTP_200_OK,
)
async def grade_exam_marking(
    marking_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return await build_grade_response(db, await grade_marking(db, marking_id))


@router.get(
    "/markings/{marking_id}/grade",
    response_model=ExamGradeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_grade_for_marking(
    marking_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return await get_grade_for_marking_view(db, marking_id)


@router.get(
    "/grades/{grade_id}",
    response_model=ExamGradeResponse,
    status_code=status.HTTP_200_OK,
)
async def get_grade(
    grade_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_grade_view(db, grade_id, current_user)


@router.get(
    "/exams/{exam_id}/grades",
    response_model=list[ExamGradeResponse],
    status_code=status.HTTP_200_OK,
)
async def list_exam_grades(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await list_exam_grades_view(db, exam_id, current_user)


@router.get(
    "/grades/{grade_id}/history",
    response_model=list[GradeAuditEntryResponse],
    status_code=status.HTTP_200_OK,
)
async def get_grade_history(
    grade_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await get_grade_history_view(db, grade_id, current_user)


@router.patch(
    "/grades/{grade_id}",
    response_model=ExamGradeResponse,
    status_code=status.HTTP_200_OK,
)
async def update_grade(
    grade_id: UUID,
    payload: UpdateExamGradeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    grade = await apply_grade_corrections(db, grade_id, payload, current_user)
    return await build_grade_response(db, grade)


@router.get(
    "/grades/{grade_id}/questions/{question_number}/snippet",
    status_code=status.HTTP_200_OK,
)
async def get_grade_question_snippet(
    grade_id: UUID,
    question_number: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    snippet = await get_grade_question_snippet_bytes(db, grade_id, question_number, current_user)
    return StreamingResponse(io.BytesIO(snippet), media_type="image/jpeg")


@router.get(
    "/grades/{grade_id}/pages/{page_index}/annotations",
    response_model=list[QuestionAnnotation],
    status_code=status.HTTP_200_OK,
)
async def get_grade_page_annotations(
    grade_id: UUID,
    page_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-question coordinates and grade for every answer question on one
    page of a grade's scan.

    This is what a frontend overlays on that page's image, served by
    GET /grades/{grade_id}/pages/{page_index}/image below.
    """
    return await get_grade_page_annotations_view(db, grade_id, page_index, current_user)


@router.get(
    "/grades/{grade_id}/identity",
    response_model=IdentityAnnotations,
    status_code=status.HTTP_200_OK,
)
async def get_grade_identity(
    grade_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The grade's name/student-ID bubble fields and decoded values,
    regardless of which page they're on. Used for a persistent "identify
    student" card, including which page to jump to.
    """
    return await get_grade_identity_view(db, grade_id, current_user)


@router.get(
    "/grades/{grade_id}/pages/{page_index}/identity",
    response_model=IdentityAnnotations,
    status_code=status.HTTP_200_OK,
)
async def get_grade_page_identity(
    grade_id: UUID,
    page_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Per-character name/student-ID bubble coordinates for one page of a
    grade's scan, plus what OMR decoded them as. Empty (with blank decoded
    strings) on any page without name/ID fields, e.g. a plain question page.
    """
    return await get_grade_page_identity_view(db, grade_id, page_index, current_user)


@router.get(
    "/grades/{grade_id}/pages/{page_index}/version",
    response_model=VersionAnnotation,
    status_code=status.HTTP_200_OK,
)
async def get_grade_page_version(
    grade_id: UUID,
    page_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """The version-selector bubble on one page of a grade's scan, if this
    template has one and it's on this page, plus what OMR decoded it as.
    Read-only: see VersionAnnotation for why.
    """
    return await get_grade_page_version_view(db, grade_id, page_index, current_user)


@router.get(
    "/grades/{grade_id}/pages/{page_index}/image",
    status_code=status.HTTP_200_OK,
)
async def get_grade_page_image(
    grade_id: UUID,
    page_index: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    image = await get_grade_page_image_bytes(db, grade_id, page_index, current_user)
    return StreamingResponse(io.BytesIO(image), media_type="image/jpeg")
