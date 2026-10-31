"""Unit tests for services/omr_marking_service.py (all DB/OMR calls mocked)."""
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from integrations.omr_client import OMRClientError
from models.omr_detected_mark import MarkFieldType
from schemas.omr_schema import DetectedQuestionMark
from services.omr_marking_service import MarkingConfigError, run_and_store_marking


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UNSET = object()


def _scan(exam_template_id=_UNSET, omr_scan_id="omr-scan-1"):
    s = MagicMock()
    s.id = uuid4()
    s.exam_template_id = uuid4() if exam_template_id is _UNSET else exam_template_id
    s.omr_scan_id = omr_scan_id
    return s


def _exam_template(omr_template_id=_UNSET):
    t = MagicMock()
    t.omr_template_id = uuid4() if omr_template_id is _UNSET else omr_template_id
    return t


def _omr_template(mark_template_id="mt-1"):
    t = MagicMock()
    t.id = uuid4()
    t.mark_template_id = mark_template_id
    return t


def _marking():
    m = MagicMock()
    m.id = uuid4()
    return m


def _marking_result(scans, errors=None):
    r = MagicMock()
    r.scans = scans
    r.errors = errors or []
    return r


def _scan_marks(scan_id, marks):
    sm = MagicMock()
    sm.scan_id = scan_id
    sm.marks = marks
    return sm


def _marking_error(scan_id, debug):
    e = MagicMock()
    e.scan_id = scan_id
    e.debug = debug
    return e


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


@pytest.fixture
def mock_session_local(mock_db):
    session_local = MagicMock()
    session_local.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    session_local.return_value.__aexit__ = AsyncMock(return_value=None)
    return session_local


# ---------------------------------------------------------------------------
# Config-error paths (scan/template not ready) — none should reach the OMR service
# ---------------------------------------------------------------------------

class TestRunAndStoreMarkingConfigErrors:
    async def test_no_scan_ids_returns_empty(self, mock_session_local):
        with patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local):
            markings, failures = await run_and_store_marking([])
        assert markings == {}
        assert failures == {}

    @pytest.mark.parametrize(
        "scan,exam_template,omr_template",
        [
            pytest.param(None, _exam_template(), _omr_template(), id="scan_not_found"),
            pytest.param(_scan(omr_scan_id=None), _exam_template(), _omr_template(), id="scan_missing_omr_scan_id"),
            pytest.param(_scan(exam_template_id=None), _exam_template(), _omr_template(), id="scan_missing_exam_template_id"),
            pytest.param(_scan(), None, _omr_template(), id="exam_template_not_found"),
            pytest.param(_scan(), _exam_template(omr_template_id=None), _omr_template(), id="exam_template_has_no_omr_template"),
            pytest.param(_scan(), _exam_template(), _omr_template(mark_template_id=None), id="omr_template_missing_mark_template_id"),
        ],
    )
    async def test_config_error_reported_as_failure_not_raised(
        self, mock_session_local, scan, exam_template, omr_template
    ):
        scan_id = scan.id if scan is not None else uuid4()
        scans_by_id = {scan_id: scan} if scan is not None else {}
        with (
            patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local),
            patch("services.omr_marking_service.ScanRepository.get_by_ids", AsyncMock(return_value=scans_by_id)),
            patch("services.omr_marking_service.get_exam_template_by_id", AsyncMock(return_value=exam_template)),
            patch("services.omr_marking_service.get_omr_template_by_id", AsyncMock(return_value=omr_template)),
            patch("services.omr_marking_service.run_marking_job", new_callable=AsyncMock) as mock_run,
        ):
            markings, failures = await run_and_store_marking([scan_id])

        assert markings == {}
        assert isinstance(failures[scan_id], MarkingConfigError)
        mock_run.assert_not_awaited()


# ---------------------------------------------------------------------------
# Happy path + OMR service failure paths
# ---------------------------------------------------------------------------

class TestRunAndStoreMarking:
    async def test_happy_path_persists_typed_detected_marks(self, mock_db, mock_session_local):
        scan = _scan(omr_scan_id="omr-scan-1")
        template = _exam_template()
        omr_template = _omr_template(mark_template_id="mt-1")
        marking = _marking()

        marks = [
            DetectedQuestionMark(
                questionId="Q1", flagged=False, selected=["A"], confidence=0.9, pageIndex=0,
                bounds={"x": 0, "y": 10, "width": 200, "height": 60},
                boxes=[
                    {"label": "A", "selected": True, "x": 10, "y": 20, "width": 30, "height": 40},
                    {"label": "B", "selected": False, "x": 50, "y": 20, "width": 30, "height": 40},
                ],
            ),
            DetectedQuestionMark(
                questionId="L3", flagged=True, selected=[], confidence=0.4, pageIndex=1,
                bounds={"x": 5, "y": 15, "width": 210, "height": 70},
                boxes=[],
            ),
            DetectedQuestionMark(
                questionId="V1", flagged=False, selected=["B"], confidence=0.7, pageIndex=0,
                bounds={"x": 80, "y": 90, "width": 130, "height": 140},
                boxes=[{"label": "B", "selected": True, "x": 90, "y": 100, "width": 110, "height": 120}],
            ),
        ]
        result = _marking_result([_scan_marks("omr-scan-1", marks)])

        with (
            patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local),
            patch("services.omr_marking_service.ScanRepository.get_by_ids", AsyncMock(return_value={scan.id: scan})),
            patch("services.omr_marking_service.get_exam_template_by_id", AsyncMock(return_value=template)),
            patch("services.omr_marking_service.get_omr_template_by_id", AsyncMock(return_value=omr_template)),
            patch("services.omr_marking_service.create_marking", AsyncMock(return_value=marking)) as mock_create_marking,
            patch("services.omr_marking_service.run_marking_job", AsyncMock(return_value=result)) as mock_run,
            patch("services.omr_marking_service.create_detected_marks", new_callable=AsyncMock) as mock_create_detected,
        ):
            markings, failures = await run_and_store_marking([scan.id])

        assert markings == {scan.id: marking.id}
        assert failures == {}
        mock_create_marking.assert_awaited_once_with(
            mock_db, scan_id=scan.id, omr_template_id=omr_template.id, flush=False
        )
        mock_run.assert_awaited_once_with("mt-1", ["omr-scan-1"])

        stored = mock_create_detected.call_args.args[2]
        assert stored == [
            (
                MarkFieldType.QUESTION, 1, "A", False, 0,
                {"x": 0, "y": 10, "width": 200, "height": 60},
                [
                    {"label": "A", "selected": True, "x": 10, "y": 20, "width": 30, "height": 40},
                    {"label": "B", "selected": False, "x": 50, "y": 20, "width": 30, "height": 40},
                ], 0.9,
            ),
            (
                MarkFieldType.LAST_NAME, 3, None, True, 1,
                {"x": 5, "y": 15, "width": 210, "height": 70},
                [], 0.4,
            ),
            (
                MarkFieldType.VERSION, 1, "B", False, 0,
                {"x": 80, "y": 90, "width": 130, "height": 140},
                [{"label": "B", "selected": True, "x": 90, "y": 100, "width": 110, "height": 120}], 0.7,
            ),
        ]

        assert marking.status == "completed"

    async def test_batches_multiple_scans_into_one_mark_request(self, mock_db, mock_session_local):
        scan_a = _scan(omr_scan_id="omr-a")
        scan_b = _scan(omr_scan_id="omr-b")
        template = _exam_template()
        omr_template = _omr_template(mark_template_id="mt-1")
        marking_a, marking_b = _marking(), _marking()

        result = _marking_result([
            _scan_marks("omr-a", []),
            _scan_marks("omr-b", []),
        ])

        scans_by_id = {scan_a.id: scan_a, scan_b.id: scan_b}
        markings_by_id = {scan_a.id: marking_a, scan_b.id: marking_b}

        with (
            patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local),
            patch("services.omr_marking_service.ScanRepository.get_by_ids", AsyncMock(return_value=scans_by_id)),
            patch("services.omr_marking_service.get_exam_template_by_id", AsyncMock(return_value=template)),
            patch("services.omr_marking_service.get_omr_template_by_id", AsyncMock(return_value=omr_template)),
            patch("services.omr_marking_service.create_marking", AsyncMock(side_effect=lambda db, scan_id, omr_template_id, flush=False: markings_by_id[scan_id])),
            patch("services.omr_marking_service.run_marking_job", AsyncMock(return_value=result)) as mock_run,
            patch("services.omr_marking_service.create_detected_marks", new_callable=AsyncMock),
        ):
            markings, failures = await run_and_store_marking([scan_a.id, scan_b.id])

        mock_run.assert_awaited_once_with("mt-1", ["omr-a", "omr-b"])
        assert markings == {scan_a.id: marking_a.id, scan_b.id: marking_b.id}
        assert failures == {}

    async def test_omr_client_error_fails_whole_batch_and_reraises(self, mock_db, mock_session_local):
        scan = _scan()
        template = _exam_template()
        omr_template = _omr_template()
        marking = _marking()

        with (
            patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local),
            patch("services.omr_marking_service.ScanRepository.get_by_ids", AsyncMock(return_value={scan.id: scan})),
            patch("services.omr_marking_service.get_exam_template_by_id", AsyncMock(return_value=template)),
            patch("services.omr_marking_service.get_omr_template_by_id", AsyncMock(return_value=omr_template)),
            patch("services.omr_marking_service.create_marking", AsyncMock(return_value=marking)),
            patch("services.omr_marking_service.run_marking_job", AsyncMock(side_effect=OMRClientError("boom"))),
        ):
            with pytest.raises(OMRClientError):
                await run_and_store_marking([scan.id])

        assert marking.status == "failed"

    async def test_scan_missing_from_result_marks_failed(self, mock_db, mock_session_local):
        scan = _scan(omr_scan_id="omr-scan-1")
        template = _exam_template()
        omr_template = _omr_template()
        marking = _marking()
        result = _marking_result(
            [_scan_marks("some-other-scan", [])],
            errors=[_marking_error("omr-scan-1", "page not found")],
        )

        with (
            patch("services.omr_marking_service.AsyncSessionLocal", mock_session_local),
            patch("services.omr_marking_service.ScanRepository.get_by_ids", AsyncMock(return_value={scan.id: scan})),
            patch("services.omr_marking_service.get_exam_template_by_id", AsyncMock(return_value=template)),
            patch("services.omr_marking_service.get_omr_template_by_id", AsyncMock(return_value=omr_template)),
            patch("services.omr_marking_service.create_marking", AsyncMock(return_value=marking)),
            patch("services.omr_marking_service.run_marking_job", AsyncMock(return_value=result)),
            patch("services.omr_marking_service.create_detected_marks", new_callable=AsyncMock) as mock_create_detected,
        ):
            markings, failures = await run_and_store_marking([scan.id])

        assert markings == {}
        assert isinstance(failures[scan.id], MarkingConfigError)
        mock_create_detected.assert_not_awaited()
        assert marking.status == "failed"
