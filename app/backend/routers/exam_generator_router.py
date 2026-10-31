import re
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import require_staff
from dependencies.storage_dep import get_storage_repo
from errors.exceptions import BadRequestError, ForbiddenError, NotFoundError
from models.user import User
from repositories.exam_templates import get_exam_template_by_id
from repositories.storage import StorageRepository
from schemas.exam_templates import ExamTemplateResponse
from services.exam_generator import finalize_exam_template, generate_template_pdf, render_template_preview_pdf

router = APIRouter(prefix="/api/exam-templates", tags=["Exam Generation"])


@router.post(
    "/{template_id}/generate",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def generate_exam(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
    storage_repo: StorageRepository = Depends(get_storage_repo),
):
    return await generate_template_pdf(db, storage_repo, template_id, current_user.id)


@router.post(
    "/{template_id}/finalize",
    response_model=ExamTemplateResponse,
    status_code=status.HTTP_200_OK,
)
async def finalize_exam(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
    storage_repo: StorageRepository = Depends(get_storage_repo),
):
    return await finalize_exam_template(db, storage_repo, template_id, current_user.id)


@router.get(
    "/{template_id}/download-pdf",
    status_code=status.HTTP_200_OK,
)
async def download_exam_pdf(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
    storage_repo: StorageRepository = Depends(get_storage_repo),
):
    template = await get_exam_template_by_id(db, template_id)
    if not template:
        raise NotFoundError("Exam template not found", code="template_not_found")
    if template.created_by != current_user.id:
        raise ForbiddenError("Not authorised to download this exam template", code="forbidden")
    if not template.generated_pdf_path:
        raise BadRequestError(
            "PDF has not been generated for this template yet",
            code="pdf_not_generated",
        )

    # Stream the PDF through the backend rather than redirecting to a presigned
    # Garage URL: Garage is only reachable inside the Docker network (prod maps
    # no host port for it), and a cross-origin redirect would also need bucket
    # CORS rules before the browser let the frontend read the response.
    pdf_bytes = storage_repo.download_file(template.generated_pdf_path)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", template.name) or "bubble_sheet"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )


@router.get(
    "/{template_id}/preview-pdf",
    status_code=status.HTTP_200_OK,
)
async def preview_exam_pdf(
    template_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    pdf_bytes = await render_template_preview_pdf(db, template_id, current_user.id)
    return Response(content=pdf_bytes, media_type="application/pdf")
