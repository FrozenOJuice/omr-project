"""Matches decoded student identity (name and student id) against a course's
enrolled students.
"""
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User
from services.course import list_enrolled_students
from services.student_identity_decoder import DecodedIdentity


class MatchStatus(StrEnum):
    MATCHED = "matched"
    NO_MATCH = "no_match"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class StudentMatchResult:
    status: MatchStatus
    student: User | None = None
    candidates: tuple[User, ...] = ()


@dataclass(frozen=True)
class IdentityMatchResult:
    name: StudentMatchResult
    student_id: StudentMatchResult
    # False if no one on the course roster has a student_number on file yet
    # (e.g. their account predates that field) — in that case there's
    # nothing meaningful to compare the decoded id against.
    student_id_available: bool


def match_candidates(matches: list[User]) -> StudentMatchResult:
    if len(matches) == 1:
        return StudentMatchResult(status=MatchStatus.MATCHED, student=matches[0])
    if matches:
        return StudentMatchResult(status=MatchStatus.AMBIGUOUS, candidates=tuple(matches))
    return StudentMatchResult(status=MatchStatus.NO_MATCH)


def match_student(candidates: list[User], decoded: DecodedIdentity) -> StudentMatchResult:
    """Matches decoded last/first name against a list of enrolled students."""
    decoded_first = decoded.first_name.value.strip().lower()
    decoded_last = decoded.last_name.value.strip().lower()

    if not decoded_first or not decoded_last:
        return StudentMatchResult(status=MatchStatus.NO_MATCH)

    matches = [
        user
        for user in candidates
        if user.first_name.lower() == decoded_first
        and user.last_name.lower() == decoded_last
    ]

    return match_candidates(matches)


def match_student_by_id(candidates: list[User], decoded: DecodedIdentity) -> StudentMatchResult:
    """Matches the decoded student id against a list of enrolled students."""
    decoded_number = decoded.student_id.value.strip()

    if not decoded_number:
        return StudentMatchResult(status=MatchStatus.NO_MATCH)

    matches = [user for user in candidates if user.student_number == decoded_number]

    return match_candidates(matches)


async def match_student_identity_for_course(
    db: AsyncSession, course_id: UUID, decoded: DecodedIdentity
) -> IdentityMatchResult:
    """Loads a course's enrolled students and matches decoded identity (name
    and student id) against them.
    """
    candidates = list(await list_enrolled_students(db, course_id))

    return IdentityMatchResult(
        name=match_student(candidates, decoded),
        student_id=match_student_by_id(candidates, decoded),
        student_id_available=any(user.student_number for user in candidates),
    )
