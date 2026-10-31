import io
import json

import httpx
import pytest

from integrations import omr_client
from integrations.omr_client import (
    OMRClientError,
    OMRJobNotFoundError,
    OMRScanRejectedError,
    OMRTemplateNotFoundError,
    delete_scans,
    get_job_result,
    get_job_status,
    run_marking_job,
    submit_scan_pdf_job,
    upload_marking_template,
    upload_preprocessing_template,
    upload_scan_pdf_batch,
    upload_scan_pdf,
)
from schemas.omr_schema import (
    MarkingConfig,
    MarkingPage,
    MarkingResult,
    MarkingTemplate,
    Point,
    PreprocessingAnchor,
    PreprocessingConfig,
    PreprocessingPage,
    PreprocessingTemplate,
    Question,
    QuestionOption,
    ROI,
)


def _sample_preprocessing_template() -> PreprocessingTemplate:
    anchor = PreprocessingAnchor(
        center=Point(x=10, y=10),
        roi=ROI(min=Point(x=0, y=0), max=Point(x=20, y=20)),
    )
    return PreprocessingTemplate(
        width=800,
        height=1700,
        config=PreprocessingConfig(
            blur_size=5,
            morph_close_size=3,
            min_anchor_confidence=0.5,
            adaptive_block_size=91,
            adaptive_c=-15,
        ),
        pages=[PreprocessingPage(anchors=[anchor, anchor, anchor])],
    )


def _sample_marking_template() -> MarkingTemplate:
    option = QuestionOption(label="A", x=10, y=10)
    question = Question(id="Q1", bubble_width=26, bubble_height=26, options=[option])
    return MarkingTemplate(
        config=MarkingConfig(fill_threshold=0.25, bubble_inset=0.75),
        pages=[MarkingPage(questions=[question])],
    )


class FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.text = text

    @property
    def is_error(self) -> bool:
        return self.status_code >= 400

    def json(self):
        return self._json_data


def _fake_client_returning(calls: list, response: FakeResponse):
    class FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return response

        async def get(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return response

        async def request(self, method, url, **kwargs):
            calls.append({"method": method, "url": url, **kwargs})
            return response

    return FakeAsyncClient


def _fake_client_raising(exc: Exception):
    class FakeAsyncClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, **kwargs):
            raise exc

        async def request(self, method, url, **kwargs):
            raise exc

    return FakeAsyncClient


@pytest.mark.asyncio
async def test_upload_preprocessing_template_sends_expected_multipart(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse(json_data={"templateId": "pt-123"})),
    )

    anchor_images = {
        (0, 0): b"anchor00",
        (0, 1): b"anchor01",
        (0, 2): b"anchor02",
    }

    template_id = await upload_preprocessing_template(_sample_preprocessing_template(), anchor_images)

    assert template_id == "pt-123"
    assert len(calls) == 1
    call = calls[0]
    assert call["url"] == f"{omr_client.settings.omr_base_url}/template/preprocess"
    assert set(call["files"].keys()) == {"page0anchor0", "page0anchor1", "page0anchor2"}
    assert call["files"]["page0anchor1"] == ("page0anchor1.jpg", b"anchor01", "image/jpeg")

    sent_template = json.loads(call["data"]["template"])
    assert sent_template["config"]["blurSize"] == 5
    assert sent_template["config"]["adaptiveBlockSize"] == 91
    assert sent_template["config"]["adaptiveC"] == -15


@pytest.mark.asyncio
async def test_upload_preprocessing_template_raises_on_400(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=400, text="blurSize must be odd")),
    )

    with pytest.raises(OMRClientError):
        await upload_preprocessing_template(
            _sample_preprocessing_template(),
            {(0, 0): b"x", (0, 1): b"x", (0, 2): b"x"},
        )


@pytest.mark.asyncio
async def test_upload_marking_template_sends_expected_json(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse(json_data={"templateId": "mt-456"})),
    )

    template_id = await upload_marking_template(_sample_marking_template())

    assert template_id == "mt-456"
    call = calls[0]
    assert call["url"] == f"{omr_client.settings.omr_base_url}/template/mark"
    assert call["json"]["config"]["fillThreshold"] == 0.25
    assert call["json"]["pages"][0]["questions"][0]["bubbleWidth"] == 26


@pytest.mark.asyncio
async def test_upload_marking_template_raises_on_500(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=500, text="internal error")),
    )

    with pytest.raises(OMRClientError):
        await upload_marking_template(_sample_marking_template())


@pytest.mark.asyncio
async def test_upload_marking_template_wraps_connection_error(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_raising(httpx.ConnectError("connection refused")),
    )

    with pytest.raises(OMRClientError):
        await upload_marking_template(_sample_marking_template())


@pytest.mark.asyncio
async def test_upload_marking_template_raises_on_500_without_structured_body_has_no_code(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=500, text="internal error")),
    )

    with pytest.raises(OMRClientError) as exc_info:
        await upload_marking_template(_sample_marking_template())

    assert exc_info.value.code is None


@pytest.mark.asyncio
async def test_upload_scan_pdf_sends_expected_multipart(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse(json_data={"scanIds": ["scan-pdf-1"], "errors": []})),
    )

    scan_ids = await upload_scan_pdf("pt-123", b"%PDF-1.4 fake bytes")

    assert scan_ids == ["scan-pdf-1"]
    call = calls[0]
    assert call["url"] == f"{omr_client.settings.omr_base_url}/scan/pdf"
    assert call["data"] == {"preprocessingTemplate": "pt-123"}
    assert call["files"]["pdf"] == ("scan.pdf", b"%PDF-1.4 fake bytes", "application/pdf")


@pytest.mark.asyncio
async def test_upload_scan_pdf_includes_dpi_when_given(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse(json_data={"scanIds": ["scan-pdf-1"], "errors": []})),
    )

    await upload_scan_pdf("pt-123", b"fake-pdf-bytes", dpi=150)

    assert calls[0]["data"] == {"preprocessingTemplate": "pt-123", "dpi": "150"}


@pytest.mark.asyncio
async def test_upload_scan_pdf_returns_every_scan_id(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [],
            FakeResponse(
                json_data={
                    "scanIds": ["scan-pdf-1", "scan-pdf-2", "scan-pdf-3"],
                    "errors": [],
                }
            ),
        ),
    )

    assert await upload_scan_pdf("pt-123", b"fake-pdf-bytes") == [
        "scan-pdf-1",
        "scan-pdf-2",
        "scan-pdf-3",
    ]


@pytest.mark.asyncio
async def test_upload_scan_pdf_raises_not_found_on_404(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=404, text="not found")),
    )

    with pytest.raises(OMRTemplateNotFoundError):
        await upload_scan_pdf("missing-id", b"fake-pdf-bytes")


@pytest.mark.asyncio
async def test_upload_scan_pdf_raises_rejected_on_422(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [],
            FakeResponse(
                status_code=422,
                json_data=[{"from": 1, "thru": 2, "debug": "confidence 0.10 below threshold 0.50"}],
            ),
        ),
    )

    with pytest.raises(OMRScanRejectedError) as exc_info:
        await upload_scan_pdf("pt-123", b"fake-pdf-bytes")

    assert "confidence" in str(exc_info.value)
    assert exc_info.value.errors[0]["debug"] == "confidence 0.10 below threshold 0.50"


@pytest.mark.asyncio
async def test_upload_scan_pdf_parses_structured_error_code(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [],
            FakeResponse(
                status_code=400,
                json_data={"code": "malformed_pdf", "message": "the given file does not form a PDF"},
            ),
        ),
    )

    with pytest.raises(OMRClientError) as exc_info:
        await upload_scan_pdf("pt-123", b"not-a-pdf")

    assert exc_info.value.code == "malformed_pdf"


@pytest.mark.asyncio
async def test_upload_scan_pdf_wraps_connection_error(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_raising(httpx.ConnectError("connection refused")),
    )

    with pytest.raises(OMRClientError):
        await upload_scan_pdf("pt-123", b"fake-pdf-bytes")


@pytest.mark.asyncio
async def test_upload_scan_pdf_batch_streams_one_pdf_and_keeps_all_results(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse(
                json_data={
                    "scanIds": ["scan-1", "scan-3"],
                    "errors": [{"from": 3, "thru": 4, "debug": "low confidence"}],
                }
            )

    monkeypatch.setattr(omr_client.httpx, "Client", FakeClient)
    stream = io.BytesIO(b"%PDF-1.4 batch")

    result = await upload_scan_pdf_batch("pt-123", stream, dpi=216)

    assert result.scan_ids == ["scan-1", "scan-3"]
    assert result.errors[0].from_page == 3
    assert calls[0]["data"] == {"preprocessingTemplate": "pt-123", "dpi": "216"}
    assert calls[0]["files"]["pdf"] == ("scan.pdf", stream, "application/pdf")


@pytest.mark.asyncio
async def test_upload_scan_pdf_batch_returns_all_rejections(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, **kwargs):
            return FakeResponse(
                status_code=422,
                json_data=[{"from": 1, "thru": 2, "debug": "unreadable"}],
            )

    monkeypatch.setattr(omr_client.httpx, "Client", FakeClient)

    result = await upload_scan_pdf_batch("pt-123", io.BytesIO(b"pdf"))

    assert result.scan_ids == []
    assert result.errors[0].debug == "unreadable"


@pytest.mark.asyncio
async def test_submit_scan_pdf_job_returns_job_id(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, **kwargs):
            calls.append({"url": url, **kwargs})
            return FakeResponse(status_code=202, json_data={"id": "job-123"})

    monkeypatch.setattr(omr_client.httpx, "Client", FakeClient)
    stream = io.BytesIO(b"%PDF-1.4 batch")

    job_id = await submit_scan_pdf_job("pt-123", stream, dpi=216)

    assert job_id == "job-123"
    assert calls[0]["url"] == f"{omr_client.settings.omr_base_url}/job/scan/pdf"
    assert calls[0]["data"] == {"preprocessingTemplate": "pt-123", "dpi": "216"}


@pytest.mark.asyncio
async def test_submit_scan_pdf_job_raises_not_found_on_404(monkeypatch):
    class FakeClient:
        def __init__(self, timeout=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, **kwargs):
            return FakeResponse(status_code=404, text="not found")

    monkeypatch.setattr(omr_client.httpx, "Client", FakeClient)

    with pytest.raises(OMRTemplateNotFoundError):
        await submit_scan_pdf_job("missing-id", io.BytesIO(b"pdf"), dpi=None)


@pytest.mark.asyncio
async def test_get_job_status_parses_running_job(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            calls,
            FakeResponse(
                json_data={
                    "id": "job-123",
                    "method": "POST",
                    "path": "/job/scan/pdf",
                    "progress": 0.5,
                    "startedTimestamp": 1000,
                    "notes": "rendering 4 pages",
                }
            ),
        ),
    )

    status_obj = await get_job_status("job-123")

    assert status_obj.progress == 0.5
    assert status_obj.finished_timestamp is None
    assert status_obj.success is None


@pytest.mark.asyncio
async def test_get_job_status_parses_finished_job(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [],
            FakeResponse(
                json_data={
                    "id": "job-123",
                    "method": "POST",
                    "path": "/job/scan/pdf",
                    "progress": 1.0,
                    "startedTimestamp": 1000,
                    "finishedTimestamp": 2000,
                    "success": True,
                    "notes": "rendering 4 pages",
                }
            ),
        ),
    )

    status_obj = await get_job_status("job-123")

    assert status_obj.finished_timestamp == 2000
    assert status_obj.success is True


@pytest.mark.asyncio
async def test_get_job_status_raises_not_found_on_404(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=404, text="job ID not recognized")),
    )

    with pytest.raises(OMRJobNotFoundError):
        await get_job_status("missing-job")


@pytest.mark.asyncio
async def test_get_job_result_parses_success_response(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [], FakeResponse(json_data={"scanIds": ["scan-1", "scan-2"], "errors": []})
        ),
    )

    result = await get_job_result("job-123", "pt-123")

    assert result.scan_ids == ["scan-1", "scan-2"]


@pytest.mark.asyncio
async def test_get_job_result_raises_template_not_found_on_replayed_404(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=404, text="not found")),
    )

    with pytest.raises(OMRTemplateNotFoundError):
        await get_job_result("job-123", "pt-123")


@pytest.mark.asyncio
async def test_delete_scans_sends_batch_delete(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse()),
    )

    await delete_scans(["scan-1", "scan-2"])

    assert calls == [
        {
            "method": "DELETE",
            "url": f"{omr_client.settings.omr_base_url}/scan",
            "json": ["scan-1", "scan-2"],
        }
    ]


@pytest.mark.asyncio
async def test_delete_scans_skips_empty_batch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse()),
    )

    await delete_scans([])

    assert calls == []


@pytest.mark.asyncio
async def test_delete_scans_raises_on_omr_error(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=500, text="internal error")),
    )

    with pytest.raises(OMRClientError):
        await delete_scans(["scan-1"])


@pytest.mark.asyncio
async def test_run_marking_job_sends_expected_json_and_parses_result(monkeypatch):
    calls = []
    result_json = {
        "pagesMarked": 2,
        "templateId": "mt-456",
        "scans": [
            {
                "scanId": "scan-1",
                "marks": [
                    {
                        "questionId": "Q1", "flagged": False, "selected": ["A"],
                        "confidence": 0.9, "pageIndex": 0,
                        "bounds": {"x": 0, "y": 10, "width": 200, "height": 60},
                        "boxes": [{"label": "A", "selected": True, "x": 10, "y": 20, "width": 30, "height": 40}],
                    },
                    {
                        "questionId": "Q2", "flagged": True, "selected": [],
                        "confidence": 0.2, "pageIndex": 1,
                        "bounds": {"x": 5, "y": 15, "width": 210, "height": 70},
                        "boxes": [],
                    },
                ],
            }
        ],
    }
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(calls, FakeResponse(json_data=result_json)),
    )

    result = await run_marking_job("mt-456", ["scan-1"])

    assert isinstance(result, MarkingResult)
    assert result.template_id == "mt-456"
    assert result.pages_marked == 2
    assert result.scans[0].scan_id == "scan-1"
    assert result.scans[0].marks[0].question_id == "Q1"
    assert result.scans[0].marks[0].selected == ["A"]
    assert result.scans[0].marks[1].flagged is True

    call = calls[0]
    assert call["url"] == f"{omr_client.settings.omr_base_url}/mark"
    assert call["json"] == {"template": "mt-456", "scans": ["scan-1"]}


@pytest.mark.asyncio
async def test_run_marking_job_accepts_current_response_without_performance_metrics(monkeypatch):
    result_json = {
        "pagesMarked": 1,
        "templateId": "mt-456",
        "scans": [{"scanId": "scan-1", "marks": []}],
    }
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(json_data=result_json)),
    )

    result = await run_marking_job("mt-456", ["scan-1"])

    assert result.pages_marked == 1
    assert result.scans[0].scan_id == "scan-1"


@pytest.mark.asyncio
async def test_run_marking_job_parses_partial_batch_errors(monkeypatch):
    result_json = {
        "pagesMarked": 1,
        "templateId": "mt-456",
        "scans": [{"scanId": "scan-1", "marks": []}],
        "errors": [{"scanId": "scan-2", "debug": "scan scan-2 failed marking"}],
    }
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(json_data=result_json)),
    )

    result = await run_marking_job("mt-456", ["scan-1", "scan-2"])

    assert len(result.scans) == 1
    assert len(result.errors) == 1
    assert result.errors[0].scan_id == "scan-2"
    assert result.errors[0].debug == "scan scan-2 failed marking"


@pytest.mark.asyncio
async def test_run_marking_job_sends_every_scan_id(monkeypatch):
    calls = []
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            calls,
            FakeResponse(
                json_data={
                    "pagesMarked": 0,
                    "templateId": "mt-456",
                    "scans": [],
                    "errors": [],
                }
            ),
        ),
    )

    await run_marking_job("mt-456", ["scan-1", "scan-2", "scan-3"])

    assert calls[0]["json"] == {
        "template": "mt-456",
        "scans": ["scan-1", "scan-2", "scan-3"],
    }


@pytest.mark.asyncio
async def test_run_marking_job_raises_on_422_all_scans_failed(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning(
            [],
            FakeResponse(
                status_code=422,
                json_data=[{"scanId": "scan-1", "debug": "scan scan-1 failed marking"}],
            ),
        ),
    )

    with pytest.raises(OMRClientError) as exc_info:
        await run_marking_job("mt-456", ["scan-1"])

    assert "scan scan-1 failed marking" in str(exc_info.value)


@pytest.mark.asyncio
async def test_run_marking_job_raises_on_404(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=404, text="scan not found")),
    )

    with pytest.raises(OMRClientError):
        await run_marking_job("mt-456", ["missing-scan"])


@pytest.mark.asyncio
async def test_run_marking_job_raises_on_500(monkeypatch):
    monkeypatch.setattr(
        omr_client.httpx,
        "AsyncClient",
        _fake_client_returning([], FakeResponse(status_code=500, text="internal error")),
    )

    with pytest.raises(OMRClientError):
        await run_marking_job("mt-456", ["scan-1"])
