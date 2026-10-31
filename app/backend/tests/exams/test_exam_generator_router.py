"""Integration tests for the exam generation and finalization endpoints.

POST /api/exam-templates/{template_id}/generate   — blank PDF + scan template
POST /api/exam-templates/{template_id}/finalize   — mark template + OMR record
GET  /api/exam-templates/{template_id}/download-pdf

Storage is mocked via the mock_storage fixture so no real S3 calls are made.
Staff access is tested via the staff_client fixture (PROFESSOR role).
"""
import uuid

import pytest

pytestmark = pytest.mark.db


async def _setup_template(client, token):
    """Create a reusable custom (non-blueprint) exam template and return its id."""
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
    return template.json()["id"]


async def _setup_ubco_template(client, token):
    """Create a template via the UBCO_100 blueprint and return its id."""
    headers = {"Authorization": f"Bearer {token}"}
    template = await client.post(
        "/api/exam-templates?blueprint=ubco_100",
        headers=headers,
    )
    return template.json()["id"]


class TestGenerateEndpoint:
    async def test_student_user_is_forbidden(self, staff_client, register_user):
        prof_client, prof_token = await staff_client()
        template_id = await _setup_template(prof_client, prof_token)

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]

        response = await prof_client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403

    async def test_unauthenticated_is_rejected(self, client):
        response = await client.post(f"/api/exam-templates/{uuid.uuid4()}/generate")
        assert response.status_code == 401

    async def test_unknown_template_returns_404(self, staff_client, mock_storage):
        client, token = await staff_client()
        response = await client.post(
            f"/api/exam-templates/{uuid.uuid4()}/generate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "template_not_found"

    async def test_wrong_owner_returns_403(self, staff_client, mock_storage):
        owner_client, owner_token = await staff_client()
        other_client, other_token = await staff_client()
        template_id = await _setup_template(owner_client, owner_token)

        response = await other_client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "forbidden"

    async def test_happy_path_returns_template_with_pdf_path(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_template(client, token)

        response = await client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["generated_pdf_path"] == f"generated/{template_id}/bubble_sheet.pdf"
        assert data["omr_template_id"] is None

    async def test_happy_path_uploads_three_files_to_storage(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_template(client, token)

        await client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert mock_storage.upload_file.call_count == 3


class TestFinalizeEndpoint:
    async def _setup_generated_template_with_answer_key(self, client, token, *, generate=True):
        """Create a template, exam, and complete answer keys."""
        headers = {"Authorization": f"Bearer {token}"}

        template_id = await _setup_template(client, token)

        if generate:
            await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

        course = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        exam = await client.post(
            "/api/exams",
            json={"name": "Midterm", "start_time": "2026-08-01T09:00:00+00:00",
                  "end_time": "2026-08-01T12:00:00+00:00", "role": "student",
                  "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        # Complete keys are still useful to callers of this helper even though
        # OMR registration itself no longer depends on them.
        for version in ("A", "B", "C", "D"):
            ak_payload = {
                "exam_template_id": template_id,
                "exam_version": version,
                "answer_key": {
                    str(i): {"grading_type": "single", "correct_choices": ["A"],
                              "points": 1.0, "partial_weights": None}
                    for i in range(1, 3)
                },
                "scoring_rules": {"default_points_per_question": 1.0},
            }
            await client.post(f"/api/exams/{exam_id}/answer-keys", json=ak_payload, headers=headers)
        return template_id

    async def test_finalize_without_pdf_generates_and_registers_template(
        self, staff_client, mock_storage, mock_omr_client
    ):
        client, token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(
            client, token, generate=False
        )

        response = await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["generated_pdf_path"] == f"generated/{template_id}/bubble_sheet.pdf"
        assert response.json()["omr_template_id"] is not None

    async def test_finalize_without_answer_key_registers_template(
        self, staff_client, mock_storage, mock_omr_client
    ):
        client, token = await staff_client()
        headers = {"Authorization": f"Bearer {token}"}
        template_id = await _setup_template(client, token)

        await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

        response = await client.post(
            f"/api/exam-templates/{template_id}/finalize", headers=headers
        )
        assert response.status_code == 200
        assert response.json()["omr_template_id"] is not None

    async def test_finalize_happy_path_sets_omr_template(self, staff_client, mock_storage, mock_omr_client):
        client, token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(client, token)

        response = await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["omr_template_id"] is not None

    async def test_finalize_uploads_mark_template(self, staff_client, mock_storage, mock_omr_client):
        client, token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(client, token)
        mock_storage.upload_file.reset_mock()

        await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {token}"},
        )
        uploaded_keys = {c.args[1] for c in mock_storage.upload_file.call_args_list}
        assert f"generated/{template_id}/mark_template.json" in uploaded_keys

    async def test_finalize_wrong_owner_returns_403(self, staff_client, mock_storage):
        owner_client, owner_token = await staff_client()
        other_client, other_token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(owner_client, owner_token)

        response = await other_client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {other_token}"},
        )
        assert response.status_code == 403

    async def test_student_cannot_finalize(self, staff_client, register_user):
        prof_client, prof_token = await staff_client()
        template_id = await _setup_template(prof_client, prof_token)

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]

        response = await prof_client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403


class TestDownloadEndpoint:
    async def test_student_user_is_forbidden(self, staff_client, register_user):
        prof_client, prof_token = await staff_client()
        template_id = await _setup_template(prof_client, prof_token)

        student_resp = await register_user()
        student_token = student_resp.json()["access_token"]

        response = await prof_client.get(
            f"/api/exam-templates/{template_id}/download-pdf",
            headers={"Authorization": f"Bearer {student_token}"},
        )
        assert response.status_code == 403

    async def test_unknown_template_returns_404(self, staff_client, mock_storage):
        client, token = await staff_client()
        response = await client.get(
            f"/api/exam-templates/{uuid.uuid4()}/download-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404

    async def test_pdf_not_yet_generated_returns_400(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_template(client, token)

        response = await client.get(
            f"/api/exam-templates/{template_id}/download-pdf",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "pdf_not_generated"

    async def test_streams_pdf_bytes_after_generate(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_template(client, token)
        headers = {"Authorization": f"Bearer {token}"}
        pdf_bytes = b"%PDF-1.4 test pdf"
        mock_storage.download_file.return_value = pdf_bytes

        await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

        response = await client.get(
            f"/api/exam-templates/{template_id}/download-pdf",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "application/pdf"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.content.startswith(b"%PDF")
        mock_storage.download_file.assert_called_once_with(
            f"generated/{template_id}/bubble_sheet.pdf"
        )


class TestUbcoBlueprintGeneration:
    """UBCO_100 blueprint templates use the fixed, hand-made sheet in
    app/backend/data/ubc_template instead of a custom-drawn layout."""

    async def test_generate_uploads_only_the_scan_template(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_ubco_template(client, token)

        response = await client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["generated_pdf_path"] is None
        assert data["omr_template_id"] is None

        assert mock_storage.upload_file.call_count == 1
        uploaded_key = mock_storage.upload_file.call_args_list[0].args[1]
        assert uploaded_key == f"generated/{template_id}/scan_template.json"

    async def test_download_pdf_unavailable_since_nothing_was_drawn(self, staff_client, mock_storage):
        client, token = await staff_client()
        template_id = await _setup_ubco_template(client, token)
        headers = {"Authorization": f"Bearer {token}"}

        await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

        response = await client.get(f"/api/exam-templates/{template_id}/download-pdf", headers=headers)
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "pdf_not_generated"

    async def test_finalize_does_not_require_generate_first(
        self, staff_client, mock_storage, mock_omr_client
    ):
        client, token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(
            client, token, call_generate=False
        )

        response = await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        assert response.json()["omr_template_id"] is not None

    async def test_finalize_uploads_the_hand_made_mark_and_scan_templates(
        self, staff_client, mock_storage, mock_omr_client
    ):
        import json
        from services.exam_generator import _load_ubc_mark_template_bytes, _load_ubc_scan_template

        client, token = await staff_client()
        template_id = await self._setup_generated_template_with_answer_key(
            client, token, call_generate=True
        )
        mock_storage.upload_file.reset_mock()

        await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers={"Authorization": f"Bearer {token}"},
        )

        expected_scan_template, _ = _load_ubc_scan_template()
        uploads = {c.args[1]: c.args[0] for c in mock_storage.upload_file.call_args_list}
        assert uploads[f"generated/{template_id}/mark_template.json"] == _load_ubc_mark_template_bytes()
        assert json.loads(uploads[f"generated/{template_id}/scan_template.json"]) == expected_scan_template

    async def _setup_generated_template_with_answer_key(self, client, token, *, call_generate: bool):
        headers = {"Authorization": f"Bearer {token}"}
        template_id = await _setup_ubco_template(client, token)

        if call_generate:
            await client.post(f"/api/exam-templates/{template_id}/generate", headers=headers)

        course = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        exam = await client.post(
            "/api/exams",
            json={"name": "Midterm", "start_time": "2026-08-01T09:00:00+00:00",
                  "end_time": "2026-08-01T12:00:00+00:00", "role": "student",
                  "course_id": course.json()["id"], "exam_template_id": template_id},
            headers=headers,
        )
        exam_id = exam.json()["id"]

        ak_payload = {
            "exam_template_id": template_id,
            "exam_version": None,
            "answer_key": {
                str(i): {"grading_type": "single", "correct_choices": ["A"],
                          "points": 1.0, "partial_weights": None}
                for i in range(1, 101)
            },
            "scoring_rules": {"default_points_per_question": 1.0},
        }
        await client.post(f"/api/exams/{exam_id}/answer-keys", json=ak_payload, headers=headers)
        return template_id
