import io
import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import fitz
import pytest
from PIL import Image

from models.scan import Scan
from integrations.omr_client import OMRClientError
from schemas.omr_schema import OMRJobStatus, PDFScanResult
from services.scan_processing import (
    FAILURE_OMR_SERVICE_ERROR,
    FAILURE_SCAN_PREPROCESSING_FAILED,
    _detect_scan_dpi,
    _materialize_pdf_batch_results,
    run_pdf_batch_pipeline,
)


def _finished_job_status(**overrides) -> OMRJobStatus:
    fields = dict(
        id="job-1",
        method="POST",
        path="/job/scan/pdf",
        progress=1.0,
        startedTimestamp=1000,
        finishedTimestamp=2000,
        success=True,
        notes="",
    )
    fields.update(overrides)
    return OMRJobStatus.model_validate(fields)


def _make_scanned_pdf_bytes(dpi: float, page_w_pt: float = 612.0, page_h_pt: float = 792.0) -> bytes:
    """Builds a one-page PDF with a full-page embedded JPEG sized so its
    pixel dimensions imply the given DPI against the given page size, the
    same shape a real scan-to-PDF tool produces.
    """
    width_px = round(page_w_pt / 72 * dpi)
    height_px = round(page_h_pt / 72 * dpi)

    img = Image.new("RGB", (width_px, height_px), "white")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")

    doc = fitz.open()
    page = doc.new_page(width=page_w_pt, height=page_h_pt)
    page.insert_image(fitz.Rect(0, 0, page_w_pt, page_h_pt), stream=buf.getvalue())
    result = doc.tobytes()
    doc.close()
    return result


def _make_blank_pdf_bytes() -> bytes:
    """A one-page PDF with no embedded image, standing in for a synthetic
    vector-rendered exam that has no scan resolution to detect.
    """
    doc = fitz.open()
    doc.new_page(width=612, height=792)
    result = doc.tobytes()
    doc.close()
    return result


def _stub_download_to_file(pdf_bytes: bytes):
    """A storage_repo.download_to_file side_effect that writes fixed bytes
    to whatever destination path the pipeline gives it, mimicking a real
    download without touching Garage/S3.
    """
    def _write(filename, dest_path):
        with open(dest_path, "wb") as f:
            f.write(pdf_bytes)
    return _write


class TestDetectScanDpi:
    def test_measures_dpi_from_embedded_image(self, tmp_path):
        pdf_path = tmp_path / "scan.pdf"
        pdf_path.write_bytes(_make_scanned_pdf_bytes(dpi=150))
        assert _detect_scan_dpi(str(pdf_path)) == pytest.approx(150, abs=1)

    def test_returns_none_for_purely_vector_pdf(self, tmp_path):
        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.draw_rect(fitz.Rect(50, 50, 200, 200), fill=(0, 0, 0))
        pdf_path = tmp_path / "vector.pdf"
        pdf_path.write_bytes(doc.tobytes())
        doc.close()

        assert _detect_scan_dpi(str(pdf_path)) is None

    def test_returns_none_for_invalid_pdf(self, tmp_path):
        pdf_path = tmp_path / "not-a-pdf.pdf"
        pdf_path.write_bytes(b"not a pdf")
        assert _detect_scan_dpi(str(pdf_path)) is None


def _session_context(db):
    session_local = MagicMock()
    session_local.return_value.__aenter__ = AsyncMock(return_value=db)
    session_local.return_value.__aexit__ = AsyncMock(return_value=None)
    return session_local


@pytest.mark.asyncio
async def test_materialize_pdf_batch_maps_partial_results_to_existing_scan_rows():
    seed_id = uuid.uuid4()
    batch_id = uuid.uuid4()
    seed = Scan(
        id=seed_id,
        exam_id=uuid.uuid4(),
        exam_template_id=uuid.uuid4(),
        uploader_user_id=uuid.uuid4(),
        path="exams/batch.pdf",
        page_count=2,
        batch_id=batch_id,
        batch_index=1,
        status="pending",
    )
    created = []

    async def create_many_scans(db, records):
        scans = [Scan(id=uuid.uuid4(), status="pending", **record) for record in records]
        created.extend(scans)
        return scans

    db = AsyncMock()
    result = PDFScanResult(
        scanIds=["omr-1", "omr-3"],
        errors=[{"from": 3, "thru": 4, "debug": "low anchor confidence"}],
    )

    with patch("services.scan_processing.AsyncSessionLocal", _session_context(db)), \
         patch("services.scan_processing.ScanRepository.get_by_id", new_callable=AsyncMock, return_value=seed), \
         patch("services.scan_processing.ScanRepository.create_many", new_callable=AsyncMock, side_effect=create_many_scans):
        ready = await _materialize_pdf_batch_results(seed_id, result)

    assert len(created) == 2
    records = [seed, *created]
    assert [scan.batch_index for scan in records] == [1, 2, 3]
    assert records[0].omr_scan_id == "omr-1"
    # Successfully preprocessed scans stay "pending" -- they only become
    # "completed" once grading (not just preprocessing) resolves them; see
    # _trigger_marking.
    assert records[0].status == "pending"
    assert records[1].status == "failed"
    assert records[1].failure_code == FAILURE_SCAN_PREPROCESSING_FAILED
    assert records[2].omr_scan_id == "omr-3"
    assert ready == [records[0].id, records[2].id]
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_pdf_batch_pipeline_downloads_to_temp_file_and_marks_successes():
    seed_id = uuid.uuid4()
    child_id = uuid.uuid4()
    storage = MagicMock()
    # A vector-only stub PDF has no embedded image to measure, so detection
    # falls back to the template's native_dpi (None here) and then the fixed default.
    storage.download_to_file.side_effect = _stub_download_to_file(_make_blank_pdf_bytes())
    result = PDFScanResult(scanIds=["omr-1", "omr-2"], errors=[])
    db = AsyncMock()

    with patch("services.scan_processing.get_omr_template_id", new_callable=AsyncMock, return_value=("pt-1", None)), \
         patch("services.scan_processing.AsyncSessionLocal", _session_context(db)), \
         patch("services.scan_processing.ScanRepository.set_omr_job_id", new_callable=AsyncMock) as set_job_id, \
         patch("services.scan_processing._omr_submit_scan_pdf_job", new_callable=AsyncMock, return_value="job-1") as submit, \
         patch("services.scan_processing._omr_get_job_status", new_callable=AsyncMock, return_value=_finished_job_status()) as get_status, \
         patch("services.scan_processing._omr_get_job_result", new_callable=AsyncMock, return_value=result) as get_result, \
         patch("services.scan_processing._materialize_pdf_batch_results", new_callable=AsyncMock, return_value=[seed_id, child_id]), \
         patch("services.scan_processing._trigger_marking", new_callable=AsyncMock) as mark:
        await run_pdf_batch_pipeline("exams/batch.pdf", seed_id, storage)

    storage.download_to_file.assert_called_once()
    assert storage.download_to_file.call_args.args[0] == "exams/batch.pdf"
    temp_path = storage.download_to_file.call_args.args[1]
    submit.assert_awaited_once()
    assert submit.await_args.args[0] == "pt-1"
    assert submit.await_args.kwargs["dpi"] == 216
    set_job_id.assert_awaited_once_with(db, seed_id, "job-1")
    get_status.assert_awaited_once_with("job-1")
    get_result.assert_awaited_once_with("job-1", "pt-1")
    mark.assert_awaited_once_with([seed_id, child_id])
    # The temp file used for detection/upload is cleaned up once the pipeline finishes.
    assert not os.path.exists(temp_path)


@pytest.mark.asyncio
async def test_pdf_batch_pipeline_polls_until_job_finishes():
    seed_id = uuid.uuid4()
    storage = MagicMock()
    storage.download_to_file.side_effect = _stub_download_to_file(_make_blank_pdf_bytes())
    result = PDFScanResult(scanIds=["omr-1"], errors=[])
    db = AsyncMock()

    statuses = [
        _finished_job_status(progress=0.5, finishedTimestamp=0, success=None),
        _finished_job_status(),
    ]

    with patch("services.scan_processing.get_omr_template_id", new_callable=AsyncMock, return_value=("pt-1", None)), \
         patch("services.scan_processing.AsyncSessionLocal", _session_context(db)), \
         patch("services.scan_processing.ScanRepository.set_omr_job_id", new_callable=AsyncMock), \
         patch("services.scan_processing._omr_submit_scan_pdf_job", new_callable=AsyncMock, return_value="job-1"), \
         patch("services.scan_processing._omr_get_job_status", new_callable=AsyncMock, side_effect=statuses) as get_status, \
         patch("services.scan_processing._omr_get_job_result", new_callable=AsyncMock, return_value=result), \
         patch("services.scan_processing._materialize_pdf_batch_results", new_callable=AsyncMock, return_value=[seed_id]), \
         patch("services.scan_processing._trigger_marking", new_callable=AsyncMock), \
         patch("services.scan_processing.asyncio.sleep", new_callable=AsyncMock) as sleep:
        await run_pdf_batch_pipeline("exams/batch.pdf", seed_id, storage)

    assert get_status.await_count == 2
    sleep.assert_awaited_once()


@pytest.mark.asyncio
async def test_pdf_batch_pipeline_prefers_detected_dpi_over_template_calibration():
    seed_id = uuid.uuid4()
    storage = MagicMock()
    storage.download_to_file.side_effect = _stub_download_to_file(_make_scanned_pdf_bytes(dpi=150))
    result = PDFScanResult(scanIds=["omr-1"], errors=[])
    db = AsyncMock()

    with patch("services.scan_processing.get_omr_template_id", new_callable=AsyncMock, return_value=("pt-1", 216)), \
         patch("services.scan_processing.AsyncSessionLocal", _session_context(db)), \
         patch("services.scan_processing.ScanRepository.set_omr_job_id", new_callable=AsyncMock), \
         patch("services.scan_processing._omr_submit_scan_pdf_job", new_callable=AsyncMock, return_value="job-1") as submit, \
         patch("services.scan_processing._omr_get_job_status", new_callable=AsyncMock, return_value=_finished_job_status()), \
         patch("services.scan_processing._omr_get_job_result", new_callable=AsyncMock, return_value=result), \
         patch("services.scan_processing._materialize_pdf_batch_results", new_callable=AsyncMock, return_value=[seed_id]), \
         patch("services.scan_processing._trigger_marking", new_callable=AsyncMock):
        await run_pdf_batch_pipeline("exams/batch.pdf", seed_id, storage)

    assert submit.await_args.kwargs["dpi"] == 150


@pytest.mark.asyncio
async def test_pdf_batch_pipeline_fails_seed_and_cleans_up_temp_file_when_omr_fails():
    seed_id = uuid.uuid4()
    storage = MagicMock()
    storage.download_to_file.side_effect = _stub_download_to_file(_make_blank_pdf_bytes())

    with patch("services.scan_processing.get_omr_template_id", new_callable=AsyncMock, return_value=("pt-1", None)), \
         patch(
             "services.scan_processing._omr_submit_scan_pdf_job",
             new_callable=AsyncMock,
             side_effect=OMRClientError("OMR unavailable"),
         ), \
         patch("services.scan_processing._fail_scan", new_callable=AsyncMock) as fail, \
         patch("services.scan_processing._trigger_marking", new_callable=AsyncMock) as mark:
        await run_pdf_batch_pipeline("exams/batch.pdf", seed_id, storage)

    fail.assert_awaited_once_with(seed_id, FAILURE_OMR_SERVICE_ERROR, "OMR unavailable")
    mark.assert_not_awaited()
    temp_path = storage.download_to_file.call_args.args[1]
    assert not os.path.exists(temp_path)


@pytest.mark.asyncio
async def test_materialize_rejects_omr_error_ranges_that_do_not_match_exam_pages():
    seed_id = uuid.uuid4()
    seed = Scan(
        id=seed_id,
        exam_id=uuid.uuid4(),
        exam_template_id=uuid.uuid4(),
        uploader_user_id=uuid.uuid4(),
        path="exams/batch.pdf",
        page_count=2,
        batch_id=uuid.uuid4(),
        batch_index=1,
        status="pending",
    )
    db = AsyncMock()
    result = PDFScanResult(
        scanIds=["omr-1"],
        errors=[{"from": 2, "thru": 3, "debug": "invalid range"}],
    )

    with patch("services.scan_processing.AsyncSessionLocal", _session_context(db)), \
         patch("services.scan_processing.ScanRepository.get_by_id", new_callable=AsyncMock, return_value=seed), \
         patch("services.scan_processing.ScanRepository.create", new_callable=AsyncMock) as create:
        with pytest.raises(OMRClientError, match="page range"):
            await _materialize_pdf_batch_results(seed_id, result)

    create.assert_not_awaited()
    db.commit.assert_not_awaited()
