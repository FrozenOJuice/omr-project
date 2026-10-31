from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from errors.exceptions import BadRequestError, ForbiddenError
from schemas.course_comparison import CourseComparisonUpdate, ExamMappingOverride
from services.course_comparisons import create_comparison, update_comparison


@pytest.mark.asyncio
async def test_create_pairs_exams_by_creation_order(db_session):
    user = SimpleNamespace(id=uuid4(), role="professor")
    base = SimpleNamespace(id=uuid4(), created_by=user.id)
    historical = SimpleNamespace(id=uuid4(), created_by=user.id)
    base_exams = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    historical_exams = [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]
    created = SimpleNamespace(id=uuid4())

    with (
        patch("services.course_comparisons._courses_for_comparison", AsyncMock(return_value=(base, historical))),
        patch("services.course_comparisons.comparisons_repo.get_pair", AsyncMock(return_value=None)),
        patch("services.course_comparisons.comparisons_repo.list_exams_ordered", AsyncMock(side_effect=[base_exams, historical_exams])),
        patch("services.course_comparisons.comparisons_repo.create", AsyncMock(return_value=created)) as create_mock,
        patch("services.course_comparisons.comparisons_repo.get_by_id", AsyncMock(return_value=created)),
        patch("services.course_comparisons._response", AsyncMock(return_value="response")),
    ):
        result = await create_comparison(db_session, base.id, historical.id, user)

    assert result == "response"
    assert create_mock.await_args.args[4] == [
        (base_exams[0].id, historical_exams[0].id),
        (base_exams[1].id, historical_exams[1].id),
        (base_exams[2].id, None),
    ]


@pytest.mark.asyncio
async def test_create_rejects_course_not_owned_by_professor(db_session):
    user = SimpleNamespace(id=uuid4(), role="professor")
    base = SimpleNamespace(id=uuid4(), created_by=user.id)
    historical = SimpleNamespace(id=uuid4(), created_by=uuid4())

    with patch("services.course_comparisons.get_course_by_id", AsyncMock(side_effect=[base, historical])):
        with pytest.raises(ForbiddenError) as exc_info:
            await create_comparison(db_session, base.id, historical.id, user)

    assert exc_info.value.code == "course_comparison_forbidden"


@pytest.mark.asyncio
async def test_update_rejects_exam_from_another_course(db_session):
    user = SimpleNamespace(id=uuid4(), role="professor")
    base = SimpleNamespace(id=uuid4(), created_by=user.id)
    historical = SimpleNamespace(id=uuid4(), created_by=user.id)
    base_exam = SimpleNamespace(id=uuid4())
    historical_exam = SimpleNamespace(id=uuid4())
    comparison = SimpleNamespace(id=uuid4(), mappings=[])
    request = CourseComparisonUpdate(mappings=[ExamMappingOverride(base_exam_id=base_exam.id, comparison_exam_id=uuid4())])

    with (
        patch("services.course_comparisons._authorized_comparison", AsyncMock(return_value=(comparison, base, historical))),
        patch("services.course_comparisons.comparisons_repo.list_exams_ordered", AsyncMock(side_effect=[[base_exam], [historical_exam]])),
    ):
        with pytest.raises(BadRequestError) as exc_info:
            await update_comparison(db_session, base.id, comparison.id, request, user)

    assert exc_info.value.code == "invalid_exam_mapping"
