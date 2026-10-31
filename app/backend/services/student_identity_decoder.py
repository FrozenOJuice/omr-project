"""Decodes grouped OMR name/ID bubble fields (L#/F#/I#) into strings.

Each field is a run of single-character bubbles (see app/omr/data/templates/README.md).
Trailing blanks are normal — a name shorter than the column count leaves the
remaining columns blank. A gap in the middle, a bubble with more than one
selection, or a low-confidence bubble (needs_review) makes the whole field
"ambiguous": a signal for the student-matching step to flag the exam rather
than trust the decoded value.
"""
from dataclasses import dataclass

from models.omr_detected_mark import MarkFieldType
from services.omr_field_ids import split_detected_value


@dataclass(frozen=True)
class DecodedField:
    value: str
    ambiguous: bool


@dataclass(frozen=True)
class DecodedIdentity:
    last_name: DecodedField
    first_name: DecodedField
    student_id: DecodedField


def _group_by_field_type(marks, field_type: MarkFieldType) -> dict[int, object]:
    return {mark.field_index: mark for mark in marks if mark.field_type == field_type}


def _decode_field(marks_by_index: dict[int, object]) -> DecodedField:
    if not marks_by_index:
        return DecodedField(value="", ambiguous=False)

    max_index = max(marks_by_index)
    positions = []
    for i in range(1, max_index + 1):
        mark = marks_by_index.get(i)
        if mark is None:
            positions.append(([], False))
        else:
            positions.append((split_detected_value(mark.detected_value), bool(mark.needs_review)))

    while positions and not positions[-1][0]:
        positions.pop()

    chars = []
    ambiguous = False
    for selected, needs_review in positions:
        if len(selected) == 1:
            chars.append(selected[0])
            ambiguous = ambiguous or needs_review
        else:
            chars.append("?")
            ambiguous = True

    return DecodedField(value="".join(chars), ambiguous=ambiguous)


def decode_identity_fields(marks) -> DecodedIdentity:
    """Decodes the LAST_NAME/FIRST_NAME/STUDENT_ID marks for one marking."""
    return DecodedIdentity(
        last_name=_decode_field(_group_by_field_type(marks, MarkFieldType.LAST_NAME)),
        first_name=_decode_field(_group_by_field_type(marks, MarkFieldType.FIRST_NAME)),
        student_id=_decode_field(_group_by_field_type(marks, MarkFieldType.STUDENT_ID)),
    )
