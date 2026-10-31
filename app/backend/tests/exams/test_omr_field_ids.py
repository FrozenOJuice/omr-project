"""Unit tests for services/omr_field_ids.py."""
import pytest

from models.omr_detected_mark import MarkFieldType
from services.omr_field_ids import parse_question_id


class TestParseQuestionId:
    @pytest.mark.parametrize(
        "question_id,expected_type,expected_index",
        [
            ("Q1", MarkFieldType.QUESTION, 1),
            ("Q42", MarkFieldType.QUESTION, 42),
            ("V1", MarkFieldType.VERSION, 1),
            ("L1", MarkFieldType.LAST_NAME, 1),
            ("L15", MarkFieldType.LAST_NAME, 15),
            ("F10", MarkFieldType.FIRST_NAME, 10),
            ("I8", MarkFieldType.STUDENT_ID, 8),
        ],
    )
    def test_parses_valid_ids(self, question_id, expected_type, expected_index):
        field_type, index = parse_question_id(question_id)
        assert field_type == expected_type
        assert index == expected_index

    def test_lowercase_prefix_accepted(self):
        field_type, index = parse_question_id("q7")
        assert field_type == MarkFieldType.QUESTION
        assert index == 7

    @pytest.mark.parametrize(
        "question_id",
        ["", "Q", "1", "Q1A", "X1", "QQ1", "Q-1", "Q1.5"],
    )
    def test_rejects_malformed_ids(self, question_id):
        with pytest.raises(ValueError):
            parse_question_id(question_id)

    def test_rejects_unknown_prefix(self):
        with pytest.raises(ValueError):
            parse_question_id("Z3")
