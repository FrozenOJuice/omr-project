from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession

from db.session import get_db
from dependencies.auth_dep import require_admin_or_prof, require_staff
from errors.exceptions import NotFoundError
from models.user import User
from repositories.exam_templates import get_exam_template_by_id
from schemas.exam_answer_keys import (
    CreateExamAnswerKeyRequest,
    ExamAnswerKeyResponse,
    ExtractAnswerKeyScanBatchResponse,
    UpdateExamAnswerKeyRequest,
)
from services.answer_key_scan_extraction import (
    MAX_ANSWER_KEY_SCAN_BYTES,
    AnswerKeyScanUpload,
    extract_answer_key_scan,
)
from services.exam_answer_keys import (
    create_new_answer_key,
    get_answer_key,
    get_answer_keys_for_exam,
    update_existing_answer_key,
    remove_answer_key,
)
from services.exam_generator import _build_answer_key_csv, _build_answer_key_json

router = APIRouter(prefix="/api", tags=["Exam Answer Keys"])


@router.post(
    "/exams/{exam_id}/answer-keys",
    response_model=ExamAnswerKeyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_answer_key(
    exam_id: UUID,
    payload: CreateExamAnswerKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await create_new_answer_key(db, exam_id, payload, current_user.id)


@router.post(
    "/exams/{exam_id}/answer-keys/extract-scan",
    response_model=ExtractAnswerKeyScanBatchResponse,
    status_code=status.HTTP_200_OK,
)
async def extract_answer_key_from_scan(
    exam_id: UUID,
    question_count: int = Form(..., ge=1, le=200),
    files: list[UploadFile] = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    uploads: list[AnswerKeyScanUpload] = []
    for file in files:
        pdf_bytes = await file.read(MAX_ANSWER_KEY_SCAN_BYTES + 1)
        if len(pdf_bytes) > MAX_ANSWER_KEY_SCAN_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{file.filename or 'The uploaded PDF'} exceeds the 10 MB limit",
            )
        uploads.append(
            AnswerKeyScanUpload(
                filename=file.filename,
                content_type=file.content_type,
                pdf_bytes=pdf_bytes,
            )
        )

    return await extract_answer_key_scan(
        db,
        exam_id,
        current_user.id,
        files=uploads,
        question_count=question_count,
    )


@router.get(
    "/exams/{exam_id}/answer-keys",
    response_model=list[ExamAnswerKeyResponse],
    status_code=status.HTTP_200_OK,
)
async def list_answer_keys(
    exam_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return await get_answer_keys_for_exam(db, exam_id)


@router.get(
    "/answer-keys/{answer_key_id}",
    response_model=ExamAnswerKeyResponse,
    status_code=status.HTTP_200_OK,
)
async def get_answer_key_by_id(
    answer_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    return await get_answer_key(db, answer_key_id)


@router.patch(
    "/answer-keys/{answer_key_id}",
    response_model=ExamAnswerKeyResponse,
    status_code=status.HTTP_200_OK,
)
async def update_answer_key(
    answer_key_id: UUID,
    payload: UpdateExamAnswerKeyRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    return await update_existing_answer_key(db, answer_key_id, payload, current_user.id)


@router.delete("/answer-keys/{answer_key_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_answer_key(
    answer_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_prof),
):
    await remove_answer_key(db, answer_key_id, current_user.id)


@router.get(
    "/answer-keys/{answer_key_id}/download",
    status_code=status.HTTP_200_OK,
)
async def download_answer_key_json(
    answer_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    key = await get_answer_key(db, answer_key_id)
    template = await get_exam_template_by_id(db, key.exam_template_id)
    if not template:
        raise NotFoundError("Associated template not found", code="template_not_found")
    version_label = key.exam_version or "default"
    return JSONResponse(
        content=_build_answer_key_json(template, key),
        headers={"Content-Disposition": f"attachment; filename=answer_key_{version_label}.json"},
    )


@router.get(
    "/answer-keys/{answer_key_id}/download.csv",
    status_code=status.HTTP_200_OK,
)
async def download_answer_key_csv(
    answer_key_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_staff),
):
    key = await get_answer_key(db, answer_key_id)
    template = await get_exam_template_by_id(db, key.exam_template_id)
    if not template:
        raise NotFoundError("Associated template not found", code="template_not_found")
    version_label = key.exam_version or "default"
    return PlainTextResponse(
        content=_build_answer_key_csv(template, key),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=answer_key_{version_label}.csv"},
    )
