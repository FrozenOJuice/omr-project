"""Integration tests for repositories/exam_grades.py and repositories/omr_markings.py."""
import uuid
from datetime import datetime, timezone, timedelta

import pytest

from core.security import hash_password
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_template import ExamTemplate
from models.omr_detected_mark import MarkFieldType, OMRDetectedMark
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import User, UserRole
from repositories.exam_grades import (
    create_grade,
    get_grade_by_id,
    get_grade_by_omr_marking,
    list_grades_by_answer_key,
)
from repositories.omr_markings import (
    create_detected_marks,
    create_marking,
    get_detected_marks,
    get_omr_marking_by_id,
    update_marking_status,
)

pytestmark = pytest.mark.db

_QUESTION_RESULTS = {
    "1": {
        "grading_type": "single",
        "student_answers": ["A"],
        "correct_answers": ["A"],
        "correct": True,
        "score": 1.0,
        "max_score": 1.0,
    }
}


async def _seed(db_session):
    """Create the minimal chain: user → course → exam → template → omr_template → scan → marking → answer_key."""
    user = User(
        first_name="Grader",
        last_name="Example",
        email=f"grader_{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.PROFESSOR.value,
        status="active",
    )
    db_session.add(user)
    await db_session.flush()

    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=user.id)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Test Template",
        created_by=user.id,
        question_config={"1": {"choices": ["A", "B", "C"]}},
        total_questions=1,
        version=1,
        n_versions=4,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(
        course_id=course.id,
        created_by=user.id,
        name="Midterm",
        start_time=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        role="student",
        exam_template_id=template.id,
    )
    db_session.add(exam)
    await db_session.flush()

    omr_tmpl = OMRTemplate(name="OMR", page_count=2)
    db_session.add(omr_tmpl)
    await db_session.flush()

    scan = Scan(
        exam_id=exam.id,
        exam_template_id=template.id,
        uploader_user_id=user.id,
        path="scans/test.pdf",
    )
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(
        scan_id=scan.id, omr_template_id=omr_tmpl.id, status="completed"
    )
    db_session.add(marking)
    await db_session.flush()

    answer_key = ExamAnswerKey(
        exam_id=exam.id,
        exam_template_id=template.id,
        exam_version=None,
        answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
    )
    db_session.add(answer_key)
    await db_session.flush()

    return marking, answer_key, template, user


class TestOMRMarkingsRepo:
    async def test_get_marking_by_id(self, db_session):
        marking, *_ = await _seed(db_session)
        result = await get_omr_marking_by_id(db_session, marking.id)
        assert result is not None
        assert result.id == marking.id
        assert result.status == "completed"

    async def test_get_marking_not_found(self, db_session):
        result = await get_omr_marking_by_id(db_session, uuid.uuid4())
        assert result is None

    async def test_get_detected_marks_empty(self, db_session):
        marking, *_ = await _seed(db_session)
        marks = await get_detected_marks(db_session, marking.id)
        assert marks == []

    async def test_get_detected_marks_ordered(self, db_session):
        marking, *_ = await _seed(db_session)
        for q_num in (3, 1, 2):
            db_session.add(
                OMRDetectedMark(
                    marking_id=marking.id,
                    field_type=MarkFieldType.QUESTION,
                    field_index=q_num,
                    detected_value="A",
                )
            )
        await db_session.flush()
        marks = await get_detected_marks(db_session, marking.id)
        assert [m.field_index for m in marks] == [1, 2, 3]

    async def test_update_marking_status(self, db_session):
        marking, *_ = await _seed(db_session)
        updated = await update_marking_status(db_session, marking.id, "needs_review")
        assert updated is not None
        assert updated.status == "needs_review"

    async def test_update_marking_status_not_found(self, db_session):
        result = await update_marking_status(db_session, uuid.uuid4(), "failed")
        assert result is None

    async def test_update_marking_status_sets_started_at_on_processing(self, db_session):
        marking, *_ = await _seed(db_session)
        assert marking.started_at is None
        updated = await update_marking_status(db_session, marking.id, "processing")
        assert updated.started_at is not None

    async def test_update_marking_status_sets_finished_at_on_completed(self, db_session):
        marking, *_ = await _seed(db_session)
        assert marking.finished_at is None
        updated = await update_marking_status(db_session, marking.id, "completed")
        assert updated.finished_at is not None

    async def test_create_marking(self, db_session):
        marking, *_ = await _seed(db_session)
        new_marking = await create_marking(
            db_session, scan_id=marking.scan_id, omr_template_id=marking.omr_template_id
        )
        assert new_marking.id is not None
        assert new_marking.status == "pending"
        assert new_marking.scan_id == marking.scan_id
        assert new_marking.omr_template_id == marking.omr_template_id

    async def test_create_detected_marks(self, db_session):
        marking, *_ = await _seed(db_session)
        bounds_a = {"x": 0, "y": 15, "width": 200, "height": 40}
        bounds_l = {"x": 40, "y": 55, "width": 210, "height": 80}
        box_a = [{"label": "A", "selected": True, "x": 10, "y": 20, "width": 30, "height": 40}]
        box_l = [{"label": "L", "selected": True, "x": 50, "y": 60, "width": 70, "height": 80}]
        await create_detected_marks(
            db_session,
            marking.id,
            [
                (MarkFieldType.QUESTION, 1, "A", False, 0, bounds_a, box_a, 0.9),
                (MarkFieldType.LAST_NAME, 3, None, True, 1, bounds_l, box_l, 0.4),
            ],
        )
        marks = await get_detected_marks(db_session, marking.id)
        assert [
            (
                m.field_type, m.field_index, m.detected_value, m.needs_review,
                m.page_index, m.bounds, m.boxes, m.confidence_score,
            )
            for m in marks
        ] == [
            (MarkFieldType.LAST_NAME, 3, None, True, 1, bounds_l, box_l, 0.4),
            (MarkFieldType.QUESTION, 1, "A", False, 0, bounds_a, box_a, 0.9),
        ]


class TestExamGradesRepo:
    async def test_create_grade(self, db_session):
        marking, answer_key, template, _ = await _seed(db_session)
        grade = await create_grade(
            db_session,
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results=_QUESTION_RESULTS,
            total_score=1.0,
            max_score=1.0,
            template_version=template.version,
        )
        assert grade.id is not None
        assert grade.total_score == 1.0
        assert grade.max_score == 1.0
        assert grade.template_version == 1

    async def test_get_grade_by_id(self, db_session):
        marking, answer_key, template, _ = await _seed(db_session)
        grade = await create_grade(
            db_session,
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results=_QUESTION_RESULTS,
            total_score=1.0,
            max_score=1.0,
            template_version=template.version,
        )
        fetched = await get_grade_by_id(db_session, grade.id)
        assert fetched is not None
        assert fetched.id == grade.id

    async def test_get_grade_by_id_not_found(self, db_session):
        result = await get_grade_by_id(db_session, uuid.uuid4())
        assert result is None

    async def test_get_grade_by_omr_marking(self, db_session):
        marking, answer_key, template, _ = await _seed(db_session)
        grade = await create_grade(
            db_session,
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results=_QUESTION_RESULTS,
            total_score=1.0,
            max_score=1.0,
            template_version=template.version,
        )
        fetched = await get_grade_by_omr_marking(db_session, marking.id)
        assert fetched is not None
        assert fetched.id == grade.id

    async def test_get_grade_by_omr_marking_not_found(self, db_session):
        result = await get_grade_by_omr_marking(db_session, uuid.uuid4())
        assert result is None

    async def test_list_grades_by_answer_key(self, db_session):
        marking, answer_key, template, _ = await _seed(db_session)
        grade = await create_grade(
            db_session,
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results=_QUESTION_RESULTS,
            total_score=1.0,
            max_score=1.0,
            template_version=template.version,
        )
        grades = await list_grades_by_answer_key(db_session, answer_key.id)
        assert len(grades) == 1
        assert grades[0].id == grade.id

    async def test_list_grades_by_answer_key_empty(self, db_session):
        grades = await list_grades_by_answer_key(db_session, uuid.uuid4())
        assert grades == []

    async def test_unique_constraint_omr_marking(self, db_session):
        """Each OMR marking can only have one grade."""
        import sqlalchemy.exc
        marking, answer_key, template, _ = await _seed(db_session)
        await create_grade(
            db_session,
            omr_marking_id=marking.id,
            exam_answer_key_id=answer_key.id,
            question_results=_QUESTION_RESULTS,
            total_score=1.0,
            max_score=1.0,
            template_version=template.version,
        )
        with pytest.raises(sqlalchemy.exc.IntegrityError):
            await create_grade(
                db_session,
                omr_marking_id=marking.id,
                exam_answer_key_id=answer_key.id,
                question_results=_QUESTION_RESULTS,
                total_score=0.0,
                max_score=1.0,
                template_version=template.version,
            )
            await db_session.flush()
