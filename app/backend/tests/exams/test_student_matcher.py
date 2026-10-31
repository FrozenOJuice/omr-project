"""Unit tests for services/student_matcher.py."""
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from models.user import User
from services.student_identity_decoder import DecodedField, DecodedIdentity
from services.student_matcher import (
    MatchStatus,
    match_student,
    match_student_by_id,
    match_student_identity_for_course,
)


def _identity(first: str, last: str, student_id: str = "") -> DecodedIdentity:
    return DecodedIdentity(
        first_name=DecodedField(value=first, ambiguous=False),
        last_name=DecodedField(value=last, ambiguous=False),
        student_id=DecodedField(value=student_id, ambiguous=False),
    )


def _user(first_name: str, last_name: str, student_number: str | None = None) -> User:
    return User(
        id=uuid4(),
        first_name=first_name,
        last_name=last_name,
        email=f"{first_name}.{last_name}".replace(' ', '.').lower() + "@example.com",
        password_hash="hashed",
        role="student",
        student_number=student_number,
    )


class TestMatchStudent:
    def test_matches_single_candidate_case_insensitive(self):
        alice = _user("Alice", "Example")
        result = match_student([alice], _identity("alice", "example"))
        assert result.status == MatchStatus.MATCHED
        assert result.student is alice

    def test_no_candidates_returns_no_match(self):
        result = match_student([], _identity("Alice", "Example"))
        assert result.status == MatchStatus.NO_MATCH
        assert result.student is None

    def test_no_match_when_no_candidate_name_matches(self):
        result = match_student([_user("Bob", "Jones")], _identity("Alice", "Example"))
        assert result.status == MatchStatus.NO_MATCH

    def test_ambiguous_when_multiple_candidates_share_name(self):
        john1 = _user("John", "Smith")
        john2 = _user("John", "Smith")
        result = match_student([john1, john2], _identity("John", "Smith"))
        assert result.status == MatchStatus.AMBIGUOUS
        assert set(result.candidates) == {john1, john2}
        assert result.student is None

    def test_empty_decoded_last_name_returns_no_match(self):
        result = match_student([_user("Alice", "Example")], _identity("Alice", ""))
        assert result.status == MatchStatus.NO_MATCH

    def test_empty_decoded_first_name_returns_no_match(self):
        result = match_student([_user("Alice", "Example")], _identity("", "Example"))
        assert result.status == MatchStatus.NO_MATCH

    def test_whitespace_trimmed_before_comparison(self):
        alice = _user("Alice", "Example")
        result = match_student([alice], _identity("  Alice ", " Example  "))
        assert result.status == MatchStatus.MATCHED


class TestMatchStudentById:
    def test_matches_single_candidate(self):
        alice = _user("Alice", "Example", student_number="12345678")
        result = match_student_by_id([alice], _identity("Alice", "Example", "12345678"))
        assert result.status == MatchStatus.MATCHED
        assert result.student is alice

    def test_no_candidates_returns_no_match(self):
        result = match_student_by_id([], _identity("Alice", "Example", "12345678"))
        assert result.status == MatchStatus.NO_MATCH

    def test_no_match_when_no_candidate_id_matches(self):
        bob = _user("Bob", "Jones", student_number="99999999")
        result = match_student_by_id([bob], _identity("Alice", "Example", "12345678"))
        assert result.status == MatchStatus.NO_MATCH

    def test_no_match_when_decoded_id_empty(self):
        alice = _user("Alice", "Example", student_number="12345678")
        result = match_student_by_id([alice], _identity("Alice", "Example", ""))
        assert result.status == MatchStatus.NO_MATCH

    def test_no_match_against_candidates_without_student_number(self):
        alice = _user("Alice", "Example", student_number=None)
        result = match_student_by_id([alice], _identity("Alice", "Example", "12345678"))
        assert result.status == MatchStatus.NO_MATCH

    def test_ambiguous_when_multiple_candidates_share_id(self):
        # Shouldn't happen given the unique constraint, but the matcher
        # itself doesn't assume uniqueness.
        john1 = _user("John", "Smith", student_number="12345678")
        john2 = _user("John", "Impostor", student_number="12345678")
        result = match_student_by_id([john1, john2], _identity("John", "Smith", "12345678"))
        assert result.status == MatchStatus.AMBIGUOUS
        assert set(result.candidates) == {john1, john2}


class TestMatchStudentIdentityForCourse:
    async def test_loads_enrolled_students_and_matches_both(self):
        alice = _user("Alice", "Example", student_number="12345678")
        course_id = uuid4()
        mock_db = AsyncMock()

        with patch(
            "services.student_matcher.list_enrolled_students",
            AsyncMock(return_value=[alice]),
        ) as mock_list:
            result = await match_student_identity_for_course(
                mock_db, course_id, _identity("Alice", "Example", "12345678")
            )

        mock_list.assert_awaited_once_with(mock_db, course_id)
        assert result.name.status == MatchStatus.MATCHED
        assert result.name.student is alice
        assert result.student_id.status == MatchStatus.MATCHED
        assert result.student_id.student is alice
        assert result.student_id_available is True

    async def test_student_id_unavailable_when_roster_has_no_numbers(self):
        alice = _user("Alice", "Example", student_number=None)
        course_id = uuid4()
        mock_db = AsyncMock()

        with patch(
            "services.student_matcher.list_enrolled_students",
            AsyncMock(return_value=[alice]),
        ):
            result = await match_student_identity_for_course(
                mock_db, course_id, _identity("Alice", "Example", "12345678")
            )

        assert result.student_id_available is False
        assert result.student_id.status == MatchStatus.NO_MATCH

    async def test_student_id_available_if_any_candidate_has_a_number(self):
        alice = _user("Alice", "Example", student_number=None)
        bob = _user("Bob", "Jones", student_number="99999999")
        course_id = uuid4()
        mock_db = AsyncMock()

        with patch(
            "services.student_matcher.list_enrolled_students",
            AsyncMock(return_value=[alice, bob]),
        ):
            result = await match_student_identity_for_course(
                mock_db, course_id, _identity("Nobody", "Home", "00000000")
            )

        assert result.student_id_available is True
