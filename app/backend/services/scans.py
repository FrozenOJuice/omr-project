import uuid
from typing import Optional, Sequence, Dict, Any, List
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from repositories.scans import ScanRepository
from repositories.storage import StorageRepository
from repositories.exam_answer_keys import list_answer_keys_by_exam
from repositories.exam_templates import get_exam_template_by_id
from repositories.omr_templates import get_omr_template_by_id
from models.scan import Scan
from services.course_lifecycle import ensure_exam_course_writable, ensure_scan_course_writable
from services.answer_key_status import incomplete_answer_key_versions
from integrations.omr_client import OMRClientError, OMRJobNotFoundError, get_job_status as _omr_get_job_status
from schemas.scan_schema import ScanJobStatusResponse


class ScanService:
    @staticmethod
    async def get_scans_for_template(db: AsyncSession, exam_template_id: uuid.UUID) -> Sequence[Scan]:
        return await ScanRepository.get_by_template(db, exam_template_id)

    @staticmethod
    async def download_scan_file(
        db: AsyncSession,
        storage_repo: StorageRepository,
        scan_id: uuid.UUID
    ) -> tuple[bytes, str]:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan record not found.")
        await ensure_scan_course_writable(db, scan_id)

        try:
            file_bytes = storage_repo.download_file(scan.path)

            original_filename = scan.path.split("_", 1)[-1]
            return file_bytes, original_filename
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="File not found in Garage"
            )

    @staticmethod
    async def _delete_scan_record(db: AsyncSession, storage_repo: StorageRepository, scan: Scan) -> None:
        """Deletes one scan's DB row and, unless another scan row still
        references the same storage object, its underlying file. Batch-PDF
        scans intentionally share one original upload object, so this must be
        checked per-scan rather than assumed. Does not commit -- callers
        batch their own commit so a bulk delete is one transaction.
        """
        path_is_shared = await ScanRepository.count_others_with_path(db, scan.path, scan.id)
        if not path_is_shared:
            storage_repo.delete_file(scan.path)
        await ScanRepository.delete(db, scan)

    @staticmethod
    async def delete_scan(
        db: AsyncSession,
        storage_repo: StorageRepository,
        scan_id: uuid.UUID
    ) -> None:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan record not found.")

        await ScanService._delete_scan_record(db, storage_repo, scan)
        await db.commit()

    @staticmethod
    async def delete_scans_for_exam(
        db: AsyncSession,
        storage_repo: StorageRepository,
        exam_id: uuid.UUID,
    ) -> None:
        """Deletes every scan uploaded for an exam in one transaction, so a
        professor can clear out a bad batch without deleting scans one at a
        time. A no-op if the exam has no scans.
        """
        scans = await ScanRepository.get_by_exam(db, exam_id)
        for scan in scans:
            await ScanService._delete_scan_record(db, storage_repo, scan)
        await db.commit()

    @staticmethod
    async def get_scans_for_exam(db: AsyncSession, exam_id: uuid.UUID) -> Sequence[Scan]:
        return await ScanRepository.get_by_exam(db, exam_id)

    @staticmethod
    async def get_job_status(db: AsyncSession, scan_id: uuid.UUID) -> ScanJobStatusResponse:
        """Proxy an in-flight batch upload's live progress, keyed off the seed
        scan's stored job id. 404s once there's no active job, whether
        because none was ever submitted or OMR has since expired it from its
        own job registry.

        OMR's own job finishing only means preprocessing is done -- grading
        the resulting batch (scan_processing._trigger_marking) still has to
        run afterward, and can take a while for a large batch. Once OMR
        reports finished, this keeps reporting `finished=False` (with
        progress recomputed from how many of the batch's scans have actually
        been graded) until every scan sharing this batch id has left
        'pending', so the frontend's progress indicator doesn't disappear
        mid-pipeline.
        """
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan or not scan.omr_job_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active OMR job for this scan.")

        try:
            job_status = await _omr_get_job_status(scan.omr_job_id)
        except OMRJobNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active OMR job for this scan.")
        except OMRClientError as exc:
            raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

        omr_finished = job_status.finished_timestamp is not None
        if omr_finished and scan.batch_id is not None:
            total, pending = await ScanRepository.count_batch_progress(db, scan.batch_id)
            if pending > 0:
                graded_progress = (total - pending) / total if total else 0
                return ScanJobStatusResponse(
                    progress=graded_progress,
                    finished=False,
                    success=job_status.success,
                    notes="Grading in progress",
                )

        return ScanJobStatusResponse(
            progress=job_status.progress,
            finished=omr_finished,
            success=job_status.success,
            notes=job_status.notes,
        )

    @staticmethod
    async def _resolve_group_page_count(
        db: AsyncSession,
        exam_id: uuid.UUID,
        exam_template_id: uuid.UUID,
    ) -> int:
        """The number of pages one exam instance spans for this template, i.e.
        the group size a batch upload must be split into.

        Student scan uploads additionally require a complete answer key for
        every exam version. Answer-key extraction uses the OMR client directly
        and therefore does not pass through this student-upload guard.
        """
        exam_template = await get_exam_template_by_id(db, exam_template_id)
        if not exam_template or not exam_template.omr_template_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exam template has no OMR template configured yet — finalize the template before uploading scans.",
            )

        answer_keys = await list_answer_keys_by_exam(db, exam_id)
        incomplete_versions = incomplete_answer_key_versions(
            exam_template.n_versions, answer_keys
        )
        if incomplete_versions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Complete every answer-key version before uploading student scans "
                    f"(incomplete: {', '.join(incomplete_versions)})."
                ),
            )

        omr_template = await get_omr_template_by_id(db, exam_template.omr_template_id)
        if not omr_template:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Exam template's OMR template could not be found.",
            )

        return omr_template.page_count

    @staticmethod
    async def upload_pdf_batch(
        db: AsyncSession,
        storage_repo: StorageRepository,
        exam_id: uuid.UUID,
        exam_template_id: uuid.UUID,
        uploader_user_id: uuid.UUID,
        contents: bytes,
        filename: Optional[str] = None,
    ) -> List[Scan]:
        """Store a small batch PDF intact and create its pending placeholder."""
        await ensure_exam_course_writable(db, exam_id)
        page_count = await ScanService._resolve_group_page_count(
            db, exam_id, exam_template_id
        )
        safe_filename = (filename or "batch.pdf").replace(" ", "_")
        storage_path = (
            f"exams/{exam_id}/{exam_template_id}/"
            f"{uuid.uuid4().hex}_{safe_filename}"
        )

        try:
            storage_repo.upload_file(contents, storage_path)
            scan = await ScanRepository.create(
                db=db,
                exam_id=exam_id,
                exam_template_id=exam_template_id,
                uploader_user_id=uploader_user_id,
                path=storage_path,
                page_count=page_count,
                batch_id=uuid.uuid4(),
                batch_index=1,
            )
            await db.commit()
            return [scan]
        except Exception:
            await db.rollback()
            try:
                storage_repo.delete_file(storage_path)
            except Exception:
                pass
            raise

    # Multipart upload functions
    @staticmethod
    async def prepare_multipart_upload(
        db: AsyncSession,
        storage_repo: StorageRepository,
        exam_id: uuid.UUID,
        exam_template_id: uuid.UUID,
        filename: str,
        total_chunks: int
    ) -> Dict[str, Any]:
        await ensure_exam_course_writable(db, exam_id)
        await ScanService._resolve_group_page_count(db, exam_id, exam_template_id)

        file_uuid = uuid.uuid4().hex
        safe_filename = filename.replace(" ", "_")
        storage_path = f"exams/{exam_id}/{exam_template_id}/{file_uuid}_{safe_filename}"

        try:
            upload_id = storage_repo.initiate_multipart_upload(storage_path)

            urls = []
            for part_num in range(1, total_chunks + 1):
                url = storage_repo.generate_presigned_part_url(storage_path, upload_id, part_num)
                urls.append({"part_number": part_num, "url": url})

            return {"upload_id": upload_id, "storage_path": storage_path, "urls": urls}
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to initialize storage session: {str(e)}"
            )

    @staticmethod
    async def finalize_pdf_batch_upload(
        db: AsyncSession,
        storage_repo: StorageRepository,
        exam_id: uuid.UUID,
        exam_template_id: uuid.UUID,
        uploader_user_id: uuid.UUID,
        upload_id: str,
        storage_path: str,
        parts: List[Dict[str, Any]],
    ) -> List[Scan]:
        """Finalize one stored batch PDF without splitting it in the backend.

        A single pending Scan acts as the batch placeholder. The PDF pipeline
        expands it into one Scan per OMR result after /scan/pdf completes.
        This is additive while the existing split-based finalize path remains
        available for fallback during rollout.
        """
        await ensure_exam_course_writable(db, exam_id)
        page_count = await ScanService._resolve_group_page_count(
            db, exam_id, exam_template_id
        )

        expected_prefix = f"exams/{exam_id}/{exam_template_id}/"
        if not storage_path.startswith(expected_prefix):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Storage path does not belong to this exam and template.",
            )

        try:
            storage_repo.complete_multipart_upload(storage_path, upload_id, parts)
        except Exception as e:
            storage_repo.abort_multipart_upload(storage_path, upload_id)
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Storage stitching failed. Chunks discarded. Error: {str(e)}",
            )

        try:
            scan = await ScanRepository.create(
                db=db,
                exam_id=exam_id,
                exam_template_id=exam_template_id,
                uploader_user_id=uploader_user_id,
                path=storage_path,
                page_count=page_count,
                batch_id=uuid.uuid4(),
                batch_index=1,
            )
            await db.commit()
            return [scan]
        except Exception:
            await db.rollback()
            storage_repo.delete_file(storage_path)
            raise
