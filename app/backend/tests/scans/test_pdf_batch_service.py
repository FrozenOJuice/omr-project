import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.scan import Scan
from services.scans import ScanService


def _job_status(*, finished_timestamp, progress=1.0, success=None, notes=""):
    job_status = MagicMock()
    job_status.finished_timestamp = finished_timestamp
    job_status.progress = progress
    job_status.success = success
    job_status.notes = notes
    return job_status


@pytest.mark.asyncio
async def test_upload_pdf_batch_uses_exam_when_resolving_page_count():
    db = AsyncMock()
    storage = MagicMock()
    exam_id = uuid.uuid4()
    template_id = uuid.uuid4()
    scan = MagicMock()

    with patch("services.scans.ensure_exam_course_writable", new_callable=AsyncMock), \
         patch.object(
             ScanService, "_resolve_group_page_count", new_callable=AsyncMock, return_value=2
         ) as resolve_page_count, \
         patch("services.scans.ScanRepository.create", new_callable=AsyncMock, return_value=scan):
        scans = await ScanService.upload_pdf_batch(
            db=db,
            storage_repo=storage,
            exam_id=exam_id,
            exam_template_id=template_id,
            uploader_user_id=uuid.uuid4(),
            contents=b"%PDF-1.4",
        )

    assert scans == [scan]
    resolve_page_count.assert_awaited_once_with(db, exam_id, template_id)


@pytest.mark.asyncio
async def test_finalize_pdf_batch_uses_exam_when_resolving_page_count():
    db = AsyncMock()
    storage = MagicMock()
    exam_id = uuid.uuid4()
    template_id = uuid.uuid4()
    storage_path = f"exams/{exam_id}/{template_id}/batch.pdf"
    scan = MagicMock()

    with patch("services.scans.ensure_exam_course_writable", new_callable=AsyncMock), \
         patch.object(
             ScanService, "_resolve_group_page_count", new_callable=AsyncMock, return_value=2
         ) as resolve_page_count, \
         patch("services.scans.ScanRepository.create", new_callable=AsyncMock, return_value=scan):
        scans = await ScanService.finalize_pdf_batch_upload(
            db=db,
            storage_repo=storage,
            exam_id=exam_id,
            exam_template_id=template_id,
            uploader_user_id=uuid.uuid4(),
            upload_id="upload-id",
            storage_path=storage_path,
            parts=[{"PartNumber": 1, "ETag": "etag"}],
        )

    assert scans == [scan]
    resolve_page_count.assert_awaited_once_with(db, exam_id, template_id)


@pytest.mark.asyncio
async def test_delete_scans_for_exam_deletes_every_scan_in_one_transaction():
    db = AsyncMock()
    storage = MagicMock()
    exam_id = uuid.uuid4()
    scan_a = Scan(id=uuid.uuid4(), exam_id=exam_id, uploader_user_id=uuid.uuid4(), path="exams/a.pdf", batch_index=1)
    scan_b = Scan(id=uuid.uuid4(), exam_id=exam_id, uploader_user_id=uuid.uuid4(), path="exams/a.pdf", batch_index=2)

    with patch("services.scans.ScanRepository.get_by_exam", new_callable=AsyncMock, return_value=[scan_a, scan_b]), \
         patch("services.scans.ScanRepository.count_others_with_path", new_callable=AsyncMock, side_effect=[1, 0]) as count_others, \
         patch("services.scans.ScanRepository.delete", new_callable=AsyncMock) as delete:
        await ScanService.delete_scans_for_exam(db, storage, exam_id)

    # scan_a's path is still referenced by scan_b when checked first, so its
    # file isn't removed yet; scan_b is the last reference and does remove it.
    assert count_others.await_args_list[0].args == (db, "exams/a.pdf", scan_a.id)
    assert count_others.await_args_list[1].args == (db, "exams/a.pdf", scan_b.id)
    storage.delete_file.assert_called_once_with("exams/a.pdf")
    assert delete.await_count == 2
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_scans_for_exam_is_a_noop_when_exam_has_no_scans():
    db = AsyncMock()
    storage = MagicMock()
    exam_id = uuid.uuid4()

    with patch("services.scans.ScanRepository.get_by_exam", new_callable=AsyncMock, return_value=[]), \
         patch("services.scans.ScanRepository.delete", new_callable=AsyncMock) as delete:
        await ScanService.delete_scans_for_exam(db, storage, exam_id)

    delete.assert_not_awaited()
    storage.delete_file.assert_not_called()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_job_status_reports_unfinished_while_omr_still_running():
    db = AsyncMock()
    scan = Scan(id=uuid.uuid4(), exam_id=uuid.uuid4(), uploader_user_id=uuid.uuid4(), path="exams/a.pdf", omr_job_id="job-1")

    with patch("services.scans.ScanRepository.get_by_id", new_callable=AsyncMock, return_value=scan), \
         patch(
             "services.scans._omr_get_job_status",
             new_callable=AsyncMock,
             return_value=_job_status(finished_timestamp=None, progress=0.4, notes="rendering 4 pages"),
         ), \
         patch("services.scans.ScanRepository.count_batch_progress", new_callable=AsyncMock) as count_progress:
        job_status = await ScanService.get_job_status(db, scan.id)

    assert job_status.finished is False
    assert job_status.progress == 0.4
    assert job_status.notes == "rendering 4 pages"
    # OMR still running -- batch progress isn't even worth checking yet.
    count_progress.assert_not_called()


@pytest.mark.asyncio
async def test_get_job_status_stays_unfinished_while_batch_is_still_grading():
    db = AsyncMock()
    batch_id = uuid.uuid4()
    scan = Scan(
        id=uuid.uuid4(), exam_id=uuid.uuid4(), uploader_user_id=uuid.uuid4(),
        path="exams/a.pdf", omr_job_id="job-1", batch_id=batch_id,
    )

    with patch("services.scans.ScanRepository.get_by_id", new_callable=AsyncMock, return_value=scan), \
         patch(
             "services.scans._omr_get_job_status",
             new_callable=AsyncMock,
             return_value=_job_status(finished_timestamp="2026-01-01T00:00:00Z"),
         ), \
         patch(
             "services.scans.ScanRepository.count_batch_progress",
             new_callable=AsyncMock,
             return_value=(10, 4),
         ):
        job_status = await ScanService.get_job_status(db, scan.id)

    # OMR preprocessing finished, but 4 of 10 scans in the batch are still
    # pending grading, so the pipeline as a whole is not done yet.
    assert job_status.finished is False
    assert job_status.progress == 0.6
    assert job_status.notes == "Grading in progress"


@pytest.mark.asyncio
async def test_get_job_status_finishes_once_batch_grading_is_done():
    db = AsyncMock()
    batch_id = uuid.uuid4()
    scan = Scan(
        id=uuid.uuid4(), exam_id=uuid.uuid4(), uploader_user_id=uuid.uuid4(),
        path="exams/a.pdf", omr_job_id="job-1", batch_id=batch_id,
    )

    with patch("services.scans.ScanRepository.get_by_id", new_callable=AsyncMock, return_value=scan), \
         patch(
             "services.scans._omr_get_job_status",
             new_callable=AsyncMock,
             return_value=_job_status(finished_timestamp="2026-01-01T00:00:00Z", progress=1.0, success=True, notes="done"),
         ), \
         patch(
             "services.scans.ScanRepository.count_batch_progress",
             new_callable=AsyncMock,
             return_value=(10, 0),
         ):
        job_status = await ScanService.get_job_status(db, scan.id)

    assert job_status.finished is True
    assert job_status.success is True
    assert job_status.progress == 1.0
