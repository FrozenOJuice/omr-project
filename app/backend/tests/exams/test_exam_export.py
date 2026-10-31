import csv
import io
import uuid
from datetime import datetime, timezone

import pytest

from models.course import Course
from models.academic_term import UBC_WINTER_SESSION_1_TERM_ID
from models.exam import Exam
from models.exam_answer_key import ExamAnswerKey
from models.exam_grade import ExamGrade
from models.exam_template import ExamTemplate
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import UserRole

pytestmark = pytest.mark.db

EXPECTED_HEADER = [
    "student_number", "student_name", "exam_version", "status", "flag_reason",
    "Q1", "Q2",
    "total_score", "max_score", "exam_name", "course_name", "academic_term", "exam_date", "graded_at",
]


async def _seed_exam(db_session, *, course_created_by):
    course = Course(name="COSC 499", academic_term_id=UBC_WINTER_SESSION_1_TERM_ID, created_by=course_created_by)
    db_session.add(course)
    await db_session.flush()

    template = ExamTemplate(
        name="Template",
        created_by=course_created_by,
        question_config={"1": {"choices": ["A", "B"]}},
        total_questions=2,
        version=1,
        n_versions=1,
    )
    db_session.add(template)
    await db_session.flush()

    exam = Exam(
        name="Midterm Exam",
        description=None,
        start_time=datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc),
        end_time=datetime(2026, 6, 1, 11, 0, tzinfo=timezone.utc),
        role="student",
        course_id=course.id,
        created_by=course_created_by,
        exam_template_id=template.id,
    )
    db_session.add(exam)
    await db_session.flush()
    return course, template, exam


async def _add_answer_key(db_session, exam, template, *, exam_version="A"):
    answer_key = ExamAnswerKey(
        exam_id=exam.id,
        exam_template_id=template.id,
        exam_version=exam_version,
        answer_key={
            "1": {"grading_type": "single", "correct_choices": ["A"], "points": 1.0},
            "2": {"grading_type": "multiple", "correct_choices": ["B", "C"], "points": 2.0},
        },
    )
    db_session.add(answer_key)
    await db_session.flush()
    return answer_key


async def _add_grade(
    db_session,
    exam,
    template,
    answer_key,
    uploader_id,
    *,
    student_id=None,
    question_results=None,
    total_score=3.0,
    max_score=3.0,
    status="graded",
    flag_reason=None,
):
    scan = Scan(
        exam_id=exam.id,
        exam_template_id=template.id,
        uploader_user_id=uploader_id,
        path=f"scans/{uuid.uuid4().hex}.pdf",
        status="completed",
    )
    omr_template = OMRTemplate(name="OMR", page_count=2)
    db_session.add_all([scan, omr_template])
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_template.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=answer_key.id,
        question_results=question_results or {},
        total_score=total_score,
        max_score=max_score,
        template_version=1,
        student_id=student_id,
        status=status,
        flag_reason=flag_reason,
    )
    db_session.add(grade)
    await db_session.flush()
    return grade


async def _token_for(create_user, login_user, *, role, student_number=None, first_name="Alice", last_name="Example"):
    email = f"user_{uuid.uuid4().hex[:8]}@test.com"
    user = await create_user(
        email=email,
        role=role,
        student_number=student_number,
        first_name=first_name,
        last_name=last_name,
    )
    resp = await login_user(email=email)
    return user, resp.json()["access_token"]


def _parse_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text)))


class TestExportExamResults:
    async def test_owner_downloads_csv_with_expected_rows_and_columns(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        student, _ = await _token_for(
            create_user, login_user,
            role=UserRole.STUDENT, student_number="12345678",
            first_name="Joe", last_name="Blow",
        )
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        answer_key = await _add_answer_key(db_session, exam, template, exam_version="A")
        await _add_grade(
            db_session, exam, template, answer_key, professor.id,
            student_id=student.id,
            question_results={
                "1": {"grading_type": "single", "student_answers": ["A"], "correct_answers": ["A"], "correct": True, "score": 1.0, "max_score": 1.0, "ambiguous": False},
                "2": {"grading_type": "multiple", "student_answers": ["B", "C"], "correct_answers": ["B", "C"], "correct": True, "score": 2.0, "max_score": 2.0, "ambiguous": False},
            },
        )

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith("text/csv")
        assert response.headers["content-disposition"] == 'attachment; filename="midterm-exam-results.csv"'

        rows = _parse_csv(response.text)
        assert rows[0] == EXPECTED_HEADER
        assert len(rows) == 2
        assert rows[1] == [
            "12345678", "Joe Blow", "A", "graded", "",
            "A", "B,C",
            "3.0", "3.0", "Midterm Exam", "COSC 499", "Winter Session 1", "2026-06-01", rows[1][-1],
        ]
        assert rows[1][-1]  # graded_at is populated

    async def test_needs_review_grade_exported_with_blank_student(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        answer_key = await _add_answer_key(db_session, exam, template)
        await _add_grade(
            db_session, exam, template, answer_key, professor.id,
            student_id=None,
            question_results={
                "1": {"grading_type": "single", "student_answers": [], "correct_answers": ["A"], "correct": False, "score": 0.0, "max_score": 1.0, "ambiguous": False},
            },
            total_score=0.0,
            status="needs_review",
            flag_reason="name_no_match",
        )

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

        rows = _parse_csv(response.text)
        assert len(rows) == 2
        row = rows[1]
        assert row[0] == ""  # student_number
        assert row[1] == ""  # student_name
        assert row[3] == "needs_review"
        assert row[4] == "name_no_match"
        assert row[5] == ""  # Q1 blank response

    async def test_formula_like_cells_are_escaped(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        student, _ = await _token_for(
            create_user, login_user,
            role=UserRole.STUDENT, student_number="55555555",
            first_name="=HYPERLINK(1)", last_name="Example",
        )
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        exam.name = "=cmd Midterm"
        answer_key = await _add_answer_key(db_session, exam, template)
        await _add_grade(
            db_session, exam, template, answer_key, professor.id,
            student_id=student.id,
        )

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

        row = _parse_csv(response.text)[1]
        # Cells that Excel/Sheets would treat as formulas get a ' prefix.
        assert row[1] == "'=HYPERLINK(1) Example"
        assert row[EXPECTED_HEADER.index("exam_name")] == "'=cmd Midterm"

    async def test_export_with_no_grades_returns_header_only(
        self, create_user, login_user, client, db_session
    ):
        professor, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=professor.id)
        await _add_answer_key(db_session, exam, template)

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        assert _parse_csv(response.text) == [EXPECTED_HEADER]

    async def test_non_owner_professor_is_forbidden(
        self, create_user, login_user, client, db_session
    ):
        owner, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        course, template, exam = await _seed_exam(db_session, course_created_by=owner.id)

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text

    async def test_student_is_forbidden(self, create_user, login_user, client, db_session):
        owner, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, token = await _token_for(create_user, login_user, role=UserRole.STUDENT, student_number="87654321")
        course, template, exam = await _seed_exam(db_session, course_created_by=owner.id)

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403, response.text

    async def test_admin_can_export_any_exam(self, create_user, login_user, client, db_session):
        owner, _ = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)
        _, token = await _token_for(create_user, login_user, role=UserRole.ADMIN)
        course, template, exam = await _seed_exam(db_session, course_created_by=owner.id)
        await _add_answer_key(db_session, exam, template)

        response = await client.get(
            f"/api/exams/{exam.id}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text

    async def test_unknown_exam_returns_404(self, create_user, login_user, client, db_session):
        _, token = await _token_for(create_user, login_user, role=UserRole.PROFESSOR)

        response = await client.get(
            f"/api/exams/{uuid.uuid4()}/export",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404, response.text
