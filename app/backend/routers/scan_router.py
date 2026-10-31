import io
from uuid import UUID
from fastapi import APIRouter, Depends, status, File, UploadFile, Form, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse

from dependencies.auth_dep import require_admin_or_prof, require_staff
from db.session import get_db
from models.user import User
from schemas.scan_schema import ScanResponse, InitiateMultipartRequest, CompleteMultipartRequest, InitiateMultipartResponse, ScanJobStatusResponse
from services.scans import ScanService
from services.scan_processing import run_pdf_batch_pipeline
from repositories.storage import StorageRepository
from dependencies.storage_dep import get_storage_repo 

router = APIRouter(prefix="/api/scans", tags=["scans"])


@router.get("/exam/{exam_id}", response_model=list[ScanResponse])
async def list_scans_by_exam(
    exam_id: UUID,
    db = Depends(get_db),
    user: User = Depends(require_staff),
):
    return await ScanService.get_scans_for_exam(db, exam_id)


@router.delete("/exam/{exam_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_all_scans_for_exam(
    exam_id: UUID,
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_admin_or_prof),
):
    await ScanService.delete_scans_for_exam(db=db, storage_repo=storage_repo, exam_id=exam_id)


@router.get("/template/{exam_template_id}", response_model=list[ScanResponse])
async def list_scans_by_template(
    exam_template_id: UUID,
    db = Depends(get_db),
    user: User = Depends(require_staff),
):
    return await ScanService.get_scans_for_template(db, exam_template_id)


@router.get("/{scan_id}/download")
async def download_scan_file(
    scan_id: UUID,
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_staff),
):
    file_bytes, original_filename = await ScanService.download_scan_file(
        db=db, storage_repo=storage_repo, scan_id=scan_id
    )
    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{original_filename}"'}
    )


@router.get("/{scan_id}/job-status", response_model=ScanJobStatusResponse)
async def get_scan_job_status(
    scan_id: UUID,
    db = Depends(get_db),
    user: User = Depends(require_staff),
):
    return await ScanService.get_job_status(db, scan_id)


@router.delete("/{scan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scan(
    scan_id: UUID,
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_admin_or_prof),
):
    await ScanService.delete_scan(db=db, storage_repo=storage_repo, scan_id=scan_id)


"""Chunked upload routers"""
@router.post("/initiate", response_model=InitiateMultipartResponse)
async def initiate_upload_session(
    request: InitiateMultipartRequest,
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_staff)
):
    if request.total_chunks > 39:
        raise HTTPException(status_code=400, detail="File too large. Maximum PDF size is 195MB.")
        
    session_info = await ScanService.prepare_multipart_upload(
        db=db,
        storage_repo=storage_repo,
        exam_id=request.exam_id,
        exam_template_id=request.exam_template_id,
        filename=request.filename,
        total_chunks=request.total_chunks
    )
    return session_info


@router.post("/pdf", response_model=list[ScanResponse], status_code=status.HTTP_201_CREATED)
async def upload_pdf_batch(
    background_tasks: BackgroundTasks,
    exam_id: UUID = Form(...),
    exam_template_id: UUID = Form(...),
    file: UploadFile = File(...),
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_staff),
):
    """Accept a small PDF through the backend without splitting it."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported file extension format. Please upload pdf",
        )

    max_file_size = 200_000_000
    contents = await file.read(max_file_size + 1)
    if len(contents) > max_file_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File size exceeds maximum threshold.",
        )

    scan_records = await ScanService.upload_pdf_batch(
        db=db,
        storage_repo=storage_repo,
        exam_id=exam_id,
        exam_template_id=exam_template_id,
        uploader_user_id=user.id,
        contents=contents,
        filename=file.filename,
    )
    seed_scan = scan_records[0]
    background_tasks.add_task(
        run_pdf_batch_pipeline,
        storage_path=seed_scan.path,
        seed_scan_id=seed_scan.id,
        storage_repo=storage_repo,
    )
    return scan_records


@router.post("/finalize-pdf", response_model=list[ScanResponse], status_code=status.HTTP_201_CREATED)
async def finalize_pdf_batch_upload_session(
    background_tasks: BackgroundTasks,
    request: CompleteMultipartRequest,
    db = Depends(get_db),
    storage_repo: StorageRepository = Depends(get_storage_repo),
    user: User = Depends(require_staff),
):
    """Finalize a batch PDF and let OMR split/preprocess the complete file."""
    scan_records = await ScanService.finalize_pdf_batch_upload(
        db=db,
        storage_repo=storage_repo,
        exam_id=request.exam_id,
        exam_template_id=request.exam_template_id,
        uploader_user_id=user.id,
        upload_id=request.upload_id,
        storage_path=request.storage_path,
        parts=[part.model_dump() for part in request.parts],
    )

    seed_scan = scan_records[0]
    background_tasks.add_task(
        run_pdf_batch_pipeline,
        storage_path=seed_scan.path,
        seed_scan_id=seed_scan.id,
        storage_repo=storage_repo,
    )
    return scan_records
