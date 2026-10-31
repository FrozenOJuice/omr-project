import uuid
import pytest
from fastapi import status
from unittest.mock import AsyncMock, MagicMock, patch
from main import app
from dependencies.storage_dep import get_storage_repo
from models.scan import Scan

pytestmark = pytest.mark.db

@pytest.fixture
def mock_storage_dependency():
    mock_storage = MagicMock()
    app.dependency_overrides[get_storage_repo] = lambda: mock_storage
    yield mock_storage
    app.dependency_overrides.clear()

@pytest.mark.asyncio
async def test_router_upload_pdf_uses_batch_pipeline(authenticated_client, mock_storage_dependency):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    exam_id = uuid.uuid4()
    template_id = uuid.uuid4()
    scan = Scan(
        id=uuid.uuid4(),
        exam_id=exam_id,
        exam_template_id=template_id,
        uploader_user_id=uuid.uuid4(),
        path=f"exams/{exam_id}/{template_id}/batch.pdf",
        page_count=2,
        batch_id=uuid.uuid4(),
        batch_index=1,
        status="pending",
    )

    with patch("services.scans.ScanService.upload_pdf_batch", new_callable=AsyncMock, return_value=[scan]) as upload, \
         patch("routers.scan_router.run_pdf_batch_pipeline", new_callable=AsyncMock) as pipeline:
        response = await client.post(
            "/api/scans/pdf",
            files={"file": ("batch.pdf", b"%PDF-1.4", "application/pdf")},
            data={"exam_id": str(exam_id), "exam_template_id": str(template_id)},
            headers=headers,
        )

    assert response.status_code == status.HTTP_201_CREATED
    upload.assert_awaited_once()
    pipeline.assert_awaited_once_with(
        storage_path=scan.path,
        seed_scan_id=scan.id,
        storage_repo=mock_storage_dependency,
    )

@pytest.mark.asyncio
async def test_router_initiate_multipart_success(authenticated_client, mock_storage_dependency):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    
    mock_response = {
        "upload_id": "session-xyz",
        "storage_path": "exams/path.pdf",
        "urls": [{"part_number": 1, "url": "https://garage.com/part1"}]
    }

    with patch("services.scans.ScanService.prepare_multipart_upload", new_callable=AsyncMock) as mock_service:
        mock_service.return_value = mock_response

        payload = {
            "exam_id": str(uuid.uuid4()),
            "exam_template_id": str(uuid.uuid4()),
            "filename": "heavy_test.pdf",
            "total_chunks": 1
        }

        response = await client.post("/api/scans/initiate", json=payload, headers=headers)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["upload_id"] == "session-xyz"
        assert len(response.json()["urls"]) == 1

@pytest.mark.asyncio
async def test_router_initiate_multipart_too_large(authenticated_client, mock_storage_dependency):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}

    payload = {
        "exam_id": str(uuid.uuid4()),
        "exam_template_id": str(uuid.uuid4()),
        "filename": "giant.pdf",
        "total_chunks": 150
    }

    response = await client.post("/api/scans/initiate", json=payload, headers=headers)
    assert response.status_code == status.HTTP_400_BAD_REQUEST

@pytest.mark.asyncio
async def test_router_finalize_pdf_uses_batch_pipeline(authenticated_client, mock_storage_dependency):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    exam_id = uuid.uuid4()
    template_id = uuid.uuid4()
    scan = Scan(
        id=uuid.uuid4(),
        exam_id=exam_id,
        exam_template_id=template_id,
        uploader_user_id=uuid.uuid4(),
        path=f"exams/{exam_id}/{template_id}/batch.pdf",
        page_count=2,
        batch_id=uuid.uuid4(),
        batch_index=1,
        status="pending",
    )

    with patch("services.scans.ScanService.finalize_pdf_batch_upload", new_callable=AsyncMock, return_value=[scan]) as finalize, \
         patch("routers.scan_router.run_pdf_batch_pipeline", new_callable=AsyncMock) as pipeline:
        response = await client.post(
            "/api/scans/finalize-pdf",
            json={
                "upload_id": "upload-1",
                "storage_path": scan.path,
                "exam_id": str(exam_id),
                "exam_template_id": str(template_id),
                "parts": [{"PartNumber": 1, "ETag": "etag-1"}],
            },
            headers=headers,
        )

    assert response.status_code == status.HTTP_201_CREATED
    finalize.assert_awaited_once()
    pipeline.assert_awaited_once_with(
        storage_path=scan.path,
        seed_scan_id=scan.id,
        storage_repo=mock_storage_dependency,
    )


@pytest.mark.asyncio
async def test_router_get_scan_job_status_success(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    scan_id = uuid.uuid4()

    from schemas.scan_schema import ScanJobStatusResponse

    with patch(
        "services.scans.ScanService.get_job_status",
        new_callable=AsyncMock,
        return_value=ScanJobStatusResponse(progress=0.5, finished=False, success=None, notes="rendering 4 pages"),
    ) as get_status:
        response = await client.get(f"/api/scans/{scan_id}/job-status", headers=headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {
        "progress": 0.5,
        "finished": False,
        "success": None,
        "notes": "rendering 4 pages",
    }
    get_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_router_get_scan_job_status_404_when_no_active_job(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    scan_id = uuid.uuid4()

    from fastapi import HTTPException, status as http_status

    with patch(
        "services.scans.ScanService.get_job_status",
        new_callable=AsyncMock,
        side_effect=HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail="No active OMR job for this scan."),
    ):
        response = await client.get(f"/api/scans/{scan_id}/job-status", headers=headers)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.asyncio
async def test_router_delete_all_scans_for_exam_success(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    exam_id = uuid.uuid4()

    with patch(
        "services.scans.ScanService.delete_scans_for_exam",
        new_callable=AsyncMock,
    ) as delete_all:
        response = await client.delete(f"/api/scans/exam/{exam_id}", headers=headers)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    delete_all.assert_awaited_once()
    assert delete_all.await_args.kwargs["exam_id"] == exam_id


@pytest.mark.asyncio
async def test_router_list_scans_by_template_success(authenticated_client):
    client, token = await authenticated_client()
    headers = {"Authorization": f"Bearer {token}"}
    
    exam_id = uuid.uuid4()
    template_id = uuid.uuid4()

    mock_scans_list = [
        Scan(id=uuid.uuid4(), exam_id=exam_id, exam_template_id=template_id, uploader_user_id=uuid.uuid4(), path="exams/s1.pdf", page_count=2, status="completed"),
        Scan(id=uuid.uuid4(), exam_id=exam_id, exam_template_id=template_id, uploader_user_id=uuid.uuid4(), path="exams/s2.pdf", page_count=4, status="failed"),
    ]

    with patch("services.scans.ScanService.get_scans_for_template", new_callable=AsyncMock) as mock_service:
        mock_service.return_value = mock_scans_list

        response = await client.get(f"/api/scans/template/{template_id}", headers=headers)
        
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["path"] == "exams/s1.pdf"
        assert data[0]["status"] == "completed"
        assert data[1]["status"] == "failed"
