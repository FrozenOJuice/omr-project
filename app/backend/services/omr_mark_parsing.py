"""Shared semantic parsing for persisted and raw OMR marks.

Student grading reads ``OMRDetectedMark`` rows after they have been persisted,
while answer-key scan extraction reads ``DetectedQuestionMark`` objects directly
from the OMR service.  The public helpers in this module intentionally accept
both shapes so those workflows agree on question and version interpretation.
"""
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from models.omr_detected_mark import MarkFieldType
from services.omr_field_ids import parse_question_id, split_detected_value


class PersistedMark(Protocol):
    field_type: str
    field_index: int
    detected_value: str | None


class RawOMRMark(Protocol):
    question_id: str
    selected: list[str]


MarkLike = PersistedMark | RawOMRMark


@dataclass(frozen=True)
class ParsedOMRMark:
    field_type: MarkFieldType
    field_index: int
    selected_choices: tuple[str, ...]


def _parse_mark(mark: MarkLike) -> ParsedOMRMark:
    """Normalize either backend mark representation into one semantic shape."""
    question_id = getattr(mark, "question_id", None)
    if isinstance(question_id, str):
        field_type, field_index = parse_question_id(question_id)
        selected_choices = tuple(mark.selected)
    else:
        field_type = MarkFieldType(mark.field_type)
        field_index = mark.field_index
        selected_choices = tuple(split_detected_value(mark.detected_value))

    return ParsedOMRMark(
        field_type=field_type,
        field_index=field_index,
        selected_choices=selected_choices,
    )


def _parsed_marks(marks: Iterable[MarkLike]) -> Iterable[ParsedOMRMark]:
    return (_parse_mark(mark) for mark in marks)


def parse_question_selections(marks: Iterable[MarkLike]) -> dict[int, list[str]]:
    """Return ``{question_number: selected choices}`` for answer questions."""
    return {
        mark.field_index: list(mark.selected_choices)
        for mark in _parsed_marks(marks)
        if mark.field_type == MarkFieldType.QUESTION
    }


def detect_version(marks: Iterable[MarkLike]) -> str | None:
    """Return the dedicated version selection when exactly one choice is marked."""
    for mark in _parsed_marks(marks):
        if mark.field_type == MarkFieldType.VERSION:
            return mark.selected_choices[0] if len(mark.selected_choices) == 1 else None
    return None


def detect_version_from_q1(marks: Iterable[MarkLike]) -> str | None:
    """Return the UBC blueprint version encoded in physical question 1.

    The UBC sheet has no dedicated version field. When ``version_from_q1`` is
    enabled, its first ordinary question row is reserved for this purpose.
    """
    for mark in _parsed_marks(marks):
        if mark.field_type == MarkFieldType.QUESTION and mark.field_index == 1:
            return mark.selected_choices[0] if len(mark.selected_choices) == 1 else None
    return None
