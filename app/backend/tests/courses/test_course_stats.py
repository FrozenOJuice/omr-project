from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from errors.exceptions import ForbiddenError, NotFoundError
from services.course_stats import get_course_stats


pytestmark = pytest.mark.db


@contextmanager
def _patches(*, course, user=None, rows=None):
    with ExitStack() as stack:
        stack.enter_context(
            patch("services.course_stats.get_course_by_id", AsyncMock(return_value=course))
        )
        stack.enter_context(
            patch("services.course_stats.get_user_by_id", AsyncMock(return_value=user))
        )
        stack.enter_context(
            patch(
                "services.course_stats.list_course_exam_grade_rows",
                AsyncMock(return_value=rows or []),
            )
        )
        yield


class TestGetCourseStats:
    async def test_course_not_found(self, db_session):
        with _patches(course=None):
            with pytest.raises(NotFoundError) as exc_info:
                await get_course_stats(db_session, uuid4(), uuid4())

        assert exc_info.value.code == "course_not_found"

    async def test_non_owner_is_forbidden(self, db_session):
        with _patches(
            course=SimpleNamespace(created_by=uuid4()),
            user=SimpleNamespace(role="professor"),
        ):
            with pytest.raises(ForbiddenError) as exc_info:
                await get_course_stats(db_session, uuid4(), uuid4())

        assert exc_info.value.code == "course_stats_forbidden"

    async def test_aggregates_and_compares_exam_percentages(self, db_session):
        course_id = uuid4()
        owner_id = uuid4()
        midterm_id = uuid4()
        final_id = uuid4()
        empty_id = uuid4()
        rows = [
            (midterm_id, "Midterm", 4.0, 10.0),
            (midterm_id, "Midterm", 6.0, 10.0),
            (midterm_id, "Midterm", 7.0, 10.0),
            (final_id, "Final", 8.0, 10.0),
            (final_id, "Final", 9.0, 10.0),
            (final_id, "Final", 9.0, 10.0),
            (empty_id, "Practice", None, None),
        ]

        with _patches(
            course=SimpleNamespace(created_by=owner_id),
            user=SimpleNamespace(role="professor"),
            rows=rows,
        ):
            stats = await get_course_stats(db_session, course_id, owner_id)

        assert stats.exam_count == 3
        assert stats.graded_count == 6
        assert stats.mean_percentage == 71.67
        assert stats.standard_deviation_percentage == 17.72
        assert stats.median_percentage == 75.0
        assert stats.mode_percentages == [90.0]
        assert stats.highest_percentage == 90.0
        assert stats.lowest_percentage == 40.0
        assert stats.distribution == {
            "<50": 1,
            "50-60": 0,
            "60-70": 1,
            "70-80": 1,
            "80-90": 1,
            "90-100": 2,
        }

        by_name = {exam.exam_name: exam for exam in stats.exams}
        assert by_name["Midterm"].mean_percentage == 56.67
        assert by_name["Midterm"].standard_deviation_percentage == 12.47
        assert by_name["Midterm"].median_percentage == 60.0
        assert by_name["Final"].mode_percentages == [90.0]
        assert by_name["Practice"].graded_count == 0
        assert by_name["Practice"].mean_percentage is None
        assert by_name["Practice"].standard_deviation_percentage is None

    async def test_admin_can_view_any_course(self, db_session):
        course_id = uuid4()
        with _patches(
            course=SimpleNamespace(created_by=uuid4()),
            user=SimpleNamespace(role="admin"),
        ):
            stats = await get_course_stats(db_session, course_id, uuid4())

        assert stats.course_id == course_id
        assert stats.exam_count == 0
