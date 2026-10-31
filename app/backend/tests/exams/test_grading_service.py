"""Unit tests for services/grading_service.py."""
from unittest.mock import ANY, AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from errors.exceptions import BadRequestError, NotFoundError
from models.omr_detected_mark import MarkFieldType
from services.grading_service import (
    _answer_key_is_complete,
    _compute_scores,
    _identity_mismatch_flag_reason,
    _incomplete_answer_key_versions,
    _is_ambiguous,
    _name_confidence_flag_reason,
    _name_flag_reason,
    _score_question,
    _select_answer_key,
    _student_id_confidence_flag_reason,
    _student_id_flag_reason,
    _version_flag_reason,
    grade_marking,
)
from services.omr_mark_parsing import (
    detect_version,
    parse_question_selections,
)
from services.student_identity_decoder import DecodedField, DecodedIdentity
from services.student_matcher import IdentityMatchResult, MatchStatus, StudentMatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mark(
    field_index: int,
    detected_value: str | None,
    needs_review: bool = False,
    field_type: MarkFieldType = MarkFieldType.QUESTION,
):
    m = MagicMock()
    m.field_type = field_type
    m.field_index = field_index
    m.detected_value = detected_value
    m.needs_review = needs_review
    return m


def _version_mark(detected_value: str | None):
    return _mark(1, detected_value, field_type=MarkFieldType.VERSION)


def _answer_key(exam_version: str | None, answer_key: dict, scoring_rules: dict | None = None):
    k = MagicMock()
    k.id = uuid4()
    k.exam_version = exam_version
    k.answer_key = answer_key
    k.scoring_rules = scoring_rules
    return k


def _template(version: int = 1, version_from_q1: bool = False, n_versions: int = 1):
    t = MagicMock()
    t.id = uuid4()
    t.version = version
    t.version_from_q1 = version_from_q1
    t.n_versions = n_versions
    return t


def _marking(status: str = "completed", omr_template_id=None):
    m = MagicMock()
    m.id = uuid4()
    m.status = status
    m.omr_template_id = omr_template_id or uuid4()
    m.scan_id = uuid4()
    return m


def _scan(exam_id=None):
    s = MagicMock()
    s.id = uuid4()
    s.exam_id = exam_id or uuid4()
    return s


def _exam(course_id=None):
    e = MagicMock()
    e.id = uuid4()
    e.course_id = course_id or uuid4()
    return e


def _student():
    u = MagicMock()
    u.id = uuid4()
    return u


def _match_result(status: MatchStatus = MatchStatus.MATCHED, student=None):
    return StudentMatchResult(status=status, student=student)


def _identity_match_result(
    name_status: MatchStatus = MatchStatus.MATCHED,
    name_student=None,
    id_status: MatchStatus = MatchStatus.NO_MATCH,
    id_student=None,
    student_id_available: bool = False,
) -> IdentityMatchResult:
    return IdentityMatchResult(
        name=StudentMatchResult(status=name_status, student=name_student),
        student_id=StudentMatchResult(status=id_status, student=id_student),
        student_id_available=student_id_available,
    )


def _decoded_identity(
    first_name: str = "",
    first_name_ambiguous: bool = False,
    last_name: str = "",
    last_name_ambiguous: bool = False,
    student_id: str = "",
    student_id_ambiguous: bool = False,
) -> DecodedIdentity:
    return DecodedIdentity(
        first_name=DecodedField(value=first_name, ambiguous=first_name_ambiguous),
        last_name=DecodedField(value=last_name, ambiguous=last_name_ambiguous),
        student_id=DecodedField(value=student_id, ambiguous=student_id_ambiguous),
    )


_SINGLE_KEY = {
    "1": {"grading_type": "single", "correct_choices": ["A"], "points": 2.0},
    "2": {"grading_type": "single", "correct_choices": ["B"], "points": 2.0},
}

_MULTI_KEY = {
    "1": {"grading_type": "multiple", "correct_choices": ["A", "C"], "points": 3.0},
}

_PARTIAL_KEY = {
    "1": {
        "grading_type": "partial",
        "correct_choices": ["A", "B"],
        "points": 4.0,
        "partial_weights": {"A": 0.5, "B": 0.5},
    },
}


# ---------------------------------------------------------------------------
# answer-key readiness
# ---------------------------------------------------------------------------

class TestAnswerKeyReadiness:
    def test_complete_unversioned_key_is_ready(self):
        template = _template(n_versions=1)
        assert _incomplete_answer_key_versions(
            template, [_answer_key(None, _SINGLE_KEY)]
        ) == []

    def test_reports_missing_and_incomplete_versions(self):
        template = _template(n_versions=3)
        keys = [
            _answer_key("A", _SINGLE_KEY),
            _answer_key("B", {"1": {"grading_type": "single", "correct_choices": []}}),
        ]
        assert _incomplete_answer_key_versions(template, keys) == ["B", "C"]

    def test_empty_correct_choices_are_an_incomplete_draft(self):
        assert not _answer_key_is_complete(
            {"1": {"grading_type": "single", "correct_choices": []}}
        )


# ---------------------------------------------------------------------------
# parse_question_selections
# ---------------------------------------------------------------------------

class TestParseDetectedMarks:
    def test_single_choice(self):
        result = parse_question_selections([_mark(1, "A")])
        assert result == {1: ["A"]}

    def test_multi_choice_comma_separated(self):
        result = parse_question_selections([_mark(1, "A,C")])
        assert result == {1: ["A", "C"]}

    def test_null_value_maps_to_empty_list(self):
        result = parse_question_selections([_mark(1, None)])
        assert result == {1: []}

    def test_empty_string_maps_to_empty_list(self):
        result = parse_question_selections([_mark(1, "")])
        assert result == {1: []}

    def test_version_marks_excluded(self):
        result = parse_question_selections([_version_mark("B"), _mark(1, "A")])
        assert result == {1: ["A"]}

    def test_strips_whitespace(self):
        result = parse_question_selections([_mark(1, " A , C ")])
        assert result == {1: ["A", "C"]}


# ---------------------------------------------------------------------------
# detect_version
# ---------------------------------------------------------------------------

class TestDetectVersion:
    def test_returns_letter_when_version_present(self):
        assert detect_version([_version_mark("B")]) == "B"

    def test_returns_none_when_no_version_bubble(self):
        assert detect_version([_mark(1, "A")]) is None

    def test_returns_none_when_version_empty(self):
        assert detect_version([_version_mark(None)]) is None

    def test_finds_version_mark_among_question_marks(self):
        assert detect_version([_mark(1, "A"), _version_mark("C"), _mark(2, "B")]) == "C"


# ---------------------------------------------------------------------------
# _select_answer_key
# ---------------------------------------------------------------------------

class TestSelectAnswerKey:
    def test_exact_version_match(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _select_answer_key(keys, "B") is keys[1]

    def test_falls_back_to_default_when_version_not_found(self):
        default = _answer_key(None, {})
        keys = [_answer_key("A", {}), default]
        assert _select_answer_key(keys, "C") is default

    def test_falls_back_to_first_created_when_no_match_and_no_default(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _select_answer_key(keys, "C") is keys[0]

    def test_version_none_matches_default(self):
        default = _answer_key(None, {})
        assert _select_answer_key([default], None) is default

    def test_version_none_falls_back_to_first_created_when_no_default(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _select_answer_key(keys, None) is keys[0]

    def test_returns_none_when_no_answer_keys_exist(self):
        assert _select_answer_key([], "A") is None


# ---------------------------------------------------------------------------
# _version_flag_reason
# ---------------------------------------------------------------------------

class TestVersionFlagReason:
    def test_no_versioned_keys_never_flags(self):
        keys = [_answer_key(None, {})]
        assert _version_flag_reason(keys, None) is None
        assert _version_flag_reason(keys, "A") is None

    def test_versioned_keys_but_no_version_detected(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _version_flag_reason(keys, None) == "version_not_detected"

    def test_versioned_keys_with_unrecognized_version(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _version_flag_reason(keys, "C") == "version_not_recognized"

    def test_versioned_keys_with_matching_version_does_not_flag(self):
        keys = [_answer_key("A", {}), _answer_key("B", {})]
        assert _version_flag_reason(keys, "B") is None


# ---------------------------------------------------------------------------
# _name_flag_reason
# ---------------------------------------------------------------------------

class TestNameFlagReason:
    def test_matched_does_not_flag(self):
        assert _name_flag_reason(MatchStatus.MATCHED) is None

    def test_no_match_flags(self):
        assert _name_flag_reason(MatchStatus.NO_MATCH) == "name_no_match"

    def test_ambiguous_flags(self):
        assert _name_flag_reason(MatchStatus.AMBIGUOUS) == "name_ambiguous"


# ---------------------------------------------------------------------------
# _student_id_flag_reason
# ---------------------------------------------------------------------------

class TestStudentIdFlagReason:
    def test_unavailable_never_flags(self):
        result = _identity_match_result(id_status=MatchStatus.NO_MATCH, student_id_available=False)
        assert _student_id_flag_reason(result) is None

        result = _identity_match_result(id_status=MatchStatus.AMBIGUOUS, student_id_available=False)
        assert _student_id_flag_reason(result) is None

    def test_available_and_matched_does_not_flag(self):
        result = _identity_match_result(id_status=MatchStatus.MATCHED, student_id_available=True)
        assert _student_id_flag_reason(result) is None

    def test_available_and_no_match_flags(self):
        result = _identity_match_result(id_status=MatchStatus.NO_MATCH, student_id_available=True)
        assert _student_id_flag_reason(result) == "student_id_no_match"

    def test_available_and_ambiguous_flags(self):
        result = _identity_match_result(id_status=MatchStatus.AMBIGUOUS, student_id_available=True)
        assert _student_id_flag_reason(result) == "student_id_ambiguous"


# ---------------------------------------------------------------------------
# _identity_mismatch_flag_reason
# ---------------------------------------------------------------------------

class TestIdentityMismatchFlagReason:
    def test_same_student_does_not_flag(self):
        student = _student()
        result = _identity_match_result(
            name_status=MatchStatus.MATCHED, name_student=student,
            id_status=MatchStatus.MATCHED, id_student=student,
            student_id_available=True,
        )
        assert _identity_mismatch_flag_reason(result) is None

    def test_different_students_flags(self):
        result = _identity_match_result(
            name_status=MatchStatus.MATCHED, name_student=_student(),
            id_status=MatchStatus.MATCHED, id_student=_student(),
            student_id_available=True,
        )
        assert _identity_mismatch_flag_reason(result) == "identity_mismatch"

    def test_id_not_matched_does_not_flag(self):
        result = _identity_match_result(
            name_status=MatchStatus.MATCHED, name_student=_student(),
            id_status=MatchStatus.NO_MATCH,
            student_id_available=True,
        )
        assert _identity_mismatch_flag_reason(result) is None

    def test_name_not_matched_does_not_flag(self):
        result = _identity_match_result(
            name_status=MatchStatus.NO_MATCH,
            id_status=MatchStatus.MATCHED, id_student=_student(),
            student_id_available=True,
        )
        assert _identity_mismatch_flag_reason(result) is None


# ---------------------------------------------------------------------------
# _name_confidence_flag_reason
# ---------------------------------------------------------------------------

class TestNameConfidenceFlagReason:
    def test_no_ambiguity_does_not_flag(self):
        identity = _decoded_identity(first_name="Alice", last_name="Example")
        assert _name_confidence_flag_reason(identity) is None

    def test_ambiguous_first_name_flags(self):
        identity = _decoded_identity(first_name="Alice", first_name_ambiguous=True, last_name="Example")
        assert _name_confidence_flag_reason(identity) == "name_low_confidence"

    def test_ambiguous_last_name_flags(self):
        identity = _decoded_identity(first_name="Alice", last_name="Example", last_name_ambiguous=True)
        assert _name_confidence_flag_reason(identity) == "name_low_confidence"


# ---------------------------------------------------------------------------
# _student_id_confidence_flag_reason
# ---------------------------------------------------------------------------

class TestStudentIdConfidenceFlagReason:
    def test_unavailable_never_flags(self):
        identity = _decoded_identity(student_id="1234", student_id_ambiguous=True)
        result = _identity_match_result(student_id_available=False)
        assert _student_id_confidence_flag_reason(identity, result) is None

    def test_available_and_ambiguous_flags(self):
        identity = _decoded_identity(student_id="1234", student_id_ambiguous=True)
        result = _identity_match_result(student_id_available=True)
        assert _student_id_confidence_flag_reason(identity, result) == "student_id_low_confidence"

    def test_available_and_not_ambiguous_does_not_flag(self):
        identity = _decoded_identity(student_id="12345678")
        result = _identity_match_result(student_id_available=True)
        assert _student_id_confidence_flag_reason(identity, result) is None


# ---------------------------------------------------------------------------
# _score_question
# ---------------------------------------------------------------------------

class TestScoreQuestion:
    def test_single_correct(self):
        assert _score_question(["A"], ["A"], "single", 2.0, {}) == 2.0

    def test_single_wrong(self):
        assert _score_question(["B"], ["A"], "single", 2.0, {}) == 0.0

    def test_single_no_answer(self):
        assert _score_question([], ["A"], "single", 2.0, {}) == 0.0

    def test_multiple_all_correct(self):
        assert _score_question(["A", "C"], ["A", "C"], "multiple", 3.0, {}) == 3.0

    def test_multiple_missing_one(self):
        assert _score_question(["A"], ["A", "C"], "multiple", 3.0, {}) == 0.0

    def test_multiple_extra_wrong_selection(self):
        assert _score_question(["A", "B", "C"], ["A", "C"], "multiple", 3.0, {}) == 0.0

    def test_partial_full_credit(self):
        weights = {"A": 0.5, "B": 0.5}
        assert _score_question(["A", "B"], ["A", "B"], "partial", 4.0, weights) == 4.0

    def test_partial_half_credit(self):
        weights = {"A": 0.5, "B": 0.5}
        assert _score_question(["A"], ["A", "B"], "partial", 4.0, weights) == 2.0

    def test_partial_wrong_selection_not_penalised(self):
        weights = {"A": 0.5, "B": 0.5}
        # selecting C (wrong) gives 0 additional weight; only A counts
        assert _score_question(["A", "C"], ["A", "B"], "partial", 4.0, weights) == 2.0

    def test_partial_no_answer_zero(self):
        weights = {"A": 0.5, "B": 0.5}
        assert _score_question([], ["A", "B"], "partial", 4.0, weights) == 0.0

    def test_unknown_grading_type_scores_zero(self):
        assert _score_question(["A"], ["A"], "custom", 2.0, {}) == 0.0


# ---------------------------------------------------------------------------
# _is_ambiguous
# ---------------------------------------------------------------------------

class TestIsAmbiguous:
    def test_single_choice_multiple_marks_is_ambiguous(self):
        assert _is_ambiguous(["A", "B"], "single") is True

    def test_single_choice_one_mark_not_ambiguous(self):
        assert _is_ambiguous(["A"], "single") is False

    def test_single_choice_blank_not_ambiguous(self):
        assert _is_ambiguous([], "single") is False

    def test_multiple_choice_type_never_ambiguous(self):
        assert _is_ambiguous(["A", "B", "C"], "multiple") is False

    def test_partial_type_never_ambiguous(self):
        assert _is_ambiguous(["A", "B"], "partial") is False


# ---------------------------------------------------------------------------
# _compute_scores
# ---------------------------------------------------------------------------

class TestComputeScores:
    def test_all_correct(self):
        ak = _answer_key(None, _SINGLE_KEY)
        answers = {1: ["A"], 2: ["B"]}
        results, total, max_s = _compute_scores(answers, ak, 1.0)
        assert total == 4.0
        assert max_s == 4.0
        assert results["1"]["correct"] is True
        assert results["2"]["correct"] is True

    def test_all_wrong(self):
        ak = _answer_key(None, _SINGLE_KEY)
        answers = {1: ["B"], 2: ["A"]}
        results, total, max_s = _compute_scores(answers, ak, 1.0)
        assert total == 0.0
        assert max_s == 4.0
        assert all(r["correct"] is False for r in results.values())

    def test_no_student_answers_scores_zero(self):
        ak = _answer_key(None, _SINGLE_KEY)
        results, total, _ = _compute_scores({}, ak, 1.0)
        assert total == 0.0
        assert results["1"]["student_answers"] == []

    def test_multiple_marks_on_single_choice_flagged_ambiguous(self):
        ak = _answer_key(None, _SINGLE_KEY)
        answers = {1: ["A", "B"], 2: ["B"]}
        results, total, _ = _compute_scores(answers, ak, 1.0)
        assert results["1"]["ambiguous"] is True
        assert results["1"]["correct"] is False
        assert results["2"]["ambiguous"] is False

    def test_multiple_marks_on_multi_choice_not_ambiguous(self):
        ak = _answer_key(None, _MULTI_KEY)
        results, _, _ = _compute_scores({1: ["A", "B", "C"]}, ak, 1.0)
        assert results["1"]["ambiguous"] is False

    def test_default_points_used_when_not_in_key(self):
        key_without_points = {
            "1": {"grading_type": "single", "correct_choices": ["A"]},
        }
        ak = _answer_key(None, key_without_points)
        _, _, max_s = _compute_scores({1: ["A"]}, ak, 3.0)
        assert max_s == 3.0

    def test_partial_grading_half_score(self):
        ak = _answer_key(None, _PARTIAL_KEY)
        results, total, max_s = _compute_scores({1: ["A"]}, ak, 1.0)
        assert total == 2.0
        assert max_s == 4.0
        assert results["1"]["correct"] is False


# ---------------------------------------------------------------------------
# grade_marking (integration — all dependencies mocked)
# ---------------------------------------------------------------------------

class TestGradeMarking:
    @pytest.fixture
    def mock_db(self):
        db = AsyncMock()
        db.commit = AsyncMock()
        db.rollback = AsyncMock()
        # add() is synchronous on the real AsyncSession; AsyncMock() would
        # otherwise auto-generate an AsyncMock for it, leaving the coroutine
        # returned by db.add(entry) in grade_audit_entries.create_audit_entry
        # unawaited.
        db.add = MagicMock()
        return db

    @pytest.fixture(autouse=True)
    def mock_notifications(self):
        with (
            patch("services.grading_service.notify_course_staff", AsyncMock()) as mock_notify_staff,
            patch("services.grading_service.ensure_course_id_writable", AsyncMock()),
            patch(
                "services.grading_service.acquire_student_grade_lock",
                AsyncMock(),
            ),
            patch(
                "services.grading_service.student_has_grade_for_exam",
                AsyncMock(return_value=False),
            ),
        ):
            yield mock_notify_staff

    async def test_marking_not_found_raises_not_found(self, mock_db):
        with patch("services.grading_service.get_omr_marking_by_id", return_value=None):
            with pytest.raises(NotFoundError) as exc_info:
                await grade_marking(mock_db, uuid4())
        assert exc_info.value.code == "marking_not_found"

    async def test_marking_not_completed_raises_bad_request(self, mock_db):
        marking = _marking(status="processing")
        with patch("services.grading_service.get_omr_marking_by_id", return_value=marking):
            with pytest.raises(BadRequestError) as exc_info:
                await grade_marking(mock_db, marking.id)
        assert exc_info.value.code == "marking_not_completed"

    async def test_template_not_found_raises_not_found(self, mock_db):
        marking = _marking(status="completed")
        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=None),
        ):
            with pytest.raises(NotFoundError) as exc_info:
                await grade_marking(mock_db, marking.id)
        assert exc_info.value.code == "template_not_found"

    async def test_no_answer_key_raises_not_found(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=_exam())),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[]),
        ):
            with pytest.raises(NotFoundError) as exc_info:
                await grade_marking(mock_db, marking.id)
        assert exc_info.value.code == "answer_key_not_found"

    async def test_exam_not_found_raises_not_found(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=None)),
        ):
            with pytest.raises(NotFoundError) as exc_info:
                await grade_marking(mock_db, marking.id)
        assert exc_info.value.code == "exam_not_found"

    async def test_happy_path_single_question(self, mock_db, mock_notifications):
        mock_notify_staff = mock_notifications
        marking = _marking(status="completed")
        template = _template(version=2)
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY, {"default_points_per_question": 1.0})
        student = _student()
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[
                _mark(1, "A"),
                _mark(2, "B"),
            ]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=student)),
            ) as mock_match,
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            result = await grade_marking(mock_db, marking.id)

        assert result is fake_grade
        mock_db.commit.assert_awaited_once()
        mock_match.assert_awaited_once_with(mock_db, exam.course_id, ANY)
        # A "graded" result isn't shown to the student until the exam is
        # released (services/exam.py's release_exam sends grade_ready then) --
        # grading itself no longer notifies anyone for a clean match.
        mock_notify_staff.assert_not_awaited()
        call_kwargs = mock_create.call_args
        assert call_kwargs.kwargs["total_score"] == 4.0
        assert call_kwargs.kwargs["max_score"] == 4.0
        assert call_kwargs.kwargs["template_version"] == 2
        assert call_kwargs.kwargs["exam_answer_key_id"] == ak.id
        assert call_kwargs.kwargs["status"] == "graded"
        assert call_kwargs.kwargs["student_id"] == student.id
        assert call_kwargs.kwargs["flag_reason"] is None

    async def test_duplicate_student_scan_is_flagged_for_review(
        self, mock_db, mock_notifications
    ):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        answer_key = _answer_key(None, _SINGLE_KEY)
        student = _student()
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch(
                "services.grading_service.get_detected_marks",
                return_value=[_mark(1, "A"), _mark(2, "B")],
            ),
            patch(
                "services.grading_service.get_exam_template_by_omr_template_id",
                return_value=template,
            ),
            patch(
                "services.grading_service.get_scan_for_marking",
                AsyncMock(return_value=scan),
            ),
            patch(
                "services.grading_service.get_exam_by_id",
                AsyncMock(return_value=exam),
            ),
            patch(
                "services.grading_service.list_answer_keys_by_exam",
                return_value=[answer_key],
            ),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(
                    return_value=_identity_match_result(
                        name_status=MatchStatus.MATCHED,
                        name_student=student,
                    )
                ),
            ),
            patch(
                "services.grading_service.student_has_grade_for_exam",
                AsyncMock(return_value=True),
            ) as mock_has_grade,
            patch(
                "services.grading_service.acquire_student_grade_lock",
                AsyncMock(),
            ) as mock_lock,
            patch(
                "services.grading_service.create_grade",
                AsyncMock(return_value=fake_grade),
            ) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        mock_lock.assert_awaited_once_with(mock_db, exam.id, student.id)
        mock_has_grade.assert_awaited_once_with(mock_db, exam.id, student.id)
        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["student_id"] is None
        assert mock_create.call_args.kwargs["flag_reason"] == "duplicate_student_grade"
        mock_notifications.assert_awaited_once()

    async def test_version_detected_selects_correct_key(self, mock_db):
        marking = _marking(status="completed")
        template = _template(n_versions=2)
        scan = _scan()
        exam = _exam()
        key_a = _answer_key("A", _SINGLE_KEY)
        key_b = _answer_key("B", _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[
                _version_mark("B"),
                _mark(1, "A"),
                _mark(2, "B"),
            ]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[key_a, key_b]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=_student())),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["exam_answer_key_id"] == key_b.id
        assert mock_create.call_args.kwargs["status"] == "graded"

    async def test_version_from_q1_selects_correct_key(self, mock_db):
        """UBCO_100_BLUEPRINT + version_from_q1: no dedicated VERSION mark
        exists on the fixed sheet, so field_index 1 (an ordinary QUESTION
        mark) doubles as the version selector.
        """
        marking = _marking(status="completed")
        template = _template(version_from_q1=True, n_versions=2)
        scan = _scan()
        exam = _exam()
        key_a = _answer_key("A", _SINGLE_KEY)
        key_b = _answer_key("B", _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[
                _mark(1, "B"),  # version selector, physical Q1
                _mark(2, "A"),
            ]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[key_a, key_b]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=_student())),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["exam_answer_key_id"] == key_b.id
        assert mock_create.call_args.kwargs["status"] == "graded"

    async def test_db_error_triggers_rollback(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        mock_db.commit.side_effect = Exception("db error")

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=_student())),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=MagicMock())),
        ):
            with pytest.raises(Exception, match="db error"):
                await grade_marking(mock_db, marking.id)

        mock_db.rollback.assert_awaited_once()

    async def test_version_mismatch_flags_and_does_not_assign_student(self, mock_db):
        marking = _marking(status="completed")
        template = _template(n_versions=2)
        scan = _scan()
        exam = _exam()
        key_a = _answer_key("A", _SINGLE_KEY)
        key_b = _answer_key("B", _SINGLE_KEY)
        default_key = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[
                _version_mark("C"),  # doesn't match key_a, key_b, or (by definition) the default
                _mark(1, "A"),
                _mark(2, "B"),
            ]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[key_a, key_b, default_key]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=_student())),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "version_not_recognized"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_name_no_match_flags_and_does_not_assign_student(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.NO_MATCH)),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "name_no_match"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_needs_review_notifies_staff(self, mock_db, mock_notifications):
        mock_notify_staff = mock_notifications
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.NO_MATCH)),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)),
        ):
            await grade_marking(mock_db, marking.id)

        mock_notify_staff.assert_awaited_once()

    async def test_name_ambiguous_flags(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.AMBIGUOUS)),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "name_ambiguous"

    async def test_version_and_name_mismatch_combine_into_flag_reason(self, mock_db):
        marking = _marking(status="completed")
        template = _template(n_versions=2)
        scan = _scan()
        exam = _exam()
        key_a = _answer_key("A", _SINGLE_KEY)
        key_b = _answer_key("B", _SINGLE_KEY)
        default_key = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[key_a, key_b, default_key]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.NO_MATCH)),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["flag_reason"] == "version_not_detected,name_no_match"

    async def test_student_id_no_match_flags_when_roster_has_numbers(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=_student(),
                    id_status=MatchStatus.NO_MATCH,
                    student_id_available=True,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "student_id_no_match"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_student_id_mismatch_does_not_flag_when_roster_has_no_numbers(self, mock_db):
        """Rolling-out state: nobody on the roster has a student_number yet,
        so a blank/unmatched decoded id shouldn't block grading."""
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        student = _student()
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=student,
                    id_status=MatchStatus.NO_MATCH,
                    student_id_available=False,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "graded"
        assert mock_create.call_args.kwargs["flag_reason"] is None
        assert mock_create.call_args.kwargs["student_id"] == student.id

    async def test_student_id_ambiguous_flags(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=_student(),
                    id_status=MatchStatus.AMBIGUOUS,
                    student_id_available=True,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "student_id_ambiguous"

    async def test_identity_mismatch_flags_when_name_and_id_disagree(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[_mark(1, "A")]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=_student(),
                    id_status=MatchStatus.MATCHED, id_student=_student(),
                    student_id_available=True,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "identity_mismatch"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_name_and_id_both_match_same_student_assigns_and_grades(self, mock_db):
        marking = _marking(status="completed")
        template = _template(version=2)
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY, {"default_points_per_question": 1.0})
        student = _student()
        fake_grade = MagicMock()

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=[
                _mark(1, "A"),
                _mark(2, "B"),
            ]),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=student,
                    id_status=MatchStatus.MATCHED, id_student=student,
                    student_id_available=True,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "graded"
        assert mock_create.call_args.kwargs["flag_reason"] is None
        assert mock_create.call_args.kwargs["student_id"] == student.id

    async def test_ambiguous_name_decode_flags_even_when_matched(self, mock_db):
        """A low-confidence name bubble can still happen to decode to a real
        student's name — that's a lucky guess, not a reliable read, so it
        should still be flagged for review rather than silently graded."""
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        student = _student()
        fake_grade = MagicMock()

        detected_marks = [
            _mark(1, "A"),
            _mark(1, "S", field_type=MarkFieldType.LAST_NAME, needs_review=True),
        ]

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=detected_marks),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(name_status=MatchStatus.MATCHED, name_student=student)),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "name_low_confidence"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_ambiguous_student_id_decode_flags_when_roster_has_numbers(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        student = _student()
        fake_grade = MagicMock()

        detected_marks = [
            _mark(1, "A"),
            _mark(1, "1,2", field_type=MarkFieldType.STUDENT_ID),
        ]

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=detected_marks),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=student,
                    id_status=MatchStatus.MATCHED, id_student=student,
                    student_id_available=True,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "needs_review"
        assert mock_create.call_args.kwargs["flag_reason"] == "student_id_low_confidence"
        assert mock_create.call_args.kwargs["student_id"] is None

    async def test_ambiguous_student_id_decode_does_not_flag_when_roster_has_no_numbers(self, mock_db):
        marking = _marking(status="completed")
        template = _template()
        scan = _scan()
        exam = _exam()
        ak = _answer_key(None, _SINGLE_KEY)
        student = _student()
        fake_grade = MagicMock()

        detected_marks = [
            _mark(1, "A"),
            _mark(1, "1,2", field_type=MarkFieldType.STUDENT_ID),
        ]

        with (
            patch("services.grading_service.get_omr_marking_by_id", return_value=marking),
            patch("services.grading_service.get_detected_marks", return_value=detected_marks),
            patch("services.grading_service.get_exam_template_by_omr_template_id", return_value=template),
            patch("services.grading_service.get_scan_for_marking", AsyncMock(return_value=scan)),
            patch("services.grading_service.get_exam_by_id", AsyncMock(return_value=exam)),
            patch("services.grading_service.list_answer_keys_by_exam", return_value=[ak]),
            patch(
                "services.grading_service.match_student_identity_for_course",
                AsyncMock(return_value=_identity_match_result(
                    name_status=MatchStatus.MATCHED, name_student=student,
                    student_id_available=False,
                )),
            ),
            patch("services.grading_service.create_grade", AsyncMock(return_value=fake_grade)) as mock_create,
        ):
            await grade_marking(mock_db, marking.id)

        assert mock_create.call_args.kwargs["status"] == "graded"
        assert mock_create.call_args.kwargs["flag_reason"] is None
        assert mock_create.call_args.kwargs["student_id"] == student.id
