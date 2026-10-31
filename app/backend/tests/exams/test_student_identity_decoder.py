"""Unit tests for services/student_identity_decoder.py."""
from unittest.mock import MagicMock

from models.omr_detected_mark import MarkFieldType
from services.student_identity_decoder import DecodedField, decode_identity_fields


def _mark(field_type, field_index, detected_value, needs_review=False):
    m = MagicMock()
    m.field_type = field_type
    m.field_index = field_index
    m.detected_value = detected_value
    m.needs_review = needs_review
    return m


def _last_name(*letters, needs_review_at=None):
    """Builds L1..Ln marks from a sequence of letters (None means blank)."""
    needs_review_at = needs_review_at or set()
    return [
        _mark(MarkFieldType.LAST_NAME, i, letter, needs_review=(i in needs_review_at))
        for i, letter in enumerate(letters, start=1)
        if letter is not None
    ]


class TestDecodeIdentityFields:
    def test_no_marks_yields_empty_fields(self):
        result = decode_identity_fields([])
        assert result.last_name == DecodedField(value="", ambiguous=False)
        assert result.first_name == DecodedField(value="", ambiguous=False)
        assert result.student_id == DecodedField(value="", ambiguous=False)

    def test_clean_last_name_with_trailing_blanks(self):
        marks = _last_name("S", "M", "I", "T", "H", None, None, None, None, None)
        result = decode_identity_fields(marks)
        assert result.last_name == DecodedField(value="SMITH", ambiguous=False)

    def test_short_first_name_with_trailing_blanks(self):
        marks = [_mark(MarkFieldType.FIRST_NAME, i, letter) for i, letter in enumerate(["J", "O", "E"], start=1)]
        result = decode_identity_fields(marks)
        assert result.first_name == DecodedField(value="JOE", ambiguous=False)

    def test_student_id_digits(self):
        digits = ["1", "2", "3", "4", "5", "6", "7", "8"]
        marks = [_mark(MarkFieldType.STUDENT_ID, i, d) for i, d in enumerate(digits, start=1)]
        result = decode_identity_fields(marks)
        assert result.student_id == DecodedField(value="12345678", ambiguous=False)

    def test_all_blank_field_is_empty_not_ambiguous(self):
        marks = [_mark(MarkFieldType.LAST_NAME, i, None) for i in range(1, 6)]
        result = decode_identity_fields(marks)
        assert result.last_name == DecodedField(value="", ambiguous=False)

    def test_interior_blank_marks_field_ambiguous(self):
        marks = _last_name("S", None, "I", "T", "H")
        result = decode_identity_fields(marks)
        assert result.last_name.value == "S?ITH"
        assert result.last_name.ambiguous is True

    def test_multi_selection_position_marks_ambiguous(self):
        marks = [
            _mark(MarkFieldType.LAST_NAME, 1, "S"),
            _mark(MarkFieldType.LAST_NAME, 2, "M,N"),
            _mark(MarkFieldType.LAST_NAME, 3, "I"),
        ]
        result = decode_identity_fields(marks)
        assert result.last_name.value == "S?I"
        assert result.last_name.ambiguous is True

    def test_needs_review_on_single_selection_still_ambiguous(self):
        marks = _last_name("S", "M", "I", needs_review_at={2})
        result = decode_identity_fields(marks)
        assert result.last_name.value == "SMI"
        assert result.last_name.ambiguous is True

    def test_missing_position_within_range_treated_as_blank_and_ambiguous(self):
        marks = [
            _mark(MarkFieldType.LAST_NAME, 1, "S"),
            _mark(MarkFieldType.LAST_NAME, 3, "I"),
        ]
        result = decode_identity_fields(marks)
        assert result.last_name.value == "S?I"
        assert result.last_name.ambiguous is True

    def test_ignores_unrelated_field_types(self):
        marks = [
            _mark(MarkFieldType.QUESTION, 1, "A"),
            _mark(MarkFieldType.VERSION, 1, "B"),
            *_last_name("S", "M", "I", "T", "H"),
        ]
        result = decode_identity_fields(marks)
        assert result.last_name.value == "SMITH"
        assert result.first_name == DecodedField(value="", ambiguous=False)
        assert result.student_id == DecodedField(value="", ambiguous=False)
