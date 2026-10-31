"""Integration tests for the exam-specific PDF endpoints.

POST /api/exams/{exam_id}/generate-pdf
GET  /api/exams/{exam_id}/download-pdf

These build on top of a template's own generate/finalize endpoints (see
test_exam_generator_router.py) -- an exam's PDF can't be generated until its
template is registered with OMR (finalized), which itself requires an
answer key for every version.
"""
import uuid

import pytest

pytestmark = pytest.mark.db


async def _create_course_and_exam(client, headers, template_id, name="Midterm"):
    course = await client.post(
        "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
    )
    exam = await client.post(
        "/api/exams",
        json={
            "name": name,
            "start_time": "2026-08-01T09:00:00+00:00",
            "end_time": "2026-08-01T12:00:00+00:00",
            "role": "student",
            "course_id": course.json()["id"],
            "exam_template_id": template_id,
        },
        headers=headers,
    )
    return exam.json()["id"]


async def _setup_finalized_exam(client, token):
    """Template (generated + finalized) + course + exam + answer keys for
    every version. Returns (exam_id, template_id)."""
    headers = {"Authorization": f"Bearer {token}"}

    template = await client.post(
        "/api/exam-templates",
        json={
            "name": "Custom 2Q",
            "question_config": {
                "1": {"choices": ["A", "B", "C", "D"]},
                "2": {"choices": ["A", "B", "C", "D"]},
            },
        },
        headers=headers,
    )
    template_id = template.json()["id"]
    await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

    exam_id = await _create_course_and_exam(client, headers, template_id)

    for version in ("A", "B", "C", "D"):
        ak_payload = {
            "exam_template_id": template_id,
            "exam_version": version,
            "answer_key": {
                str(i): {
                    "grading_type": "single",
                    "correct_choices": ["A"],
                    "points": 1.0,
                    "partial_weights": None,
                }
                for i in range(1, 3)
            },
            "scoring_rules": {"default_points_per_question": 1.0},
        }
        await client.post(f"/api/exams/{exam_id}/answer-keys", json=ak_payload, headers=headers)

    await client.post(f"/api/exam-templates/{template_id}/finalize", headers=headers)

    return exam_id, template_id


class TestGenerateExamPdfEndpoint:
    async def test_unauthenticated_is_rejected(self, client):
        response = await client.post(f"/api/exams/{uuid.uuid4()}/generate-pdf")
        assert response.status_code == 401

    async def test_student_user_is_forbidden(
        self, staff_client, register_user, mock_storage, mock_omr_client
    ):
        prof_client, prof_token = await staff_client()
        exam_id, _ = await _setup_finalized_exam(prof_client, prof_token)

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]

        response = await prof_client.post(
            f"/api/exams/{exam_id}/generate-pdf",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403

    async def test_unknown_exam_returns_404(self, staff_client):
        client, token = await staff_client()
        response = await client.post(
            f"/api/exams/{uuid.uuid4()}/generate-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "exam_not_found"

    async def test_other_professor_returns_403(self, staff_client, mock_storage, mock_omr_client):
        owner_client, owner_token = await staff_client()
        other_client, other_token = await staff_client()
        exam_id, _ = await _setup_finalized_exam(owner_client, owner_token)

        response = await other_client.post(
            f"/api/exams/{exam_id}/generate-pdf",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    async def test_template_not_finalized_returns_400(self, staff_client, mock_storage):
        client, token = await staff_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post(
            "/api/exam-templates",
            json={"name": "Custom", "question_config": {"1": {"choices": ["A", "B"]}}},
            headers=headers,
        )
        template_id = template.json()["id"]
        exam_id = await _create_course_and_exam(client, headers, template_id, name="Quiz")

        response = await client.post(f"/api/exams/{exam_id}/generate-pdf", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "template_not_finalized"

    async def test_blueprint_template_returns_400(self, staff_client, mock_storage):
        client, token = await staff_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
        template_id = template.json()["id"]
        exam_id = await _create_course_and_exam(client, headers, template_id, name="Quiz")

        response = await client.post(f"/api/exams/{exam_id}/generate-pdf", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "pdf_not_generated"

    async def test_happy_path_sets_generated_pdf_path(
        self, staff_client, mock_storage, mock_omr_client
    ):
        client, token = await staff_client()
        exam_id, _ = await _setup_finalized_exam(client, token)

        response = await client.post(
            f"/api/exams/{exam_id}/generate-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["generated_pdf_path"] == f"generated/exam/{exam_id}/exam_sheet.pdf"


class TestDownloadExamPdfEndpoint:
    async def test_not_generated_returns_400(self, staff_client, mock_storage, mock_omr_client):
        client, token = await staff_client()
        exam_id, _ = await _setup_finalized_exam(client, token)

        response = await client.get(
            f"/api/exams/{exam_id}/download-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "pdf_not_generated"

    async def test_happy_path_returns_pdf_bytes(
        self, staff_client, mock_storage, mock_omr_client
    ):
        client, token = await staff_client()
        exam_id, _ = await _setup_finalized_exam(client, token)
        await client.post(
            f"/api/exams/{exam_id}/generate-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )

        response = await client.get(
            f"/api/exams/{exam_id}/download-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
