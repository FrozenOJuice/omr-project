"""Background processing for uploaded batch PDFs."""

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from uuid import UUID

import fitz

from db.session import AsyncSessionLocal
from integrations.omr_client import (
    OMRClientError,
    OMRTemplateNotFoundError,
    get_job_result as _omr_get_job_result,
    get_job_status as _omr_get_job_status,
    submit_scan_pdf_job as _omr_submit_scan_pdf_job,
)
from repositories.exam_templates import get_exam_template_by_id
from repositories.exams import get_exam_by_id
from repositories.omr_templates import get_omr_template_by_id
from repositories.scans import ScanRepository
from repositories.storage import StorageRepository
from schemas.omr_schema import PDFScanResult
from services.grading_service import grade_markings_batch
from services.notifications import notify_course_staff, notify_user
from services.omr_marking_service import run_and_store_marking


# Fallback render density for templates created before native_dpi was stored.
OMR_UPLOAD_DPI = 216

# How often to check an in-flight OMR job for completion. Progress itself is
# read on demand by the frontend's own poll of the job-status endpoint; this
# loop only needs to notice when the job is done so grading can continue.
JOB_POLL_INTERVAL_SECONDS = 1.0

# Scans persisted per commit while writing back grading results. Small enough
# that the batch's progress bar (ScanRepository.count_batch_progress) still
# advances visibly, large enough to avoid a commit round trip per scan.
_MARKING_COMMIT_CHUNK_SIZE = 10

FAILURE_TEMPLATE_NOT_CONFIGURED = "template_not_configured"
FAILURE_PAGE_COUNT_MISMATCH = "page_count_mismatch"
FAILURE_LOW_SCAN_QUALITY = "low_scan_quality"
FAILURE_PAGE_OUT_OF_ORDER = "page_out_of_order"
FAILURE_MALFORMED_PDF = "malformed_pdf"
FAILURE_FILE_TOO_LARGE = "content_too_large"
FAILURE_SCAN_PREPROCESSING_FAILED = "scan_preprocessing_failed"
FAILURE_OMR_SERVICE_ERROR = "omr_service_error"

_NON_RETRYABLE_OMR_CODES = {
    "page_count_mismatch": FAILURE_PAGE_COUNT_MISMATCH,
    "low_scan_quality": FAILURE_LOW_SCAN_QUALITY,
    "page_out_of_order": FAILURE_PAGE_OUT_OF_ORDER,
    "malformed_pdf": FAILURE_MALFORMED_PDF,
    "content_too_large": FAILURE_FILE_TOO_LARGE,
    "missing_anchor": FAILURE_TEMPLATE_NOT_CONFIGURED,
}


async def get_omr_template_id(scan_id: UUID) -> tuple[str, float | None]:
    """Resolve the OMR preprocessing template and its calibrated DPI."""
    async with AsyncSessionLocal() as db:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan or not scan.exam_template_id:
            raise ValueError(f"Scan {scan_id} has no exam_template_id")

        exam_template = await get_exam_template_by_id(db, scan.exam_template_id)
        if not exam_template or not exam_template.omr_template_id:
            raise ValueError(
                f"Exam template {scan.exam_template_id} has no linked OMR template"
            )

        omr_template = await get_omr_template_by_id(db, exam_template.omr_template_id)
        if not omr_template or not omr_template.preprocess_template_id:
            raise ValueError(
                f"OMR template {exam_template.omr_template_id} is not registered with OMR"
            )

        return omr_template.preprocess_template_id, omr_template.native_dpi


async def _notify_scan_failure(db, scan_id: UUID, type: str, title: str, body: str) -> None:
    try:
        scan = await ScanRepository.get_by_id(db, scan_id)
        if not scan:
            return
        exam = await get_exam_by_id(db, scan.exam_id)
        course_id = exam.course_id if exam else None
        link_query = f"courseId={course_id}&examId={scan.exam_id}" if course_id else f"examId={scan.exam_id}"
        if type == "scan_failed":
            link_query += "&action=upload"

        await notify_user(
            db,
            recipient_user_id=scan.uploader_user_id,
            type=type,
            title=title,
            body=body,
            course_id=course_id,
            link_path="/courses",
            link_query=link_query,
        )
        if course_id is not None:
            await notify_course_staff(
                db,
                course_id=course_id,
                type=type,
                title=title,
                body=body,
                link_path="/courses",
                link_query=link_query,
                exclude_user_id=scan.uploader_user_id,
            )
    except Exception as notify_err:
        print(f"[Scan {scan_id}] Failed to send failure notification: {notify_err}")


async def _fail_scan(scan_id: UUID, failure_code: str, failure_detail: str) -> None:
    async with AsyncSessionLocal() as db:
        try:
            await ScanRepository.set_failed(db, scan_id, failure_code, failure_detail)
            await db.commit()
        except Exception as db_err:
            print(f"Failed to log pipeline error status for scan {scan_id}: {db_err}")
            await db.rollback()
            return

        await _notify_scan_failure(
            db, scan_id, "scan_failed", "Scan processing failed", failure_detail
        )


async def _fail_marking(scan_id: UUID, exc: Exception) -> None:
    print(f"[Scan {scan_id}] Marking failed: {exc}")
    try:
        async with AsyncSessionLocal() as db:
            await ScanRepository.set_failed(db, scan_id, FAILURE_OMR_SERVICE_ERROR, str(exc))
            await db.commit()
            await _notify_scan_failure(
                db, scan_id, "scan_failed", "Scan processing failed", str(exc)
            )
    except Exception as db_err:
        print(f"[Scan {scan_id}] Failed to log marking failure: {db_err}")


async def _trigger_marking(scan_ids: list[UUID]) -> None:
    """Mark and grade every successfully preprocessed scan in a batch.

    All of these scans share the same exam template, so they're marked in
    one /mark request instead of one request per scan - much faster, and it
    saves the OMR service redundant network/disk round trips. Grading is
    batched the same way (see grade_markings_batch): the exam/template/
    answer-key/roster data every scan's grading needs is loaded once for the
    whole batch instead of once per scan.

    Individually notifying staff for every flagged grade was also the
    dominant cost for a large batch (a 125-scan upload could mean 125
    separate notification writes/emails), so every scan that ends up needing
    review is rolled into one "N grades need review" notification instead.

    Each scan only flips to "completed" once grading actually resolves it
    here, not back when it was merely preprocessed -- see
    _materialize_pdf_batch_results, which leaves successfully preprocessed
    scans "pending" for exactly this reason.
    """
    if not scan_ids:
        return

    try:
        markings, failures = await run_and_store_marking(scan_ids)
    except Exception as exc:
        for scan_id in scan_ids:
            await _fail_marking(scan_id, exc)
        return

    for scan_id, exc in failures.items():
        await _fail_marking(scan_id, exc)

    if not markings:
        return

    results = await grade_markings_batch(list(markings.values()))

    needs_review_count = 0
    exam = None
    failed: list[tuple[UUID, Exception]] = []
    async with AsyncSessionLocal() as db:
        items = list(markings.items())
        for start in range(0, len(items), _MARKING_COMMIT_CHUNK_SIZE):
            chunk = items[start : start + _MARKING_COMMIT_CHUNK_SIZE]
            scans = await ScanRepository.get_by_ids(db, [scan_id for scan_id, _ in chunk])
            for scan_id, marking_id in chunk:
                scan = scans.get(scan_id)
                if scan is None:
                    continue
                result = results.get(marking_id)
                if isinstance(result, Exception):
                    scan.status = "failed"
                    scan.failure_code = FAILURE_OMR_SERVICE_ERROR
                    scan.failure_detail = str(result)
                    failed.append((scan_id, result))
                else:
                    scan.status = "completed"
                    if result.status == "needs_review":
                        needs_review_count += 1
                        if exam is None:
                            exam = await get_exam_by_id(db, scan.exam_id)
            await db.commit()

        for scan_id, result in failed:
            await _notify_scan_failure(
                db, scan_id, "grading_failed", "Grading failed for a scan", str(result)
            )

        if needs_review_count > 0 and exam is not None:
            plural = "s" if needs_review_count != 1 else ""
            await notify_course_staff(
                db,
                course_id=exam.course_id,
                type="grade_needs_review",
                title="Grades need manual review",
                body=f"{needs_review_count} grade{plural} from {exam.name} require manual review",
                link_path="/courses",
                link_query=f"courseId={exam.course_id}&examId={exam.id}",
            )


async def _materialize_pdf_batch_results(
    seed_scan_id: UUID,
    result: PDFScanResult,
) -> list[UUID]:
    """Expand one pending batch row into one row per OMR result."""
    total = len(result.scan_ids) + len(result.errors)
    if total == 0:
        raise OMRClientError("OMR returned no scans or errors for the uploaded PDF")

    async with AsyncSessionLocal() as db:
        seed = await ScanRepository.get_by_id(db, seed_scan_id)
        if not seed or not seed.page_count:
            raise ValueError(f"Batch scan {seed_scan_id} has no page-count metadata")

        errors_by_index = {}
        for error in result.errors:
            batch_index = ((error.from_page - 1) // seed.page_count) + 1
            expected_from = (batch_index - 1) * seed.page_count + 1
            expected_thru = batch_index * seed.page_count
            if error.from_page != expected_from or error.thru_page != expected_thru:
                raise OMRClientError(
                    "OMR returned an error page range that does not align with the exam template"
                )
            if batch_index in errors_by_index or batch_index > total:
                raise OMRClientError("OMR returned inconsistent PDF batch results")
            errors_by_index[batch_index] = error

        children = await ScanRepository.create_many(
            db,
            [
                {
                    "exam_id": seed.exam_id,
                    "exam_template_id": seed.exam_template_id,
                    "uploader_user_id": seed.uploader_user_id,
                    "path": seed.path,
                    "page_count": seed.page_count,
                    "batch_id": seed.batch_id,
                    "batch_index": batch_index,
                }
                for batch_index in range(2, total + 1)
            ],
        )
        records = {1: seed, **{scan.batch_index: scan for scan in children}}

        successful_ids = iter(result.scan_ids)
        ready_to_mark: list[UUID] = []
        for batch_index, scan in records.items():
            error = errors_by_index.get(batch_index)
            if error:
                scan.status = "failed"
                scan.failure_code = FAILURE_SCAN_PREPROCESSING_FAILED
                scan.failure_detail = error.debug
                continue

            try:
                scan.omr_scan_id = next(successful_ids)
            except StopIteration as exc:
                raise OMRClientError("OMR returned inconsistent PDF batch results") from exc
            # Stays "pending" here -- preprocessing succeeding isn't the same
            # as being done. It only becomes "completed" once grading
            # actually resolves it (see _trigger_marking below), so a
            # frontend poll that stops as soon as status leaves "pending"
            # doesn't declare victory mid-pipeline and then miss a later
            # grading failure.
            ready_to_mark.append(scan.id)

        if next(successful_ids, None) is not None:
            raise OMRClientError("OMR returned inconsistent PDF batch results")

        await db.commit()
        return ready_to_mark


@asynccontextmanager
async def _local_pdf_file(storage_repo: StorageRepository, storage_path: str):
    """Downloads a stored PDF to a local temp file for the duration of the block.

    Neither DPI detection nor the OMR upload need the whole file in backend
    process memory at once: fitz can inspect a file on disk directly, and
    httpx streams a file handle the same way it streams an S3 body. Routing
    through disk instead of `storage_repo.open_file`'s streaming body just
    means the file can be read twice (once to detect DPI, once to upload)
    without buffering it in memory or downloading it from storage twice.
    """
    fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(fd)
    try:
        await asyncio.to_thread(storage_repo.download_to_file, storage_path, tmp_path)
        yield tmp_path
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass


def _detect_scan_dpi(pdf_path: str) -> float | None:
    """Estimates a scanned exam PDF's real DPI from its first page's largest
    embedded image, comparing the image's pixel size against the page area
    it's actually placed in (its bbox) rather than trusting the image's own
    resolution metadata. Scanners and PDF tools routinely leave that
    metadata at a bogus default (a sample real scan reported 96 there while
    its actual pixel density, measured this way, was 150), so it can't be
    trusted.

    Returns None if the PDF has no full-page-scale embedded image to
    measure, such as a purely vector/rendered page like the seeded
    synthetic exam PDFs, so callers can fall back to a template's
    calibration DPI or a fixed default instead.
    """
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return None

    try:
        if doc.page_count == 0:
            return None
        images = doc[0].get_image_info(xrefs=True)
        if not images:
            return None

        largest = max(images, key=lambda img: img["width"] * img["height"])
        x0, y0, x1, y1 = largest["bbox"]
        bbox_w_pt, bbox_h_pt = x1 - x0, y1 - y0
        if bbox_w_pt <= 0 or bbox_h_pt <= 0:
            return None

        dpi_x = largest["width"] / (bbox_w_pt / 72)
        dpi_y = largest["height"] / (bbox_h_pt / 72)
        return (dpi_x + dpi_y) / 2
    finally:
        doc.close()


async def run_pdf_batch_pipeline(
    storage_path: str,
    seed_scan_id: UUID,
    storage_repo: StorageRepository,
) -> None:
    """Stream one intact stored PDF to OMR, then materialize, mark, and grade it."""
    try:
        omr_template_id, native_dpi = await get_omr_template_id(seed_scan_id)
    except ValueError as exc:
        await _fail_scan(seed_scan_id, FAILURE_TEMPLATE_NOT_CONFIGURED, str(exc))
        return

    try:
        async with _local_pdf_file(storage_repo, storage_path) as pdf_path:
            # The scan's own actual resolution, when it can be measured,
            # wins over the template's calibration DPI: requesting a render
            # density that doesn't match what the scan really is forces the
            # OMR service's PDF renderer to upsample or downsample it, which
            # blurs out thin single-letter marks even on an otherwise-clean scan.
            detected_dpi = _detect_scan_dpi(pdf_path)
            render_dpi = detected_dpi or native_dpi or OMR_UPLOAD_DPI
            with open(pdf_path, "rb") as pdf_stream:
                job_id = await _omr_submit_scan_pdf_job(
                    omr_template_id,
                    pdf_stream,
                    dpi=round(render_dpi),
                )

        async with AsyncSessionLocal() as db:
            await ScanRepository.set_omr_job_id(db, seed_scan_id, job_id)
            await db.commit()

        while True:
            status = await _omr_get_job_status(job_id)
            if status.finished_timestamp:
                break
            await asyncio.sleep(JOB_POLL_INTERVAL_SECONDS)

        result = await _omr_get_job_result(job_id, omr_template_id)
        ready_to_mark = await _materialize_pdf_batch_results(seed_scan_id, result)
    except OMRTemplateNotFoundError as exc:
        await _fail_scan(seed_scan_id, FAILURE_TEMPLATE_NOT_CONFIGURED, str(exc))
        return
    except OMRClientError as exc:
        await _fail_scan(
            seed_scan_id,
            _NON_RETRYABLE_OMR_CODES.get(exc.code, FAILURE_OMR_SERVICE_ERROR),
            str(exc),
        )
        return
    except Exception as exc:
        await _fail_scan(seed_scan_id, FAILURE_OMR_SERVICE_ERROR, str(exc))
        return

    await _trigger_marking(ready_to_mark)
