"""Shared answer-key readiness rules.

OMR registration is template-level technical state. Answer-key completeness is
exam-level grading state, so upload and grading checks must evaluate it
independently for the keys belonging to a particular exam.
"""
from string import ascii_uppercase


def answer_key_is_complete(answer_key: dict) -> bool:
    """Return whether every saved question has a gradeable correct answer."""
    if not answer_key:
        return False
    for item in answer_key.values():
        correct_choices = item.get("correct_choices", [])
        grading_type = item.get("grading_type", "single")
        if not correct_choices:
            return False
        if grading_type == "single" and len(correct_choices) != 1:
            return False
        if grading_type == "partial" and item.get("partial_weights") is None:
            return False
    return True


def incomplete_answer_key_versions(n_versions: int, answer_keys: list) -> list[str]:
    """List required versions that are missing or still incomplete drafts."""
    required_versions = (
        [None]
        if n_versions == 1
        else list(ascii_uppercase[:n_versions])
    )
    keys_by_version = {key.exam_version: key for key in answer_keys}
    return [
        version or "unversioned"
        for version in required_versions
        if version not in keys_by_version
        or not answer_key_is_complete(keys_by_version[version].answer_key)
    ]


def answer_keys_are_complete(n_versions: int, answer_keys: list) -> bool:
    return not incomplete_answer_key_versions(n_versions, answer_keys)
