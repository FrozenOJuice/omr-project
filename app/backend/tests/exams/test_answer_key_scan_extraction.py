from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import fitz
import pytest

from errors.exceptions import BadRequestError, ForbiddenError, ServiceUnavailableError
from integrations.omr_client import OMRClientError
from schemas.exam_answer_keys import (
    AnswerKeyScanWarningCode,
    AnswerKeyVersionDetectionStatus,
)
from schemas.omr_schema import DetectedQuestionMark, MarkingResult
from services import answer_key_scan_extraction as extraction


def _pdf(page_count: int) -> bytes:
    document = fitz.open()
    try:
        for _ in range(page_count):
            document.new_page()
        return document.tobytes()
    finally:
        document.close()


def _mark(
    question_id: str,
    selected: list[str],
    *,
    confidence: float = 0.9,
    flagged: bool = False,
) -> DetectedQuestionMark:
    return DetectedQuestionMark.model_validate(
        {
            "questionId": question_id,
            "flagged": flagged,
            "selected": selected,
            "confidence": confidence,
            "pageIndex": 0,
            "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
            "boxes": [],
        }
    )


def _marking(scans: list[tuple[str, list[DetectedQuestionMark]]], errors=None):
    return MarkingResult.model_validate(
        {
            "pagesMarked": len(scans),
            "templateId": "mark-template",
            "scans": [
                {"scanId": scan_id, "marks": marks}
                for scan_id, marks in scans
            ],
            "errors": errors or [],
        }
    )


def _configure(
    monkeypatch,
    *,
    owner_id=None,
    question_config=None,
    version_count=2,
    version_from_q1=False,
    pages_per_sheet=1,
    scan_ids=None,
    marking=None,
):
    owner_id = owner_id or uuid4()
    template_id = uuid4()
    omr_template_id = uuid4()

    exam = MagicMock(
        created_by=owner_id,
        exam_template_id=template_id,
    )
    template = MagicMock(
        id=template_id,
        question_config=question_config or {
            "1": {"choices": ["A", "B", "C"]},
            "2": {"choices": ["A", "B", "C"]},
        },
        n_versions=version_count,
        version_from_q1=version_from_q1,
        omr_template_id=omr_template_id,
    )
    omr_template = MagicMock(
        id=omr_template_id,
        page_count=pages_per_sheet,
        preprocess_template_id="preprocess-template",
        mark_template_id="mark-template",
    )
    scan_ids = scan_ids or ["scan-1"]
    marking = marking or _marking(
        [(scan_ids[0], [_mark("Q1", ["A"]), _mark("Q2", ["B"]), _mark("V1", ["A"])])]
    )

    mocks = {
        "get_exam": AsyncMock(return_value=exam),
        "get_template": AsyncMock(return_value=template),
        "get_omr_template": AsyncMock(return_value=omr_template),
        "ensure_writable": AsyncMock(),
        "upload": AsyncMock(return_value=scan_ids),
        "mark": AsyncMock(return_value=marking),
        "delete": AsyncMock(),
    }
    monkeypatch.setattr(extraction, "get_exam_by_id", mocks["get_exam"])
    monkeypatch.setattr(extraction, "get_exam_template_by_id", mocks["get_template"])
    monkeypatch.setattr(extraction, "get_omr_template_by_id", mocks["get_omr_template"])
    monkeypatch.setattr(extraction, "ensure_exam_course_writable", mocks["ensure_writable"])
    monkeypatch.setattr(extraction, "upload_scan_pdf", mocks["upload"])
    monkeypatch.setattr(extraction, "run_marking_job", mocks["mark"])
    monkeypatch.setattr(extraction, "delete_scans", mocks["delete"])
    return owner_id, exam, template, omr_template, mocks


async def test_extracts_every_sheet_in_upload_order_and_cleans_up(monkeypatch):
    scan_ids = ["scan-1", "scan-2"]
    marking = _marking(
        [
            (
                "scan-2",
                [_mark("Q1", ["C"], confidence=0.8), _mark("Q2", ["A"]), _mark("V1", ["B"])],
            ),
            (
                "scan-1",
                [_mark("Q1", ["A"], confidence=0.7), _mark("Q2", ["B"]), _mark("V1", ["A"], confidence=0.6)],
            ),
        ]
    )
    owner_id, _, _, _, mocks = _configure(
        monkeypatch,
        pages_per_sheet=2,
        scan_ids=scan_ids,
        marking=marking,
    )

    result = await extraction.extract_answer_key_scan(
        AsyncMock(),
        uuid4(),
        owner_id,
        files=[extraction.AnswerKeyScanUpload(filename="all-keys.pdf", content_type="application/pdf", pdf_bytes=_pdf(4))],
        question_count=2,
    )

    assert result.pages_per_sheet == 2
    assert [sheet.version.detected_version for sheet in result.sheets] == ["A", "B"]
    assert result.sheets[0].answers["1"].selected_choices == ["A"]
    assert (result.sheets[0].page_start, result.sheets[0].page_end) == (1, 2)
    assert (result.sheets[1].page_start, result.sheets[1].page_end) == (3, 4)
    assert result.sheets[0].minimum_confidence == pytest.approx(0.6)
    mocks["upload"].assert_awaited_once_with("preprocess-template", ANY)
    mocks["mark"].assert_awaited_once_with("mark-template", scan_ids)
    mocks["delete"].assert_awaited_once_with(scan_ids)


async def test_extracts_sheets_from_multiple_files_with_per_file_page_numbering(monkeypatch):
    marking = _marking(
        [
            ("scan-a1", [_mark("Q1", ["A"]), _mark("V1", ["A"])]),
            ("scan-b1", [_mark("Q1", ["B"]), _mark("V1", ["B"])]),
        ]
    )
    owner_id, _, _, _, mocks = _configure(
        monkeypatch,
        pages_per_sheet=1,
        marking=marking,
    )
    mocks["upload"].side_effect = [["scan-a1"], ["scan-b1"]]

    result = await extraction.extract_answer_key_scan(
        AsyncMock(),
        uuid4(),
        owner_id,
        files=[
            extraction.AnswerKeyScanUpload(filename="a.pdf", content_type="application/pdf", pdf_bytes=_pdf(1)),
            extraction.AnswerKeyScanUpload(filename="b.pdf", content_type="application/pdf", pdf_bytes=_pdf(1)),
        ],
        question_count=1,
    )

    assert [sheet.source_filename for sheet in result.sheets] == ["a.pdf", "b.pdf"]
    assert [sheet.sheet_index for sheet in result.sheets] == [0, 1]
    # Page numbers reset per file rather than continuing across the batch.
    assert [(sheet.page_start, sheet.page_end) for sheet in result.sheets] == [(1, 1), (1, 1)]
    mocks["mark"].assert_awaited_once_with("mark-template", ["scan-a1", "scan-b1"])
    mocks["delete"].assert_awaited_once_with(["scan-a1", "scan-b1"])


async def test_bad_file_in_multi_file_upload_is_attributed_to_its_filename(monkeypatch):
    owner_id, _, _, _, mocks = _configure(monkeypatch, pages_per_sheet=2)

    with pytest.raises(BadRequestError) as exc_info:
        await extraction.extract_answer_key_scan(
            AsyncMock(),
            uuid4(),
            owner_id,
            files=[
                extraction.AnswerKeyScanUpload(filename="a.pdf", content_type="application/pdf", pdf_bytes=_pdf(2)),
                extraction.AnswerKeyScanUpload(filename="b.pdf", content_type="application/pdf", pdf_bytes=_pdf(3)),
            ],
            question_count=1,
        )

    assert exc_info.value.code == "answer_key_scan_page_count_mismatch"
    assert exc_info.value.message.startswith("b.pdf:")
    # Every file is validated before any of them are uploaded to OMR.
    mocks["upload"].assert_not_awaited()


async def test_identifies_blank_flagged_and_problem_versions(monkeypatch):
    scan_ids = ["scan-1", "scan-2", "scan-3", "scan-4", "scan-5"]
    marking = _marking(
        [
            ("scan-1", [_mark("Q1", [], confidence=0.4), _mark("V1", ["A"])]),
            ("scan-2", [_mark("Q1", ["B"], flagged=True), _mark("V1", ["A"])]),
            ("scan-3", [_mark("Q1", ["C"]), _mark("V1", ["A", "B"])]),
            ("scan-4", [_mark("Q1", ["A"]), _mark("V1", ["Z"])]),
            ("scan-5", [_mark("Q1", ["B"]), _mark("V1", [])]),
        ]
    )
    owner_id, _, _, _, _ = _configure(
        monkeypatch,
        question_config={"1": {"choices": ["A", "B", "C"]}},
        scan_ids=scan_ids,
        marking=marking,
    )

    result = await extraction.extract_answer_key_scan(
        AsyncMock(),
        uuid4(),
        owner_id,
        files=[extraction.AnswerKeyScanUpload(filename="keys.pdf", content_type="application/pdf", pdf_bytes=_pdf(5))],
        question_count=1,
    )

    warning_codes = [
        {warning.code for warning in sheet.warnings}
        for sheet in result.sheets
    ]
    assert warning_codes[0] == {
        AnswerKeyScanWarningCode.BLANK_ANSWER,
        AnswerKeyScanWarningCode.VERSION_DUPLICATE,
    }
    assert warning_codes[1] == {
        AnswerKeyScanWarningCode.LOW_CONFIDENCE,
        AnswerKeyScanWarningCode.VERSION_DUPLICATE,
    }
    assert warning_codes[2] == {AnswerKeyScanWarningCode.VERSION_AMBIGUOUS}
    assert result.sheets[2].version.status == AnswerKeyVersionDetectionStatus.AMBIGUOUS
    assert warning_codes[3] == {AnswerKeyScanWarningCode.VERSION_INVALID}
    assert result.sheets[3].version.detected_version == "Z"
    assert warning_codes[4] == {AnswerKeyScanWarningCode.VERSION_NOT_DETECTED}
    assert result.sheets[4].version.status == AnswerKeyVersionDetectionStatus.MISSING


async def test_uses_q1_as_version_without_returning_it_as_an_answer(monkeypatch):
    scan_ids = ["scan-1"]
    marking = _marking(
        [("scan-1", [_mark("Q1", ["B"]), _mark("Q2", ["C"], confidence=0.75)])]
    )
    owner_id, _, _, _, _ = _configure(
        monkeypatch,
        question_config={"2": {"choices": ["A", "B", "C"]}},
        version_count=3,
        version_from_q1=True,
        scan_ids=scan_ids,
        marking=marking,
    )

    result = await extraction.extract_answer_key_scan(
        AsyncMock(),
        uuid4(),
        owner_id,
        files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(1))],
        question_count=1,
    )

    assert result.sheets[0].version.detected_version == "B"
    assert result.sheets[0].answers["2"].selected_choices == ["C"]
    assert "1" not in result.sheets[0].answers


@pytest.mark.parametrize(
    ("filename", "content_type", "pdf_bytes", "expected_code"),
    [
        ("key.txt", "application/pdf", b"not-pdf", "invalid_answer_key_scan_file"),
        ("key.pdf", "text/plain", b"not-pdf", "invalid_answer_key_scan_file"),
        ("key.pdf", "application/pdf", b"not-pdf", "invalid_answer_key_scan_file"),
        ("key.pdf", "application/pdf", b"", "invalid_answer_key_scan_file"),
    ],
)
def test_validates_pdf(filename, content_type, pdf_bytes, expected_code):
    with pytest.raises(BadRequestError) as exc_info:
        extraction._validate_pdf(filename, content_type, pdf_bytes)
    assert exc_info.value.code == expected_code


async def test_rejects_non_owner_before_using_omr(monkeypatch):
    owner_id, _, _, _, mocks = _configure(monkeypatch)

    with pytest.raises(ForbiddenError):
        await extraction.extract_answer_key_scan(
            AsyncMock(),
            uuid4(),
            uuid4(),
            files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(1))],
            question_count=1,
        )

    assert owner_id is not None
    mocks["upload"].assert_not_awaited()


async def test_validates_template_question_and_page_counts_before_omr(monkeypatch):
    owner_id, _, template, _, mocks = _configure(
        monkeypatch,
        question_config={"1": {"choices": ["A", "B"]}},
        pages_per_sheet=2,
    )

    with pytest.raises(BadRequestError) as question_error:
        await extraction.extract_answer_key_scan(
            AsyncMock(), uuid4(), owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(2))],
            question_count=2,
        )
    assert question_error.value.code == "invalid_answer_key_question_count"

    with pytest.raises(BadRequestError) as page_error:
        await extraction.extract_answer_key_scan(
            AsyncMock(), uuid4(), owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(3))],
            question_count=1,
        )
    assert page_error.value.code == "answer_key_scan_page_count_mismatch"

    template.omr_template_id = None
    with pytest.raises(BadRequestError) as template_error:
        await extraction.extract_answer_key_scan(
            AsyncMock(), uuid4(), owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(2))],
            question_count=1,
        )
    assert template_error.value.code == "omr_template_not_registered"
    mocks["upload"].assert_not_awaited()


async def test_cleans_up_when_marking_fails(monkeypatch):
    scan_ids = ["scan-1", "scan-2"]
    owner_id, _, _, _, mocks = _configure(
        monkeypatch,
        scan_ids=scan_ids,
        pages_per_sheet=1,
    )
    mocks["mark"].side_effect = OMRClientError("marking unavailable")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await extraction.extract_answer_key_scan(
            AsyncMock(),
            uuid4(),
            owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="keys.pdf", content_type="application/pdf", pdf_bytes=_pdf(2))],
            question_count=2,
        )

    assert exc_info.value.code == "answer_key_scan_omr_failed"
    mocks["delete"].assert_awaited_once_with(scan_ids)


async def test_rejects_partial_batch_and_cleans_up_processed_sheets(monkeypatch):
    owner_id, _, _, _, mocks = _configure(monkeypatch, scan_ids=["scan-1"])

    with pytest.raises(BadRequestError) as exc_info:
        await extraction.extract_answer_key_scan(
            AsyncMock(),
            uuid4(),
            owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="keys.pdf", content_type="application/pdf", pdf_bytes=_pdf(2))],
            question_count=2,
        )

    assert exc_info.value.code == "answer_key_scan_incomplete"
    mocks["mark"].assert_not_awaited()
    mocks["delete"].assert_awaited_once_with(["scan-1"])


async def test_cleanup_failure_is_reported_after_successful_extraction(monkeypatch):
    owner_id, _, _, _, mocks = _configure(monkeypatch)
    mocks["delete"].side_effect = OMRClientError("delete unavailable")

    with pytest.raises(ServiceUnavailableError) as exc_info:
        await extraction.extract_answer_key_scan(
            AsyncMock(),
            uuid4(),
            owner_id,
            files=[extraction.AnswerKeyScanUpload(filename="key.pdf", content_type="application/pdf", pdf_bytes=_pdf(1))],
            question_count=2,
        )

    assert exc_info.value.code == "answer_key_scan_cleanup_failed"
