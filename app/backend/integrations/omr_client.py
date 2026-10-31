import asyncio
import logging
from typing import BinaryIO

import httpx

from core.settings import settings
from schemas.omr_schema import OMRJobStatus, PDFScanResult, MarkingResult, MarkingTemplate, PreprocessingTemplate

logger = logging.getLogger(__name__)


class OMRClientError(Exception):
    """Raised when a request to the OMR service fails or returns an unexpected response.

    `code` is the OMR service's error code (see app/omr's handler/errors.go)
    when the response body was a structured JSON error, or None if the
    service couldn't be reached at all or returned something else.
    """

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


class OMRTemplateNotFoundError(OMRClientError):
    """Raised when the OMR service doesn't recognize a given templateId (404)."""


class OMRScanRejectedError(OMRClientError):
    """Raised when the OMR service parsed the PDF fine but none of the exams
    inside it passed preprocessing (422), e.g. poor scan quality or pages
    out of order. Unlike a 4xx/5xx request-level error, this comes back as a
    bare list of `{from, thru, debug}` entries rather than a structured
    `code`, so retrying without changing the input won't help.
    """

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message, code=None)
        self.errors = errors or []


class OMRJobNotFoundError(OMRClientError):
    """Raised when the OMR service doesn't recognize a given job id (404) -
    either it was never registered, or it was evicted (jobs are forgotten
    ~24h after they finish; see app/omr's JobRegistrar).
    """


def _error_from_response(response: httpx.Response) -> OMRClientError:
    try:
        body = response.json()
        code = body.get("code")
        message = body.get("message") or response.text
    except ValueError:
        code = None
        message = response.text
    return OMRClientError(f"OMR service returned {response.status_code}: {message}", code=code)


async def upload_preprocessing_template(
    template: PreprocessingTemplate,
    anchor_images: dict[tuple[int, int], bytes],
) -> str:
    """Uploads a preprocessing template (POST /template/preprocess).

    `anchor_images` maps (page_index, anchor_index) -> JPEG bytes, matching the
    `page{X}anchor{Y}` multipart fields the OMR service expects. Every page
    needs at least 3 anchors, each specified explicitly (the OMR service no
    longer infers shared anchors across pages).

    Returns the new preprocessing templateId.
    """
    data = {"template": template.model_dump_json(by_alias=True)}
    files = {
        f"page{page_idx}anchor{anchor_idx}": (
            f"page{page_idx}anchor{anchor_idx}.jpg",
            img_bytes,
            "image/jpeg",
        )
        for (page_idx, anchor_idx), img_bytes in anchor_images.items()
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.omr_base_url}/template/preprocess",
                data=data,
                files=files,
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_upload_preprocessing_template_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to upload preprocessing template to OMR service") from exc

    if response.is_error:
        raise _error_from_response(response)

    return response.json()["templateId"]


async def upload_marking_template(template: MarkingTemplate) -> str:
    """Uploads a marking template (POST /template/mark).

    Returns the new marking templateId.
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.omr_base_url}/template/mark",
                json=template.model_dump(by_alias=True),
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_upload_marking_template_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to upload marking template to OMR service") from exc

    if response.is_error:
        raise _error_from_response(response)

    return response.json()["templateId"]


async def upload_scan_pdf(
    preprocess_template_id: str,
    pdf_bytes: bytes,
    dpi: int | None = None,
) -> list[str]:
    """Upload a PDF batch (POST /scan/pdf) and return every new scan ID.

    The OMR service groups the PDF pages using the preprocessing template, so
    one upload may produce any number of independently markable scans.

    Raises OMRTemplateNotFoundError if the preprocessing templateId isn't
    recognized (404), or OMRScanRejectedError if the PDF was well-formed but
    the exam didn't pass preprocessing (422).
    """
    data = {"preprocessingTemplate": preprocess_template_id}
    if dpi is not None:
        data["dpi"] = str(dpi)
    files = {"pdf": ("scan.pdf", pdf_bytes, "application/pdf")}

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{settings.omr_base_url}/scan/pdf",
                data=data,
                files=files,
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_upload_scan_pdf_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to upload PDF scan to OMR service") from exc

    if response.status_code == 404:
        raise OMRTemplateNotFoundError(
            f"Preprocessing template '{preprocess_template_id}' not found"
        )
    if response.status_code == 422:
        try:
            errors = response.json()
        except ValueError:
            errors = []
        detail = errors[0].get("debug") if errors else None
        raise OMRScanRejectedError(
            f"OMR rejected the scan: {detail or 'no exams passed preprocessing'}",
            errors=errors,
        )
    if response.is_error:
        raise _error_from_response(response)

    scan_ids = response.json().get("scanIds") or []
    if not scan_ids:
        raise OMRClientError("OMR service returned no scan IDs for the uploaded PDF")
    return scan_ids


async def delete_scans(scan_ids: list[str]) -> None:
    """Delete temporary scans from the OMR service.

    The OMR endpoint is idempotent, so callers can safely run this from a
    ``finally`` block even when an earlier extraction or marking step failed.
    """
    if not scan_ids:
        return

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.request(
                "DELETE",
                f"{settings.omr_base_url}/scan",
                json=scan_ids,
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_delete_scans_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to delete scans from OMR service") from exc

    if response.is_error:
        raise _error_from_response(response)


def _parse_pdf_scan_response(response: httpx.Response, preprocess_template_id: str) -> PDFScanResult:
    """Interprets a PDF-scan response (whether from the synchronous POST
    /scan/pdf or a job-ified POST /job/scan/pdf's replayed GET /job/result),
    since both endpoints share the same underlying handler and response shape.
    """
    if response.status_code == 404:
        raise OMRTemplateNotFoundError(
            f"Preprocessing template '{preprocess_template_id}' not found"
        )
    if response.status_code == 422:
        return PDFScanResult(scanIds=[], errors=response.json())
    if response.is_error:
        raise _error_from_response(response)
    return PDFScanResult.model_validate(response.json())


def _upload_scan_pdf_batch_sync(
    preprocess_template_id: str,
    pdf_stream: BinaryIO,
    dpi: int | None,
) -> PDFScanResult:
    """Stream a stored batch PDF to OMR without loading it into backend memory."""
    data = {"preprocessingTemplate": preprocess_template_id}
    if dpi is not None:
        data["dpi"] = str(dpi)

    # PDF preprocessing is synchronous in OMR and can legitimately take more
    # than two minutes for a large exam stack. Keep a bounded connect timeout,
    # but do not turn successful long-running jobs into duplicate retries.
    timeout = httpx.Timeout(None, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{settings.omr_base_url}/scan/pdf",
            data=data,
            files={"pdf": ("scan.pdf", pdf_stream, "application/pdf")},
        )

    return _parse_pdf_scan_response(response, preprocess_template_id)


async def upload_scan_pdf_batch(
    preprocess_template_id: str,
    pdf_stream: BinaryIO,
    dpi: int | None = None,
) -> PDFScanResult:
    """Submit one potentially multi-exam PDF and retain every OMR result."""
    try:
        return await asyncio.to_thread(
            _upload_scan_pdf_batch_sync,
            preprocess_template_id,
            pdf_stream,
            dpi,
        )
    except httpx.HTTPError as exc:
        logger.error("event=omr_upload_scan_pdf_batch_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to upload PDF batch to OMR service") from exc


def _submit_scan_pdf_job_sync(
    preprocess_template_id: str,
    pdf_stream: BinaryIO,
    dpi: int | None,
) -> str:
    """Kick off a job-ified PDF batch upload (POST /job/scan/pdf) and return
    its job id. The OMR service accepts the multipart body and returns 202
    immediately, before preprocessing has actually run.
    """
    data = {"preprocessingTemplate": preprocess_template_id}
    if dpi is not None:
        data["dpi"] = str(dpi)

    timeout = httpx.Timeout(None, connect=10.0)
    with httpx.Client(timeout=timeout) as client:
        response = client.post(
            f"{settings.omr_base_url}/job/scan/pdf",
            data=data,
            files={"pdf": ("scan.pdf", pdf_stream, "application/pdf")},
        )

    if response.status_code == 404:
        raise OMRTemplateNotFoundError(
            f"Preprocessing template '{preprocess_template_id}' not found"
        )
    if response.is_error:
        raise _error_from_response(response)
    return response.json()["id"]


async def submit_scan_pdf_job(
    preprocess_template_id: str,
    pdf_stream: BinaryIO,
    dpi: int | None = None,
) -> str:
    """Submit a PDF batch as an async OMR job and return its job id, so
    callers can poll get_job_status/get_job_result instead of blocking.
    """
    try:
        return await asyncio.to_thread(
            _submit_scan_pdf_job_sync,
            preprocess_template_id,
            pdf_stream,
            dpi,
        )
    except httpx.HTTPError as exc:
        logger.error("event=omr_submit_scan_pdf_job_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to submit PDF batch job to OMR service") from exc


async def get_job_status(job_id: str) -> OMRJobStatus:
    """Fetch an OMR job's current progress/status (GET /job)."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.omr_base_url}/job",
                params={"id": job_id},
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_get_job_status_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to fetch job status from OMR service") from exc

    if response.status_code == 404:
        raise OMRJobNotFoundError(f"OMR job '{job_id}' not found")
    if response.is_error:
        raise _error_from_response(response)

    return OMRJobStatus.model_validate(response.json())


async def get_job_result(job_id: str, preprocess_template_id: str) -> PDFScanResult:
    """Fetch a finished job's original PDF-scan response (GET /job/result),
    which replays the same status code/body POST /job/scan/pdf's underlying
    handler would have returned synchronously - including a 404 if that
    original call didn't recognize the preprocessing template. Callers are
    expected to have already polled get_job_status to completion, so an
    "unknown job id" 404 shouldn't happen here; a 404 is treated as a
    replayed template-not-found error rather than as OMRJobNotFoundError.
    """
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.omr_base_url}/job/result",
                params={"id": job_id},
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_get_job_result_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to fetch job result from OMR service") from exc

    return _parse_pdf_scan_response(response, preprocess_template_id)


async def run_marking_job(marking_template_id: str, scan_ids: list[str]) -> MarkingResult:
    """Run one batch marking job (POST /mark) and return all scan results.

    This call is synchronous — the OMR service marks scans fast enough
    (~3ms/page) that it just returns results directly in the response rather
    than handing back a job id to poll. A given scan's own marking failure is
    reported in `MarkingResult.errors` rather than failing the whole request;
    raise OMRClientError for request-level failures (bad template/scan ids,
    malformed request, upstream 5xx).
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{settings.omr_base_url}/mark",
                json={"template": marking_template_id, "scans": scan_ids},
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_run_marking_job_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to run marking job on OMR service") from exc

    if response.status_code == 422:
        # Every scan in the batch failed to mark. Unlike other error
        # responses, the body here is a bare list of {scanId, debug} (not
        # {code, message}), so it needs its own handling rather than
        # _error_from_response.
        try:
            errors = response.json()
        except ValueError:
            errors = []
        detail = errors[0].get("debug") if errors else None
        raise OMRClientError(
            f"OMR rejected the marking job: {detail or 'every scan in the batch failed to mark'}"
        )
    if response.is_error:
        raise _error_from_response(response)

    return MarkingResult.model_validate(response.json())


async def get_question_snippet(marking_template_id: str, scan_id: str, question_id: str) -> bytes:
    """Fetches the OMR service's cropped image for a question on a marked scan."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.omr_base_url}/snippet",
                params={
                    "template": marking_template_id,
                    "scan": scan_id,
                    "question": question_id,
                },
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_get_question_snippet_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to fetch question snippet from OMR service") from exc

    if response.is_error:
        raise _error_from_response(response)

    return response.content


async def get_scan_page_image(scan_id: str, page_idx: int) -> bytes:
    """Fetches the OMR service's unmodified picture for a single page of a scan."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                f"{settings.omr_base_url}/image",
                params={"scan": scan_id, "page": page_idx},
            )
    except httpx.HTTPError as exc:
        logger.error("event=omr_get_scan_page_image_failed error_type=%s", type(exc).__name__)
        raise OMRClientError("Failed to fetch page image from OMR service") from exc

    if response.is_error:
        raise _error_from_response(response)

    return response.content
