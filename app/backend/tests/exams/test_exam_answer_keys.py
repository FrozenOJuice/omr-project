import uuid
import pytest

from models.exam import Exam
from models.exam_grade import ExamGrade
from models.omr_marking import OMRMarking
from models.omr_template import OMRTemplate
from models.scan import Scan

pytestmark = pytest.mark.db


async def _seed_grade_for_answer_key(db_session, exam_id: str, answer_key_id: str) -> None:
    """Minimal FK chain (OMRTemplate -> Scan -> OMRMarking -> ExamGrade) needed
    to make an answer key look "already graded" for the freeze guard."""
    exam = await db_session.get(Exam, uuid.UUID(exam_id))

    omr_tmpl = OMRTemplate(name="OMR", page_count=1)
    db_session.add(omr_tmpl)
    await db_session.flush()

    scan = Scan(
        exam_id=exam.id,
        exam_template_id=exam.exam_template_id,
        uploader_user_id=exam.created_by,
        path="scans/test.pdf",
    )
    db_session.add(scan)
    await db_session.flush()

    marking = OMRMarking(scan_id=scan.id, omr_template_id=omr_tmpl.id, status="completed")
    db_session.add(marking)
    await db_session.flush()

    grade = ExamGrade(
        omr_marking_id=marking.id,
        exam_answer_key_id=uuid.UUID(answer_key_id),
        question_results={},
        total_score=0.0,
        max_score=1.0,
        template_version=1,
        status="needs_review",
    )
    db_session.add(grade)
    await db_session.flush()


async def _setup_exam_and_template(client, headers, version_count=1):
    """Helper: create template → course → exam (referencing template), return (exam_id, template_id)."""
    version_query = (
        f"&version_from_q1=true&n_versions={version_count}"
        if version_count > 1
        else ""
    )
    template = await client.post(
        f"/api/exam-templates?blueprint=ubco_100{version_query}", headers=headers
    )
    template_id = template.json()["id"]

    course = await client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
    exam = await client.post(
        "/api/exams",
        json={
            "name": "Midterm",
            "start_time": "2026-06-25T09:00:00Z",
            "end_time": "2026-06-25T10:00:00Z",
            "role": "student",
            "course_id": course.json()["id"],
            "exam_template_id": template_id,
        },
        headers=headers,
    )
    return exam.json()["id"], template_id


SINGLE_KEY_PAYLOAD = {
    "exam_template_id": None,  # filled in per test
    "exam_version": None,
    "answer_key": {
        str(i): {"grading_type": "single", "correct_choices": ["A"], "points": 1.0, "partial_weights": None}
        for i in range(1, 101)
    },
    "scoring_rules": {"default_points_per_question": 1.0},
}

VERSIONED_KEY_PAYLOAD = {
    **SINGLE_KEY_PAYLOAD,
    "answer_key": {
        question: item
        for question, item in SINGLE_KEY_PAYLOAD["answer_key"].items()
        if question != "1"
    },
}


class TestCreateExamAnswerKey:
    async def test_create_single_version_answer_key_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        payload = {**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id}
        response = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)

        assert response.status_code == 201
        data = response.json()
        assert data["exam_id"] == exam_id
        assert data["exam_template_id"] == template_id
        assert data["exam_version"] is None
        assert data["answer_key"]["1"]["grading_type"] == "single"

    async def test_create_versioned_answer_keys_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )

        for version in ("A", "B"):
            payload = {
                **VERSIONED_KEY_PAYLOAD,
                "exam_template_id": template_id,
                "exam_version": version,
            }
            r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
            assert r.status_code == 201
            assert r.json()["exam_version"] == version

    async def test_create_duplicate_version_fails(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )

        payload = {
            **VERSIONED_KEY_PAYLOAD,
            "exam_template_id": template_id,
            "exam_version": "A",
        }
        await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)

        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 403

    async def test_create_answer_key_invalid_choice_fails(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        payload = {**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id}
        payload["answer_key"] = {
            **payload["answer_key"],
            "15": {"grading_type": "single", "correct_choices": ["F"], "points": 1.0, "partial_weights": None},
        }
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)

        assert r.status_code == 400
        assert "question '15'" in r.json()["error"]["message"]

    async def test_create_partial_answer_key_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Partial Template",
                "question_config": {"1": {"choices": ["A", "B", "C"]}},
                "n_versions": 1,
            },
            headers=headers,
        )
        template_id = template.json()["id"]

        course = await client.post("/api/courses", json={"name": "COSC", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        exam = await client.post(
            "/api/exams",
            json={"name": "Q", "start_time": "2026-06-25T09:00:00Z", "end_time": "2026-06-25T10:00:00Z", "role": "student", "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        payload = {
            "exam_template_id": template_id,
            "exam_version": None,
            "answer_key": {
                "1": {
                    "grading_type": "partial",
                    "correct_choices": ["A", "B"],
                    "points": 3.0,
                    "partial_weights": {"A": 0.6, "B": 0.4},
                }
            },
            "scoring_rules": None,
        }
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 201
        assert r.json()["answer_key"]["1"]["grading_type"] == "partial"

    async def test_create_partial_missing_weights_fails(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Partial Template",
                "question_config": {"1": {"choices": ["A", "B", "C"]}},
                "n_versions": 1,
            },
            headers=headers,
        )
        template_id = template.json()["id"]

        course = await client.post("/api/courses", json={"name": "COSC", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        exam = await client.post(
            "/api/exams",
            json={"name": "Q", "start_time": "2026-06-25T09:00:00Z", "end_time": "2026-06-25T10:00:00Z", "role": "student", "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        payload = {
            "exam_template_id": template_id,
            "exam_version": None,
            "answer_key": {
                "1": {
                    "grading_type": "partial",
                    "correct_choices": ["A"],
                    "points": None,
                    "partial_weights": None,
                }
            },
            "scoring_rules": None,
        }
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 422

    async def test_create_partial_weights_summing_over_100_percent_fails(self, authenticated_client):
        # grading_service._score_question sums the weights of every correct
        # choice a student marks, so an answer key whose correct-choice
        # weights add up to more than 1 misrepresents what each choice is
        # worth even though the final score still gets clamped to `points`.
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Partial Template",
                "question_config": {"1": {"choices": ["A", "B", "C"]}},
                "n_versions": 1,
            },
            headers=headers,
        )
        template_id = template.json()["id"]

        course = await client.post("/api/courses", json={"name": "COSC", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        exam = await client.post(
            "/api/exams",
            json={"name": "Q", "start_time": "2026-06-25T09:00:00Z", "end_time": "2026-06-25T10:00:00Z", "role": "student", "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        payload = {
            "exam_template_id": template_id,
            "exam_version": None,
            "answer_key": {
                "1": {
                    "grading_type": "partial",
                    "correct_choices": ["A", "B"],
                    "points": 1.0,
                    "partial_weights": {"A": 0.6, "B": 0.6},
                }
            },
            "scoring_rules": None,
        }
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 422

    async def test_create_partial_weights_summing_under_100_percent_fails(self, authenticated_client):
        # A student who marks every correct choice must be able to reach full
        # marks. Weights that only add up to e.g. 80% would make full credit
        # unreachable no matter what a student selects.
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Partial Template",
                "question_config": {"1": {"choices": ["A", "B", "C"]}},
                "n_versions": 1,
            },
            headers=headers,
        )
        template_id = template.json()["id"]

        course = await client.post("/api/courses", json={"name": "COSC", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        exam = await client.post(
            "/api/exams",
            json={"name": "Q", "start_time": "2026-06-25T09:00:00Z", "end_time": "2026-06-25T10:00:00Z", "role": "student", "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        payload = {
            "exam_template_id": template_id,
            "exam_version": None,
            "answer_key": {
                "1": {
                    "grading_type": "partial",
                    "correct_choices": ["A", "B"],
                    "points": 1.0,
                    "partial_weights": {"A": 0.3, "B": 0.3},
                }
            },
            "scoring_rules": None,
        }
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 422

    async def test_versioned_exam_requires_a_configured_version(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )

        missing = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**VERSIONED_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        invalid = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={
                **VERSIONED_KEY_PAYLOAD,
                "exam_template_id": template_id,
                "exam_version": "C",
            },
            headers=headers,
        )

        assert missing.status_code == 400
        assert missing.json()["error"]["code"] == "answer_key_version_required"
        assert invalid.status_code == 400
        assert invalid.json()["error"]["code"] == "invalid_answer_key_version"

    async def test_single_version_exam_rejects_a_version_label(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        response = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={
                **SINGLE_KEY_PAYLOAD,
                "exam_template_id": template_id,
                "exam_version": "A",
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_answer_key_version"

    async def test_create_answer_key_invalid_version_format_fails(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        payload = {**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id, "exam_version": "AB"}
        r = await client.post(f"/api/exams/{exam_id}/answer-keys", json=payload, headers=headers)
        assert r.status_code == 422

    async def test_create_answer_key_forbidden_for_non_owner(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="prof_a@ubc.ca")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        exam_id, template_id = await _setup_exam_and_template(client_a, headers_a)

        client_b, token_b = await authenticated_client(email="prof_b@ubc.ca")
        payload = {**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id}
        r = await client_b.post(
            f"/api/exams/{exam_id}/answer-keys",
            json=payload,
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 403


class TestGetExamAnswerKey:
    async def test_list_answer_keys_for_exam(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )

        for version in ("A", "B"):
            await client.post(
                f"/api/exams/{exam_id}/answer-keys",
                json={
                    **VERSIONED_KEY_PAYLOAD,
                    "exam_template_id": template_id,
                    "exam_version": version,
                },
                headers=headers,
            )

        r = await client.get(f"/api/exams/{exam_id}/answer-keys", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) == 2
        assert {k["exam_version"] for k in r.json()} == {"A", "B"}

    async def test_get_answer_key_by_id(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]

        r = await client.get(f"/api/answer-keys/{key_id}", headers=headers)
        assert r.status_code == 200
        assert r.json()["id"] == key_id

    async def test_get_nonexistent_answer_key_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        r = await client.get(f"/api/answer-keys/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404


class TestUpdateExamAnswerKey:
    async def test_update_answer_key_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]

        patch = await client.patch(
            f"/api/answer-keys/{key_id}",
            json={
                "answer_key": {
                    "5": {"grading_type": "multiple", "correct_choices": ["A", "B"], "points": 2.0, "partial_weights": None}
                }
            },
            headers=headers,
        )
        assert patch.status_code == 200
        assert patch.json()["answer_key"]["5"]["grading_type"] == "multiple"
        assert patch.json()["answer_key"]["1"]["grading_type"] == "single"

    async def test_update_answer_key_forbidden_for_non_owner(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="prof_a@ubc.ca")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        exam_id, template_id = await _setup_exam_and_template(client_a, headers_a)
        created = await client_a.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers_a,
        )
        key_id = created.json()["id"]

        client_b, token_b = await authenticated_client(email="prof_b@ubc.ca")
        r = await client_b.patch(
            f"/api/answer-keys/{key_id}",
            json={"scoring_rules": {"default_points_per_question": 5.0}},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert r.status_code == 403


class TestDownloadAnswerKeyJson:
    async def test_nonexistent_answer_key_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        r = await client.get(
            f"/api/answer-keys/{uuid.uuid4()}/download",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "answer_key_not_found"

    async def test_returns_json_payload(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={
                **VERSIONED_KEY_PAYLOAD,
                "exam_template_id": template_id,
                "exam_version": "A",
            },
            headers=headers,
        )
        key_id = created.json()["id"]

        r = await client.get(f"/api/answer-keys/{key_id}/download", headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["exam_version"] == "A"
        assert "questions" in body
        assert "total_points" in body
        assert body["questions"]["2"]["correct_choices"] == ["A"]

    async def test_returns_csv_payload(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(
            client, headers, version_count=2
        )
        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={
                **VERSIONED_KEY_PAYLOAD,
                "exam_template_id": template_id,
                "exam_version": "A",
            },
            headers=headers,
        )

        r = await client.get(
            f"/api/answer-keys/{created.json()['id']}/download.csv",
            headers=headers,
        )

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert r.headers["content-disposition"].endswith("answer_key_A.csv")
        assert "question,correct_choices,grading_type,points" in r.text
        assert "2,A,single" in r.text

    async def test_student_user_is_forbidden(self, staff_client, register_user):
        prof_client, prof_token = await staff_client()
        headers = {"Authorization": f"Bearer {prof_token}"}

        template = await prof_client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
        template_id = template.json()["id"]

        course = await prof_client.post("/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers)
        exam = await prof_client.post(
            "/api/exams",
            json={"name": "M", "start_time": "2026-08-01T09:00:00Z", "end_time": "2026-08-01T12:00:00Z",
                  "role": "student", "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        created = await prof_client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]

        r = await prof_client.get(
            f"/api/answer-keys/{key_id}/download",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert r.status_code == 403


class TestDeleteExamAnswerKey:
    async def test_delete_answer_key_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]

        delete_r = await client.delete(f"/api/answer-keys/{key_id}", headers=headers)
        assert delete_r.status_code == 204

        get_r = await client.get(f"/api/answer-keys/{key_id}", headers=headers)
        assert get_r.status_code == 404

    async def test_delete_nonexistent_answer_key_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        r = await client.delete(f"/api/answer-keys/{uuid.uuid4()}", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 404


class TestAnswerKeyFreezeAfterGrading:
    async def test_update_blocked_once_exam_has_a_grade(self, authenticated_client, db_session):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]
        await _seed_grade_for_answer_key(db_session, exam_id, key_id)

        patch = await client.patch(
            f"/api/answer-keys/{key_id}",
            json={"scoring_rules": {"default_points_per_question": 5.0}},
            headers=headers,
        )
        assert patch.status_code == 409
        assert patch.json()["error"]["code"] == "exam_already_graded"

    async def test_delete_blocked_once_exam_has_a_grade(self, authenticated_client, db_session):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**SINGLE_KEY_PAYLOAD, "exam_template_id": template_id},
            headers=headers,
        )
        key_id = created.json()["id"]
        await _seed_grade_for_answer_key(db_session, exam_id, key_id)

        delete_r = await client.delete(f"/api/answer-keys/{key_id}", headers=headers)
        assert delete_r.status_code == 409
        assert delete_r.json()["error"]["code"] == "exam_already_graded"

    async def test_create_additional_version_blocked_once_exam_has_a_grade(
        self, authenticated_client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        exam_id, template_id = await _setup_exam_and_template(client, headers, version_count=2)

        created = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**VERSIONED_KEY_PAYLOAD, "exam_template_id": template_id, "exam_version": "A"},
            headers=headers,
        )
        key_id = created.json()["id"]
        await _seed_grade_for_answer_key(db_session, exam_id, key_id)

        r = await client.post(
            f"/api/exams/{exam_id}/answer-keys",
            json={**VERSIONED_KEY_PAYLOAD, "exam_template_id": template_id, "exam_version": "B"},
            headers=headers,
        )
        assert r.status_code == 409
        assert r.json()["error"]["code"] == "exam_already_graded"
