from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from errors.exceptions import NotFoundError
from services.exam_stats import get_exam_stats


pytestmark = pytest.mark.db


def _grade_row(
    total_score: float,
    max_score: float,
    question_results: dict,
    exam_version: str | None = None,
):
    return (total_score, max_score, question_results, exam_version)


@contextmanager
def _patches(exam, course=None, user=None, grade_rows=None, template=None):
    with ExitStack() as stack:
        stack.enter_context(
            patch("services.exam_stats.get_exam_by_id", AsyncMock(return_value=exam))
        )
        stack.enter_context(
            patch("services.exam_stats.get_course_by_id", AsyncMock(return_value=course))
        )
        stack.enter_context(
            patch("services.exam_stats.get_user_by_id", AsyncMock(return_value=user))
        )
        stack.enter_context(
            patch(
                "services.exam_stats.list_exam_grade_rows",
                AsyncMock(return_value=grade_rows or []),
            )
        )
        stack.enter_context(
            patch("services.exam_stats.get_exam_template_by_id", AsyncMock(return_value=template))
        )
        yield


class TestGetExamStats:
    async def test_exam_not_found_raises_not_found(self, db_session):
        exam_id = uuid4()
        requesting_user_id = uuid4()

        with patch("services.exam_stats.get_exam_by_id", AsyncMock(return_value=None)):
            with pytest.raises(NotFoundError) as exc_info:
                await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert exc_info.value.code == "exam_not_found"

    async def test_empty_exam_returns_empty_stats(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)
        course = SimpleNamespace(created_by=requesting_user_id)
        user = SimpleNamespace(role="professor")

        with _patches(exam, course, user, []):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert stats.exam_id == exam_id
        assert stats.graded_count == 0
        assert stats.mean_score is None
        assert stats.standard_deviation_score is None
        assert stats.median_score is None
        assert stats.mode_scores == []
        assert stats.mean_percentage is None
        assert stats.standard_deviation_percentage is None
        assert stats.min_percentage is None
        assert stats.q1_percentage is None
        assert stats.median_percentage is None
        assert stats.q3_percentage is None
        assert stats.max_percentage is None
        assert stats.score_distribution == []
        assert stats.question_stats == []

    async def test_calculates_score_summary_and_question_stats(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)
        course = SimpleNamespace(created_by=requesting_user_id)
        user = SimpleNamespace(role="professor")
        rows = [
            _grade_row(
                8.0,
                10.0,
                {
                    "1": {
                        "student_answers": ["A"],
                        "correct_answers": ["A"],
                        "correct": True,
                        "score": 5.0,
                        "max_score": 5.0,
                    },
                    "2": {
                        "student_answers": ["D"],
                        "correct_answers": ["C"],
                        "correct": False,
                        "score": 3.0,
                        "max_score": 5.0,
                    },
                },
            ),
            _grade_row(
                6.0,
                10.0,
                {
                    "1": {
                        "student_answers": ["B"],
                        "correct_answers": ["A"],
                        "correct": False,
                        "score": 0.0,
                        "max_score": 5.0,
                    },
                    "2": {
                        "student_answers": ["C"],
                        "correct_answers": ["C"],
                        "correct": True,
                        "score": 5.0,
                        "max_score": 5.0,
                    },
                },
            ),
            _grade_row(
                8.0,
                10.0,
                {
                    "1": {
                        "student_answers": ["A"],
                        "correct_answers": ["A"],
                        "correct": True,
                        "score": 5.0,
                        "max_score": 5.0,
                    },
                    "2": {
                        "student_answers": [],
                        "correct_answers": ["C"],
                        "correct": False,
                        "score": 0.0,
                        "max_score": 5.0,
                    },
                },
            ),
        ]

        with _patches(exam, course, user, rows):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert stats.graded_count == 3
        assert stats.mean_score == 7.33
        assert stats.standard_deviation_score == 0.94
        assert stats.median_score == 8.0
        assert stats.mode_scores == [8.0]
        assert stats.mean_percentage == 73.33
        assert stats.standard_deviation_percentage == 9.43
        assert stats.min_percentage == 60.0
        assert stats.q1_percentage == 70.0
        assert stats.median_percentage == 80.0
        assert stats.q3_percentage == 80.0
        assert stats.max_percentage == 80.0
        nonempty_buckets = [
            bucket.model_dump() for bucket in stats.score_distribution if bucket.count > 0
        ]
        assert len(stats.score_distribution) == 10
        assert nonempty_buckets == [
            {
                "label": "60-69%",
                "lower_bound": 60,
                "upper_bound": 69,
                "count": 1,
                "percentage": 33.33,
            },
            {
                "label": "80-89%",
                "lower_bound": 80,
                "upper_bound": 89,
                "count": 2,
                "percentage": 66.67,
            },
        ]
        assert len(stats.version_stats) == 1
        assert stats.version_stats[0].exam_version is None
        assert stats.version_stats[0].graded_count == 3

        question_1 = stats.question_stats[0]
        assert question_1.question_number == "1"
        assert question_1.graded_count == 3
        assert question_1.correct_count == 2
        assert question_1.correct_percentage == 66.67
        assert question_1.incorrect_count == 1
        assert question_1.incorrect_percentage == 33.33
        assert question_1.average_score == 3.33
        assert question_1.max_score == 5.0
        assert question_1.selected_distribution == {"A": 2, "B": 1}
        assert question_1.item_difficulty == 0.67
        assert question_1.discrimination_index is None
        assert question_1.distractor_efficiency == 1.0
        assert [choice.model_dump() for choice in question_1.answer_choices] == [
            {
                "answer": "A",
                "selected_count": 2,
                "selected_percentage": 66.67,
                "is_correct": True,
                "high_group_percentage": None,
                "low_group_percentage": None,
                "effectiveness": "correct",
            },
            {
                "answer": "B",
                "selected_count": 1,
                "selected_percentage": 33.33,
                "is_correct": False,
                "high_group_percentage": None,
                "low_group_percentage": None,
                "effectiveness": "effective",
            },
        ]

        question_2 = stats.question_stats[1]
        assert question_2.question_number == "2"
        assert question_2.graded_count == 3
        assert question_2.correct_count == 1
        assert question_2.correct_percentage == 33.33
        assert question_2.average_score == 2.67
        assert question_2.max_score == 5.0
        assert question_2.selected_distribution == {"D": 1, "C": 1, "blank": 1}

    async def test_handles_multi_select_answers_as_one_distribution_bucket(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)
        course = SimpleNamespace(created_by=requesting_user_id)
        user = SimpleNamespace(role="professor")
        rows = [
            _grade_row(
                1.0,
                1.0,
                {
                    "1": {
                        "student_answers": ["A", "C"],
                        "correct_answers": ["A", "C"],
                        "correct": True,
                        "score": 1.0,
                        "max_score": 1.0,
                    },
                },
            ),
            _grade_row(
                0.0,
                1.0,
                {
                    "1": {
                        "student_answers": ["A"],
                        "correct_answers": ["A", "C"],
                        "correct": False,
                        "score": 0.0,
                        "max_score": 1.0,
                    },
                },
            ),
        ]

        with _patches(exam, course, user, rows):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert stats.question_stats[0].selected_distribution == {
            "A,C": 1,
            "A": 1,
        }
        assert {
            choice.answer: choice.selected_percentage
            for choice in stats.question_stats[0].answer_choices
        } == {"A": 100.0, "C": 50.0}

    async def test_calculates_discrimination_difficulty_and_distractor_analysis(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        template_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id, exam_template_id=template_id)
        course = SimpleNamespace(created_by=requesting_user_id)
        user = SimpleNamespace(role="professor")
        template = SimpleNamespace(
            question_config={"1": {"choices": ["A", "B", "C", "D"]}}
        )

        ranked_answers = [
            (10.0, "A", True),
            (9.0, "A", True),
            (8.0, "A", True),
            (7.0, "A", True),
            (6.0, "C", False),
            (5.0, "B", False),
            (4.0, "B", False),
            (3.0, "B", False),
        ]
        rows = [
            _grade_row(
                total_score,
                10.0,
                {
                    "1": {
                        "student_answers": [answer],
                        "correct_answers": ["A"],
                        "correct": correct,
                        "score": 1.0 if correct else 0.0,
                        "max_score": 1.0,
                    }
                },
            )
            for total_score, answer, correct in ranked_answers
        ]

        with _patches(exam, course, user, rows, template=template):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        question = stats.question_stats[0]
        assert question.correct_percentage == 50.0
        assert question.incorrect_percentage == 50.0
        assert question.item_difficulty == 0.5
        assert question.discrimination_index == 1.0
        assert question.distractor_efficiency == 0.33

        choices = {choice.answer: choice for choice in question.answer_choices}
        assert choices["A"].selected_percentage == 50.0
        assert choices["A"].is_correct is True
        assert choices["B"].selected_percentage == 37.5
        assert choices["B"].high_group_percentage == 0.0
        assert choices["B"].low_group_percentage == 100.0
        assert choices["B"].effectiveness == "effective"
        assert choices["C"].selected_percentage == 12.5
        assert choices["C"].effectiveness == "weak"
        assert choices["D"].selected_percentage == 0.0
        assert choices["D"].effectiveness == "not_selected"

    async def test_keeps_question_order_and_advanced_metrics_separate_by_version(
        self, db_session
    ):
        exam_id = uuid4()
        course_id = uuid4()
        template_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(
            id=exam_id,
            course_id=course_id,
            exam_template_id=template_id,
        )
        course = SimpleNamespace(created_by=requesting_user_id)
        user = SimpleNamespace(role="professor")
        template = SimpleNamespace(
            question_config={"1": {"choices": ["A", "B", "C", "D"]}},
            n_versions=2,
        )

        rows = []
        for total_score, correct in zip(
            [10.0, 9.0, 8.0, 7.0, 6.0, 5.0, 4.0, 3.0],
            [True, True, True, True, False, False, False, False],
        ):
            rows.append(
                _grade_row(
                    total_score,
                    10.0,
                    {
                        "1": {
                            "student_answers": ["A" if correct else "B"],
                            "correct_answers": ["A"],
                            "correct": correct,
                            "score": 1.0 if correct else 0.0,
                            "max_score": 1.0,
                        }
                    },
                    exam_version="A",
                )
            )

        version_b_correct = [True, False, False, False, False, False, False, True]
        for total_score, correct in zip(
            [9.5, 8.5, 7.5, 6.5, 5.5, 4.5, 3.5, 2.5],
            version_b_correct,
        ):
            rows.append(
                _grade_row(
                    total_score,
                    10.0,
                    {
                        "1": {
                            "student_answers": ["C" if correct else "B"],
                            "correct_answers": ["C"],
                            "correct": correct,
                            "score": 1.0 if correct else 0.0,
                            "max_score": 1.0,
                        }
                    },
                    exam_version="B",
                )
            )

        with _patches(exam, course, user, rows, template=template):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert [version.exam_version for version in stats.version_stats] == ["A", "B"]
        version_a, version_b = stats.version_stats
        assert version_a.graded_count == 8
        assert version_a.mean_percentage == 65.0
        assert version_a.average_item_difficulty == 0.5
        assert version_a.average_discrimination_index == 1.0
        assert version_a.difficult_question_count == 0
        assert version_a.low_discrimination_question_count == 0
        assert next(
            choice.answer
            for choice in version_a.question_stats[0].answer_choices
            if choice.is_correct
        ) == "A"

        assert version_b.graded_count == 8
        assert version_b.mean_percentage == 60.0
        assert version_b.average_item_difficulty == 0.25
        assert version_b.average_discrimination_index == 0.0
        assert version_b.difficult_question_count == 1
        assert version_b.low_discrimination_question_count == 1
        assert next(
            choice.answer
            for choice in version_b.question_stats[0].answer_choices
            if choice.is_correct
        ) == "C"

    async def test_course_not_found_raises_not_found(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)

        with _patches(exam, course=None, user=SimpleNamespace(role="professor")):
            with pytest.raises(NotFoundError) as exc_info:
                await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert exc_info.value.code == "course_not_found"

    async def test_non_owning_non_admin_user_is_forbidden(self, db_session):
        from errors.exceptions import ForbiddenError

        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        other_instructor_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)
        course = SimpleNamespace(created_by=other_instructor_id)
        user = SimpleNamespace(role="professor")

        with _patches(exam, course, user):
            with pytest.raises(ForbiddenError) as exc_info:
                await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert exc_info.value.code == "exam_stats_forbidden"

    async def test_admin_can_view_stats_for_any_course(self, db_session):
        exam_id = uuid4()
        course_id = uuid4()
        requesting_user_id = uuid4()
        other_instructor_id = uuid4()
        exam = SimpleNamespace(id=exam_id, course_id=course_id)
        course = SimpleNamespace(created_by=other_instructor_id)
        user = SimpleNamespace(role="admin")

        with _patches(exam, course, user, []):
            stats = await get_exam_stats(db_session, exam_id, requesting_user_id)

        assert stats.exam_id == exam_id
