"""Unit tests for semantic parsing shared by grading and key extraction."""
from unittest.mock import MagicMock

from models.omr_detected_mark import MarkFieldType
from schemas.omr_schema import DetectedQuestionMark
from services.omr_mark_parsing import (
    detect_version,
    detect_version_from_q1,
    parse_question_selections,
)


def _persisted_mark(
    field_type: MarkFieldType,
    field_index: int,
    detected_value: str | None,
):
    mark = MagicMock()
    mark.field_type = field_type
    mark.field_index = field_index
    mark.detected_value = detected_value
    return mark


def _raw_mark(question_id: str, selected: list[str]) -> DetectedQuestionMark:
    return DetectedQuestionMark.model_validate(
        {
            "questionId": question_id,
            "flagged": False,
            "selected": selected,
            "confidence": 0.91,
            "pageIndex": 0,
            "bounds": {"x": 1, "y": 2, "width": 3, "height": 4},
            "boxes": [],
        }
    )


def test_question_selections_support_persisted_marks():
    marks = [
        _persisted_mark(MarkFieldType.QUESTION, 2, " A , C "),
        _persisted_mark(MarkFieldType.VERSION, 1, "B"),
    ]
    assert parse_question_selections(marks) == {2: ["A", "C"]}


def test_question_selections_support_raw_omr_marks():
    marks = [_raw_mark("Q2", ["A", "C"]), _raw_mark("V1", ["B"])]
    assert parse_question_selections(marks) == {2: ["A", "C"]}


def test_normal_version_supports_both_mark_shapes():
    assert detect_version([_persisted_mark(MarkFieldType.VERSION, 1, "C")]) == "C"
    assert detect_version([_raw_mark("V1", ["D"])]) == "D"


def test_normal_version_rejects_ambiguous_selection():
    assert detect_version([_raw_mark("V1", ["A", "B"])]) is None


def test_q1_version_supports_both_mark_shapes():
    assert detect_version_from_q1(
        [_persisted_mark(MarkFieldType.QUESTION, 1, "B")]
    ) == "B"
    assert detect_version_from_q1([_raw_mark("Q1", ["E"])]) == "E"


def test_q1_version_rejects_blank_and_ambiguous_selection():
    assert detect_version_from_q1([_raw_mark("Q1", [])]) is None
    assert detect_version_from_q1([_raw_mark("Q1", ["A", "C"])]) is None
