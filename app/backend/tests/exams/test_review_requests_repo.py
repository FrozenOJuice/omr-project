"""Integration tests for repositories/review_requests.py."""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from core.security import hash_password
from errors.exceptions import BadRequestError, ForbiddenError
from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.enrolment import Enrolment
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.grade_audit_entry import GradeAuditEntry
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.review_request_audit_entry import ReviewRequestAuditEntry
from models.scan import Scan
from models.user import User, UserRole
from repositories.notifications import count_unread
from repositories.review_requests import (
    create_review_request,
    get_review_request_by_id,
    list_by_grade,
    list_by_student,
    list_for_staff,
    update_review_request,
)

pytestmark = pytest.mark.db

_QUESTION_RESULTS = {
    "1": {
        "grading_type": "single",
        "student_answers": ["B"],
        "correct_answers": ["A"],
        "correct": False,
        "score": 0.0,
        "max_score": 1.0,
    }
}

# For tests that need a real multi-question batch, so each question's own
# current_score/proposed_score/correct can differ from its siblings'.
_TWO_QUESTION_RESULTS = {
    **_QUESTION_RESULTS,
    "2": {
        "grading_type": "single",
        "student_answers": ["A"],
        "correct_answers": ["A"],
        "correct": True,
        "score": 1.0,
        "max_score": 1.0,
    },
}


async def _seed(db_session, question_results=None):
    """Create the minimal chain up to ExamGrade, return (grade, student, answer_key)."""
    prof = User(
        first_name="Prof",
        last_name="Example",
        email=f"prof_{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.PROFESSOR.value,
        status="active",
    )
    student = User(
        first_name="Student",
        last_name="Example",
        email=f"student_{uuid.uuid4().hex[:6]}@test.com",
        password_hash=hash_password("Password123!"),
        role=UserRole.STUDENT.value,
        status="active",
    )
    db_session.add_all([prof, student])
    await db_session.flush()

    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=prof.id)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Test Template",
        created_by=prof.id,
        question_config={"1": {"choices": ["A", "B", "C"]}},
        total_questions=1,
        version=1,
        n_versions=4,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(
        course_id=course.id,
        created_by=prof.id,
        name="Midterm",
        start_time=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
        role="student",
        exam_template_id=template.id,
        released=True,
    )
    db_session.add(exam)
    await db_session.flush()

    omr_tmpl = OMRTemplate(name="OMR", page_count=2)
    db_session.add(omr_tmpl)
    await db_session.flush()

    scan = Scan(
        exam_id=exam.id,
        exam_template_id=template.id,
        uploader_user_id=prof.id,
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
        answer_key={"1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0}},
    )
    db_session.add(answer_key)
    await db_session.flush()

    resolved_question_results = question_results or _QUESTION_RESULTS
    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results=resolved_question_results,
        total_score=round(sum(r["score"] for r in resolved_question_results.values()), 4),
        max_score=round(sum(r["max_score"] for r in resolved_question_results.values()), 4),
        template_version=1,
    )
    db_session.add(grade)
    await db_session.flush()

    return grade, student, prof, answer_key


async def _create(db_session, grade, student, question_number="1", comment=None, proposed_score=1.0):
    """Creates a single-question review request and returns that one row."""
    reviews = await create_review_request(
        db_session,
        exam_grade_id=grade.id,
        student_id=student.id,
        question_numbers=[question_number],
        student_comment=comment,
        proposed_scores={question_number: proposed_score} if proposed_score is not None else {},
    )
    return reviews[0]


class TestReviewRequestsRepo:
    async def test_create_review_request(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1"],
            student_comment="I think A is wrong.",
            proposed_scores={"1": 1.0},
        )
        assert len(reviews) == 1
        review = reviews[0]
        assert review.id is not None
        assert review.status == "pending"
        assert review.question_number == "1"
        assert review.student_comment == "I think A is wrong."
        assert review.proposed_score == 1.0
        assert review.batch_id is None
        assert review.resolved_at is None

    async def test_create_review_request_batches_multiple_questions(self, db_session):
        grade, student, _prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1", "2"],
            student_comment="Both look wrong.",
            proposed_scores={"1": 1.0, "2": 1.0},
        )
        assert len(reviews) == 2
        assert reviews[0].batch_id is not None
        assert reviews[0].batch_id == reviews[1].batch_id
        assert {r.question_number for r in reviews} == {"1", "2"}

    async def test_create_review_request_batch_has_independent_proposed_scores(self, db_session):
        grade, student, _prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1", "2"],
            student_comment="Different amounts of credit for each.",
            proposed_scores={"1": 1.0, "2": 0.5},
        )
        by_question = {r.question_number: r for r in reviews}
        assert by_question["1"].current_score == 0.0
        assert by_question["1"].proposed_score == 1.0
        assert by_question["2"].current_score == 1.0
        assert by_question["2"].proposed_score == 0.5

    async def test_create_review_request_question_not_in_grade(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        with pytest.raises(BadRequestError):
            await create_review_request(
                db_session,
                exam_grade_id=grade.id,
                student_id=student.id,
                question_numbers=["99"],
                student_comment="Wrong question number.",
                proposed_scores={},
            )

    async def test_create_review_request_rejected_when_exam_not_released(self, db_session):
        grade, student, _prof, answer_key = await _seed(db_session)
        exam = await db_session.get(Exam, answer_key.exam_id)
        exam.released = False
        await db_session.flush()

        with pytest.raises(BadRequestError):
            await create_review_request(
                db_session,
                exam_grade_id=grade.id,
                student_id=student.id,
                question_numbers=["1"],
                student_comment="Too early to ask for a re-grade.",
                proposed_scores={"1": 1.0},
            )

    async def test_create_review_request_rejected_when_question_already_pending(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "First request.")

        with pytest.raises(BadRequestError):
            await create_review_request(
                db_session,
                exam_grade_id=grade.id,
                student_id=student.id,
                question_numbers=["1"],
                student_comment="Trying again before the first is resolved.",
                proposed_scores={"1": 1.0},
            )

    async def test_create_review_request_rejected_when_any_question_in_batch_already_pending(self, db_session):
        grade, student, _prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        await _create(db_session, grade, student, "2", "Already asked about question 2.")

        with pytest.raises(BadRequestError):
            await create_review_request(
                db_session,
                exam_grade_id=grade.id,
                student_id=student.id,
                question_numbers=["1", "2"],
                student_comment="Question 1 is new, but 2 is already pending.",
                proposed_scores={"1": 1.0, "2": 1.0},
            )

    async def test_create_review_request_allowed_again_once_prior_request_resolved(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        first = await _create(db_session, grade, student, "1", "First request.")
        await update_review_request(
            db_session,
            review_request_id=first.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Score stands.",
            proposed_correct={"1": False},
        )

        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1"],
            student_comment="New evidence to reconsider.",
            proposed_scores={"1": 1.0},
        )
        assert reviews[0].question_number == "1"
        assert reviews[0].status == "pending"

    async def test_create_review_request_snapshots_current_score(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1"],
            student_comment=None,
            proposed_scores={"1": 1.0},
        )
        review = reviews[0]
        assert review.current_score == grade.question_results["1"]["score"]
        assert review.proposed_score == 1.0

    async def test_create_review_request_proposed_score_optional(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1"],
            student_comment="No specific score in mind, just think it's wrong.",
            proposed_scores={},
        )
        assert reviews[0].proposed_score is None

    async def test_get_review_request_by_id(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        fetched = await get_review_request_by_id(db_session, review.id)
        assert fetched is not None
        assert fetched.id == review.id

    async def test_get_review_request_not_found(self, db_session):
        result = await get_review_request_by_id(db_session, uuid.uuid4())
        assert result is None

    async def test_list_by_grade(self, db_session):
        grade, student, _prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        r1 = await _create(db_session, grade, student, "1", "comment 1")
        r2 = await _create(db_session, grade, student, "2", "comment 2")
        reviews = await list_by_grade(db_session, grade.id)
        ids = {r.id for r in reviews}
        assert r1.id in ids
        assert r2.id in ids

    async def test_list_by_grade_empty(self, db_session):
        reviews = await list_by_grade(db_session, uuid.uuid4())
        assert reviews == []

    async def test_list_by_student(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        reviews = await list_by_student(db_session, student.id)
        assert any(r.id == review.id for r, _course_id in reviews)

    async def test_list_by_student_empty(self, db_session):
        reviews = await list_by_student(db_session, uuid.uuid4())
        assert reviews == []

    async def test_update_review_request_resolved(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", "seems off")
        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Awarded credit.",
            proposed_correct={"1": True},
        )
        assert updated is not None
        assert updated[0].status == "resolved"
        assert updated[0].instructor_response == "Awarded credit."
        assert updated[0].proposed_correct is True
        assert updated[0].resolved_at is not None

    async def test_update_review_request_resolved_requires_proposed_correct(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", "seems off")
        with pytest.raises(BadRequestError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=prof.id,
                is_admin=False,
                status="resolved",
                instructor_response="Missing a decision.",
            )

    async def test_update_review_request_resolved_updates_question_status(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", "seems off")
        assert grade.question_results["1"]["correct"] is False

        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="You were right, awarding credit.",
            proposed_correct={"1": True},
        )

        await db_session.refresh(grade)
        assert grade.question_results["1"]["correct"] is True
        assert grade.question_results["1"]["score"] == 1.0
        assert grade.question_results["1"]["ambiguous"] is False
        assert grade.total_score == 1.0

    async def test_update_review_request_rejected(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="rejected",
            instructor_response="No change.",
        )
        assert updated[0].status == "rejected"
        assert updated[0].resolved_at is not None

    async def test_create_review_request_notifies_course_staff(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "Please review")

        unread = await count_unread(db_session, prof.id)
        assert unread == 1

    async def test_resolve_review_request_notifies_student(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Score stands.",
            proposed_correct={"1": False},
        )

        unread = await count_unread(db_session, student.id)
        assert unread == 1

    async def test_update_review_request_not_found(self, db_session):
        result = await update_review_request(
            db_session,
            review_request_id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            is_admin=False,
            status="resolved",
            instructor_response=None,
        )
        assert result is None

    async def test_update_review_request_sets_proposed_score(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Adjusted score.",
            proposed_correct={"1": True},
            proposed_scores={"1": 1.0},
        )
        assert updated[0].proposed_score == 1.0
        assert updated[0].proposed_correct is True

        await db_session.refresh(grade)
        assert grade.total_score == 1.0
        assert grade.question_results["1"]["correct"] is True
        assert grade.question_results["1"]["score"] == 1.0

        grade_audit_entries = (
            await db_session.execute(
                select(GradeAuditEntry).where(GradeAuditEntry.exam_grade_id == grade.id)
            )
        ).scalars().all()
        assert len(grade_audit_entries) == 1
        entry = grade_audit_entries[0]
        assert entry.event_type == "manual_correction"
        assert entry.previous_total_score == 0.0
        assert entry.new_total_score == 1.0
        assert entry.changes["questions"]["1"]["after"]["correct"] is True
        assert entry.changes["questions"]["1"]["after"]["score"] == 1.0
        assert entry.changes["review_request_id"]["after"] == str(review.id)

    async def test_update_review_request_proposed_score_bounded_by_grade_max(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        with pytest.raises(BadRequestError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=prof.id,
                is_admin=False,
                status="resolved",
                instructor_response="Too generous.",
                proposed_correct={"1": True},
                proposed_scores={"1": 5.0},
            )

    async def test_update_review_request_batch_resolves_each_question_independently(self, db_session):
        grade, student, prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1", "2"],
            student_comment="Please recheck both.",
            proposed_scores={},
        )
        review = next(r for r in reviews if r.question_number == "1")

        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Q1 deserved credit, Q2 stays wrong.",
            proposed_correct={"1": True, "2": False},
        )
        by_question = {r.question_number: r for r in updated}
        assert by_question["1"].proposed_correct is True
        assert by_question["2"].proposed_correct is False

        await db_session.refresh(grade)
        assert grade.question_results["1"]["correct"] is True
        assert grade.question_results["1"]["score"] == 1.0
        assert grade.question_results["2"]["correct"] is False
        assert grade.question_results["2"]["score"] == 0.0
        # Q1 went 0/1 -> 1/1 (+1), Q2 went 1/1 -> 0/1 (-1): net unchanged.
        assert grade.total_score == 1.0

    async def test_update_review_request_batch_requires_decision_for_every_question(self, db_session):
        grade, student, prof, _ = await _seed(db_session, _TWO_QUESTION_RESULTS)
        reviews = await create_review_request(
            db_session,
            exam_grade_id=grade.id,
            student_id=student.id,
            question_numbers=["1", "2"],
            student_comment=None,
            proposed_scores={},
        )
        review = next(r for r in reviews if r.question_number == "1")

        with pytest.raises(BadRequestError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=prof.id,
                is_admin=False,
                status="resolved",
                instructor_response="Only decided Q1.",
                proposed_correct={"1": True},
            )

    async def test_update_review_request_forbidden_for_unrelated_staff(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        outsider = User(
            first_name="Outsider",
            last_name="Professor",
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.PROFESSOR.value,
            status="active",
        )
        db_session.add(outsider)
        await db_session.flush()

        with pytest.raises(ForbiddenError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=outsider.id,
                is_admin=False,
                status="resolved",
                instructor_response="Nice try.",
            )

    async def test_update_review_request_allowed_for_enrolled_co_professor(self, db_session):
        grade, student, prof, answer_key = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        exam = await db_session.get(Exam, answer_key.exam_id)
        co_prof = User(
            first_name="Enrolled",
            last_name="CoProfessor",
            email=f"coprof_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.PROFESSOR.value,
            status="active",
        )
        db_session.add(co_prof)
        await db_session.flush()
        db_session.add(Enrolment(user_id=co_prof.id, course_id=exam.course_id, role="professor"))
        await db_session.flush()

        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=co_prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Approved by co-professor.",
            proposed_correct={"1": True},
        )
        assert updated[0].status == "resolved"

    async def test_update_review_request_allowed_for_admin(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        admin = User(
            first_name="Admin",
            last_name="Example",
            email=f"admin_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.ADMIN.value,
            status="active",
        )
        db_session.add(admin)
        await db_session.flush()

        updated = await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=admin.id,
            is_admin=True,
            status="resolved",
            instructor_response="Approved by admin.",
            proposed_correct={"1": True},
        )
        assert updated[0].status == "resolved"


class TestReviewRequestAuditTrail:
    async def _entries_for(self, db_session, review_request_id):
        result = await db_session.execute(
            select(ReviewRequestAuditEntry)
            .where(ReviewRequestAuditEntry.review_request_id == review_request_id)
            .order_by(ReviewRequestAuditEntry.created_at)
        )
        return result.scalars().all()

    async def test_resolve_writes_audit_entry(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", "seems off")
        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Score stands.",
            proposed_correct={"1": True},
        )

        entries = await self._entries_for(db_session, review.id)
        assert len(entries) == 1
        assert entries[0].event_type == "resolved"
        assert entries[0].actor_user_id == prof.id
        assert entries[0].changes == {
            "status": {"before": "pending", "after": "resolved"},
            "instructor_response": {"before": None, "after": "Score stands."},
            "proposed_correct": {"before": None, "after": True},
        }

    async def test_reject_writes_audit_entry(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="rejected",
            instructor_response="No change.",
        )

        entries = await self._entries_for(db_session, review.id)
        assert len(entries) == 1
        assert entries[0].event_type == "rejected"

    async def test_update_twice_appends_second_entry(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="resolved",
            instructor_response="Score stands.",
            proposed_correct={"1": True},
        )
        await update_review_request(
            db_session,
            review_request_id=review.id,
            user_id=prof.id,
            is_admin=False,
            status="rejected",
            instructor_response="Changed my mind.",
        )

        entries = await self._entries_for(db_session, review.id)
        assert [e.event_type for e in entries] == ["resolved", "rejected"]
        assert entries[1].changes["status"] == {
            "before": "resolved",
            "after": "rejected",
        }
        assert entries[1].changes["instructor_response"] == {
            "before": "Score stands.",
            "after": "Changed my mind.",
        }

    async def test_exact_retry_writes_no_second_entry(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None, proposed_score=0.0)
        kwargs = {
            "review_request_id": review.id,
            "user_id": prof.id,
            "is_admin": False,
            "status": "resolved",
            "instructor_response": "Score stands.",
            "proposed_correct": {"1": True},
            "proposed_scores": {"1": 1.0},
        }

        await update_review_request(db_session, **kwargs)
        await update_review_request(db_session, **kwargs)

        entries = await self._entries_for(db_session, review.id)
        assert len(entries) == 1
        assert entries[0].changes["proposed_score"] == {
            "before": 0.0,
            "after": 1.0,
        }

        grade_audit_entries = (
            await db_session.execute(
                select(GradeAuditEntry).where(GradeAuditEntry.exam_grade_id == grade.id)
            )
        ).scalars().all()
        assert len(grade_audit_entries) == 1

    async def test_pending_transition_is_rejected_by_repository(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        with pytest.raises(BadRequestError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=prof.id,
                is_admin=False,
                status="pending",
                instructor_response=None,
            )

        assert await self._entries_for(db_session, review.id) == []

    async def test_review_deletion_preserves_audit_entry(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)
        review_id = review.id
        await update_review_request(
            db_session,
            review_request_id=review_id,
            user_id=prof.id,
            is_admin=False,
            status="rejected",
            instructor_response="No change.",
        )

        await db_session.delete(review)
        await db_session.commit()

        entries = await self._entries_for(db_session, review_id)
        assert len(entries) == 1
        assert entries[0].actor_user_id == prof.id

    async def test_forbidden_update_writes_no_audit_entry(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        review = await _create(db_session, grade, student, "1", None)

        outsider = User(
            first_name="Outsider",
            last_name="Professor",
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.PROFESSOR.value,
            status="active",
        )
        db_session.add(outsider)
        await db_session.flush()

        with pytest.raises(ForbiddenError):
            await update_review_request(
                db_session,
                review_request_id=review.id,
                user_id=outsider.id,
                is_admin=False,
                status="resolved",
                instructor_response="Nice try.",
            )

        entries = await self._entries_for(db_session, review.id)
        assert entries == []

    async def test_not_found_update_writes_no_audit_entry(self, db_session):
        missing_id = uuid.uuid4()
        result = await update_review_request(
            db_session,
            review_request_id=missing_id,
            user_id=uuid.uuid4(),
            is_admin=False,
            status="resolved",
            instructor_response=None,
        )
        assert result is None

        entries = await self._entries_for(db_session, missing_id)
        assert entries == []


class TestListForStaff:
    async def test_course_creator_sees_own_course(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "Please review")

        rows = await list_for_staff(db_session, prof.id, is_admin=False)
        assert len(rows) == 1
        _review, student_name, _course_id, course_code, term, exam_name, max_score = rows[0]
        assert student_name == "Student Example"
        assert course_code == "COSC 499"
        assert term == "Winter Session 1"
        assert exam_name == "Midterm"
        assert max_score == 1.0

    async def test_enrolled_co_professor_sees_course(self, db_session):
        grade, student, prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "Please review")

        # Look up the exam (and its course) that owns the answer key/grade.
        answer_key = await db_session.get(ExamAnswerKey, grade.exam_answer_key_id)
        exam = await db_session.get(Exam, answer_key.exam_id)

        co_prof = User(
            first_name="Enrolled",
            last_name="CoProfessor",
            email=f"coprof_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.PROFESSOR.value,
            status="active",
        )
        db_session.add(co_prof)
        await db_session.flush()
        db_session.add(Enrolment(user_id=co_prof.id, course_id=exam.course_id, role="professor"))
        await db_session.flush()

        rows = await list_for_staff(db_session, co_prof.id, is_admin=False)
        assert len(rows) == 1

    async def test_unrelated_staff_sees_nothing(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "Please review")

        outsider = User(
            first_name="Outsider",
            last_name="Professor",
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.PROFESSOR.value,
            status="active",
        )
        db_session.add(outsider)
        await db_session.flush()

        rows = await list_for_staff(db_session, outsider.id, is_admin=False)
        assert rows == []

    async def test_admin_sees_all(self, db_session):
        grade, student, _prof, _ = await _seed(db_session)
        await _create(db_session, grade, student, "1", "Please review")

        admin = User(
            first_name="Admin",
            last_name="Example",
            email=f"admin_{uuid.uuid4().hex[:6]}@test.com",
            password_hash=hash_password("Password123!"),
            role=UserRole.ADMIN.value,
            status="active",
        )
        db_session.add(admin)
        await db_session.flush()

        rows = await list_for_staff(db_session, admin.id, is_admin=True)
        assert len(rows) == 1
        _review, student_name, _course_id, course_code, term, exam_name, max_score = rows[0]
        assert student_name == "Student Example"
        assert course_code == "COSC 499"
        assert term == "Winter Session 1"
        assert exam_name == "Midterm"
        assert max_score == 1.0
