"""Contract tests for answer-key scan extraction and matching schemas."""
import pytest
from pydantic import ValidationError

from schemas.exam_answer_keys import (
    AnswerKeyScanMatchAction,
    AnswerKeyVersionDetection,
    ConfirmAnswerKeyScanMatchesRequest,
    ExtractAnswerKeyScanBatchRequest,
    ExtractedAnswerKeySheet,
)


def _detected_version(version: str = "A") -> dict:
    return {
        "status": "detected",
        "selected_choices": [version],
        "detected_version": version,
        "confidence": 0.95,
    }


def test_batch_request_constrains_question_count():
    assert ExtractAnswerKeyScanBatchRequest(question_count=80).question_count == 80
    with pytest.raises(ValidationError):
        ExtractAnswerKeyScanBatchRequest(question_count=0)
    with pytest.raises(ValidationError):
        ExtractAnswerKeyScanBatchRequest(question_count=201)


def test_extracted_sheet_contains_answers_version_confidence_and_warnings():
    sheet = ExtractedAnswerKeySheet.model_validate(
        {
            "sheet_index": 0,
            "source_filename": "keys.pdf",
            "page_start": 1,
            "page_end": 2,
            "answers": {
                "2": {
                    "selected_choices": ["C"],
                    "confidence": 0.92,
                    "flagged": False,
                }
            },
            "version": _detected_version("B"),
            "minimum_confidence": 0.81,
            "warnings": [
                {
                    "code": "blank_answer",
                    "message": "No answer was detected.",
                    "question_id": "3",
                    "selected_choices": [],
                    "confidence": 0.41,
                }
            ],
        }
    )
    assert sheet.version.detected_version == "B"
    assert sheet.answers["2"].selected_choices == ["C"]
    assert sheet.warnings[0].question_id == "3"


def test_version_detection_requires_consistent_status():
    with pytest.raises(ValidationError):
        AnswerKeyVersionDetection.model_validate(
            {
                "status": "detected",
                "selected_choices": ["A", "B"],
                "detected_version": "A",
            }
        )
    with pytest.raises(ValidationError):
        AnswerKeyVersionDetection.model_validate(
            {
                "status": "ambiguous",
                "selected_choices": ["A"],
                "detected_version": None,
            }
        )


def test_confirmation_enforces_one_sheet_per_version():
    payload = ConfirmAnswerKeyScanMatchesRequest.model_validate(
        {
            "matching_mode": "manual",
            "matches": [
                {"sheet_index": 0, "action": "apply", "target_version": "a"},
                {"sheet_index": 1, "action": "skip", "target_version": None},
            ],
        }
    )
    assert payload.matches[0].target_version == "A"
    assert payload.matches[1].action == AnswerKeyScanMatchAction.SKIP

    with pytest.raises(ValidationError):
        ConfirmAnswerKeyScanMatchesRequest.model_validate(
            {
                "matching_mode": "ordered",
                "matches": [
                    {"sheet_index": 0, "action": "apply", "target_version": "A"},
                    {"sheet_index": 1, "action": "apply", "target_version": "A"},
                ],
            }
        )


def test_skipped_sheet_cannot_target_a_version():
    with pytest.raises(ValidationError):
        ConfirmAnswerKeyScanMatchesRequest.model_validate(
            {
                "matching_mode": "manual",
                "matches": [
                    {"sheet_index": 0, "action": "skip", "target_version": "A"}
                ],
            }
        )
