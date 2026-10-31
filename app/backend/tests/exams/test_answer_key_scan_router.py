from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from services.answer_key_scan_extraction import MAX_ANSWER_KEY_SCAN_BYTES

pytestmark = pytest.mark.db


def _extraction_response():
    return {
        "pages_per_sheet": 1,
        "sheets": [
            {
                "sheet_index": 0,
                "source_filename": "keys.pdf",
                "page_start": 1,
                "page_end": 1,
                "answers": {
                    "1": {
                        "selected_choices": ["B"],
                        "confidence": 0.93,
                        "flagged": False,
                    }
                },
                "version": {
                    "status": "detected",
                    "selected_choices": ["A"],
                    "detected_version": "A",
                    "confidence": 0.91,
                },
                "minimum_confidence": 0.91,
                "warnings": [],
            }
        ],
    }


async def test_extract_scan_route_accepts_multipart_pdf(authenticated_client):
    client, token = await authenticated_client()
    exam_id = uuid4()

    with patch(
        "routers.exam_answer_key_router.extract_answer_key_scan",
        new_callable=AsyncMock,
        return_value=_extraction_response(),
    ) as mock_extract:
        response = await client.post(
            f"/api/exams/{exam_id}/answer-keys/extract-scan",
            headers={"Authorization": f"Bearer {token}"},
            data={"question_count": "1"},
            files=[("files", ("keys.pdf", b"%PDF-test", "application/pdf"))],
        )

    assert response.status_code == 200
    assert response.json()["sheets"][0]["answers"]["1"]["selected_choices"] == ["B"]
    assert mock_extract.await_count == 1
    assert mock_extract.await_args.args[1] == exam_id
    assert mock_extract.await_args.kwargs["question_count"] == 1
    uploads = mock_extract.await_args.kwargs["files"]
    assert len(uploads) == 1
    assert uploads[0].filename == "keys.pdf"
    assert uploads[0].content_type == "application/pdf"
    assert uploads[0].pdf_bytes == b"%PDF-test"


async def test_extract_scan_route_accepts_multiple_files(authenticated_client):
    client, token = await authenticated_client()
    exam_id = uuid4()

    with patch(
        "routers.exam_answer_key_router.extract_answer_key_scan",
        new_callable=AsyncMock,
        return_value=_extraction_response(),
    ) as mock_extract:
        response = await client.post(
            f"/api/exams/{exam_id}/answer-keys/extract-scan",
            headers={"Authorization": f"Bearer {token}"},
            data={"question_count": "1"},
            files=[
                ("files", ("keys-a.pdf", b"%PDF-a", "application/pdf")),
                ("files", ("keys-b.pdf", b"%PDF-b", "application/pdf")),
            ],
        )

    assert response.status_code == 200
    uploads = mock_extract.await_args.kwargs["files"]
    assert [upload.filename for upload in uploads] == ["keys-a.pdf", "keys-b.pdf"]


async def test_extract_scan_route_requires_authentication(client):
    response = await client.post(
        f"/api/exams/{uuid4()}/answer-keys/extract-scan",
        data={"question_count": "1"},
        files=[("files", ("keys.pdf", b"%PDF-test", "application/pdf"))],
    )

    assert response.status_code == 401


async def test_extract_scan_route_validates_question_count(authenticated_client):
    client, token = await authenticated_client()

    with patch(
        "routers.exam_answer_key_router.extract_answer_key_scan",
        new_callable=AsyncMock,
    ) as mock_extract:
        response = await client.post(
            f"/api/exams/{uuid4()}/answer-keys/extract-scan",
            headers={"Authorization": f"Bearer {token}"},
            data={"question_count": "0"},
            files=[("files", ("keys.pdf", b"%PDF-test", "application/pdf"))],
        )

    assert response.status_code == 422
    mock_extract.assert_not_awaited()


async def test_extract_scan_route_rejects_oversized_pdf(authenticated_client):
    client, token = await authenticated_client()

    with patch(
        "routers.exam_answer_key_router.extract_answer_key_scan",
        new_callable=AsyncMock,
    ) as mock_extract:
        response = await client.post(
            f"/api/exams/{uuid4()}/answer-keys/extract-scan",
            headers={"Authorization": f"Bearer {token}"},
            data={"question_count": "1"},
            files=[
                (
                    "files",
                    (
                        "keys.pdf",
                        b"x" * (MAX_ANSWER_KEY_SCAN_BYTES + 1),
                        "application/pdf",
                    ),
                )
            ],
        )

    assert response.status_code == 413
    mock_extract.assert_not_awaited()
