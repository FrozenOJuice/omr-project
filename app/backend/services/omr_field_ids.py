"""Parses OMR questionIds (e.g. "Q7", "V1", "L3") into (field_type, field_index).

Prefix convention, per app/omr/data/templates/README.md:
  Q# -> answer question, V# -> version selector, L# -> last name character,
  F# -> first name character, I# -> student id digit.
"""
import re

from models.omr_detected_mark import MarkFieldType

_PATTERN = re.compile(r"^([A-Za-z])(\d+)$")

_FIELD_TYPE_BY_PREFIX = {
    "Q": MarkFieldType.QUESTION,
    "V": MarkFieldType.VERSION,
    "L": MarkFieldType.LAST_NAME,
    "F": MarkFieldType.FIRST_NAME,
    "I": MarkFieldType.STUDENT_ID,
}


def parse_question_id(question_id: str) -> tuple[MarkFieldType, int]:
    """Splits a questionId like "L3" into (MarkFieldType.LAST_NAME, 3)."""
    match = _PATTERN.match(question_id)
    if not match:
        raise ValueError(f"Unrecognized question id format: {question_id!r}")

    prefix, index = match.group(1).upper(), int(match.group(2))
    field_type = _FIELD_TYPE_BY_PREFIX.get(prefix)
    if field_type is None:
        raise ValueError(f"Unknown question id prefix {prefix!r} in {question_id!r}")

    return field_type, index


def split_detected_value(detected_value: str | None) -> list[str]:
    """Splits an OMRDetectedMark's comma-separated detected_value, e.g. "A,C" -> ["A", "C"]."""
    if not detected_value:
        return []
    return [v.strip() for v in detected_value.split(",") if v.strip()]
