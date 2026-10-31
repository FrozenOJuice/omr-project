import re
from uuid import UUID

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from fastapi.responses import Response

from dependencies.auth_dep import get_current_user
from dependencies.storage_dep import get_storage_repo
from db.session import get_db
from models.user import User
from repositories.storage import StorageRepository
from schemas.exam import (
    CreateExamRequest,
    ExamReleaseAuditEntryResponse,
    ExamResponse,
    UpdateExamRequest,
)
from schemas.exam_stats import ExamScoreDistributionResponse, ExamStatsResponse
from services.exam_stats import get_exam_score_distribution, get_exam_stats
from services import exam
from services.exam_generator import generate_exam_pdf, get_exam_pdf_bytes
from dependencies.auth_dep import require_admin_or_prof, require_staff

router = APIRouter(prefix="/api/exams", tags=["exams"])


@router.post("", response_model=ExamResponse, status_code=status.HTTP_201_CREATED)
async def create_exam(
    request: CreateExamRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await exam.create_new_exam(
        db,
        request.name,
        request.description,
        request.start_time,
        request.end_time,
        request.role,
        request.course_id,
        request.exam_template_id,
        user,
        request.canvas_assignment_id,
    )


@router.get("/course/{course_id}", response_model=list[ExamResponse])
async def list_exams_by_course(
    course_id: UUID,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await exam.list_exams_by_course(db, course_id, user)


@router.get("/my", response_model=list[ExamResponse])
async def list_my_exams(
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await exam.list_exams_by_creator(db, user.id)


@router.get("/{exam_id}", response_model=ExamResponse)
async def get_exam(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await exam.get_exam(db, exam_id)


@router.patch("/{exam_id}", response_model=ExamResponse)
async def update_exam(
    exam_id: UUID,
    request: UpdateExamRequest,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    schedule_fields = {"start_time", "end_time"}
    provided_schedule_fields = request.model_fields_set & schedule_fields
    if provided_schedule_fields and provided_schedule_fields != schedule_fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="start_time and end_time must both be provided or both omitted.",
        )

    return await exam.update_existing_exam(
        db,
        exam_id,
        user,
        request.name,
        request.description,
        request.start_time,
        request.end_time,
        request.role,
        request.course_id,
        request.exam_template_id,
        request.delete_answer_keys,
        schedule_provided=bool(provided_schedule_fields),
    )


@router.delete("/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_exam(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    await exam.delete_existing_exam(db, exam_id, user)

@router.get("/{exam_id}/stats", response_model=ExamStatsResponse)
async def exam_stats(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await get_exam_stats(db, exam_id, user.id)


# Staff get the full exam_stats above; a student gets just the five-number
# summary here, once their results are released, with no per-student or
# per-question detail.
@router.get("/{exam_id}/score-distribution", response_model=ExamScoreDistributionResponse)
async def exam_score_distribution(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_exam_score_distribution(db, exam_id, user)


@router.get("/{exam_id}/export")
async def export_exam_results(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    filename, csv_text = await exam.export_exam_results_csv(db, exam_id, user)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{exam_id}/release", response_model=ExamResponse)
async def release_exam(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await exam.release_exam(db, exam_id, user)


@router.post("/{exam_id}/close", response_model=ExamResponse)
async def close_exam(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
):
    return await exam.close_exam(db, exam_id, user)


@router.get("/{exam_id}/release-history", response_model=list[ExamReleaseAuditEntryResponse])
async def release_history(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_staff),
):
    return await exam.get_release_history(db, exam_id, user)


@router.post("/{exam_id}/generate-pdf", response_model=ExamResponse)
async def generate_exam_pdf_route(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
    storage_repo: StorageRepository = Depends(get_storage_repo),
):
    return await generate_exam_pdf(db, storage_repo, exam_id, user)


@router.get("/{exam_id}/download-pdf")
async def download_exam_pdf_route(
    exam_id: UUID,
    db=Depends(get_db),
    user: User = Depends(require_admin_or_prof),
    storage_repo: StorageRepository = Depends(get_storage_repo),
):
    pdf_bytes, exam_name = await get_exam_pdf_bytes(db, storage_repo, exam_id, user)
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", exam_name) or "exam"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'},
    )
