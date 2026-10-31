import uuid
import pytest
from sqlalchemy import select

from models.exam_answer_key import ExamAnswerKey
from models.exam_template import ExamTemplate
from models.omr_template import OMRTemplate
from models.scan import Scan
from models.user import User

pytestmark = pytest.mark.db


async def _create_course(client, headers):
    return await client.post(
        "/api/courses",
        json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
        headers=headers,
    )


async def _create_exam(client, headers, course_id, template_id, name="Midterm"):
    return await client.post(
        "/api/exams",
        json={
            "name": name,
            "start_time": "2026-06-25T09:00:00Z",
            "end_time": "2026-06-25T10:00:00Z",
            "role": "student",
            "course_id": course_id,
            "exam_template_id": template_id,
        },
        headers=headers,
    )


async def _create_custom_template(client, headers, name="Custom Template"):
    return await client.post(
        "/api/exam-templates",
        json={
            "name": name,
            "question_config": {"1": {"choices": ["A", "B"]}},
            "n_versions": 4,
        },
        headers=headers,
    )


async def _create_ubco_template(client, headers, *, versioned=False):
    query = "&version_from_q1=true" if versioned else ""
    return await client.post(
        f"/api/exam-templates?blueprint=ubco_100{query}", headers=headers
    )


async def _update_version_count(client, headers, template_id, count=2):
    return await client.patch(
        f"/api/exam-templates/{template_id}",
        json={"n_versions": count},
        headers=headers,
    )


async def _create_used_template(client, headers):
    course = await _create_course(client, headers)
    template = await client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
    exam = await _create_exam(
        client,
        headers,
        course.json()["id"],
        template.json()["id"],
    )
    return template.json(), exam.json()


async def _create_answer_key(client, headers, exam_id, template_id):
    return await client.post(
        f"/api/exams/{exam_id}/answer-keys",
        json={
            "exam_template_id": template_id,
            "answer_key": {
                "1": {
                    "grading_type": "single",
                    "correct_choices": ["A"],
                    "points": 1.0,
                },
            },
        },
        headers=headers,
    )


class TestCreateExamTemplate:
    async def test_create_template_via_ubco_blueprint_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "[UBCO] 100-Question Template"
        assert data["archived_at"] is None
        assert data["version"] == 1
        assert data["total_questions"] == 100
        assert data["n_versions"] == 1
        assert data["question_config"]["1"]["choices"] == ["A", "B", "C", "D", "E"]

    async def test_create_template_via_ubco_blueprint_with_version_from_q1(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/exam-templates?blueprint=ubco_100&version_from_q1=true",
            headers=headers,
        )

        assert response.status_code == 201
        data = response.json()
        assert data["version_from_q1"] is True
        assert data["total_questions"] == 99
        assert data["n_versions"] == 5
        assert "1" not in data["question_config"]
        assert data["question_config"]["2"]["choices"] == ["A", "B", "C", "D", "E"]

    async def test_ubco_version_selector_accepts_two_to_five_versions(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/exam-templates?blueprint=ubco_100&version_from_q1=true&n_versions=3",
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["n_versions"] == 3

        invalid = await client.post(
            "/api/exam-templates?blueprint=ubco_100&version_from_q1=true&n_versions=6",
            headers=headers,
        )
        assert invalid.status_code == 422

    async def test_create_template_via_ubco_blueprint_custom_name_gets_ubco_prefix(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/exam-templates?blueprint=ubco_100&name=Midterm%201",
            headers=headers,
        )

        assert response.status_code == 201
        assert response.json()["name"] == "[UBCO] Midterm 1"

    async def test_create_template_with_custom_payload_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "True/False Quiz",
                "question_config": {
                    "1": {"choices": ["True", "False"]},
                    "2": {"choices": ["A", "B", "C"]},
                },
            },
            headers=headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "True/False Quiz"
        assert data["total_questions"] == 2
        assert data["version"] == 1
        assert data["sections"] == [
            {
                "id": "section-1",
                "name": "Section 1",
                "type": "multiple_choice",
                "question_ids": ["1", "2"],
            }
        ]

    async def test_create_template_with_ordered_sections(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "Sectioned Exam",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                    "3": {"choices": ["A", "B"]},
                },
                "sections": [
                    {
                        "id": "concepts",
                        "name": "Concepts",
                        "question_ids": ["1", "2"],
                    },
                    {
                        "id": "applications",
                        "name": "Applications",
                        "question_ids": ["3"],
                    },
                ],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        assert [section["id"] for section in response.json()["sections"]] == [
            "concepts",
            "applications",
        ]

    async def test_create_template_with_true_false_section(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "True/False Quiz",
                "question_config": {"1": {"choices": ["T", "F"]}},
                "sections": [{
                    "id": "true-false",
                    "name": "True / False",
                    "type": "true_false",
                    "question_ids": ["1"],
                }],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 201
        assert response.json()["sections"][0]["type"] == "true_false"

    async def test_create_template_rejects_wrong_true_false_choices(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "Invalid True/False Quiz",
                "question_config": {"1": {"choices": ["A", "B"]}},
                "sections": [{
                    "id": "true-false",
                    "name": "True / False",
                    "type": "true_false",
                    "question_ids": ["1"],
                }],
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    @pytest.mark.parametrize(
        "sections",
        [
            [
                {"id": "one", "name": "One", "question_ids": ["1"]},
                {"id": "two", "name": "Two", "question_ids": ["1", "2"]},
            ],
            [{"id": "one", "name": "One", "question_ids": ["1"]}],
            [{"id": "one", "name": "One", "question_ids": ["1", "3"]}],
        ],
    )
    async def test_create_template_rejects_invalid_section_membership(
        self, authenticated_client, sections
    ):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "Invalid Sections",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                },
                "sections": sections,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422

    async def test_create_template_missing_body_without_blueprint(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 400

    async def test_create_template_insufficient_choices_fails(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "Bad Template",
                "question_config": {"1": {"choices": ["A"]}},
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 422

    async def test_create_template_rejects_more_than_200_questions(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        response = await client.post(
            "/api/exam-templates",
            json={
                "name": "Too Large",
                "question_config": {
                    str(index): {"choices": ["A", "B"]}
                    for index in range(1, 202)
                },
            },
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 422


class TestUpdateExamTemplate:
    async def test_update_unused_custom_template_version_count(
        self, authenticated_client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)
        template_id = uuid.UUID(template.json()["id"])
        db_template = await db_session.get(ExamTemplate, template_id)
        omr_template = OMRTemplate(name="Old generated template", page_count=1)
        db_session.add(omr_template)
        await db_session.flush()
        db_template.generated_pdf_path = "generated/custom/bubble_sheet.pdf"
        db_template.omr_template_id = omr_template.id
        await db_session.flush()

        response = await _update_version_count(client, headers, template_id)

        assert response.status_code == 200
        assert response.json()["n_versions"] == 2
        assert response.json()["generated_pdf_path"] is None
        assert response.json()["omr_template_id"] is None

    async def test_update_assigned_custom_template_version_count_conflicts(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        course = await _create_course(client, headers)
        template = await _create_custom_template(
            client, headers, "Assigned Custom Template"
        )
        await _create_exam(
            client,
            headers,
            course.json()["id"],
            template.json()["id"],
        )

        response = await _update_version_count(
            client, headers, template.json()["id"]
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_versions_locked"

    async def test_update_unused_ubco_version_count(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_ubco_template(client, headers, versioned=True)

        response = await _update_version_count(
            client, headers, template.json()["id"]
        )

        assert response.status_code == 200
        assert response.json()["n_versions"] == 2

    async def test_update_assigned_ubco_version_count_conflicts(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        course = await _create_course(client, headers)
        template = await _create_ubco_template(client, headers, versioned=True)
        await _create_exam(
            client,
            headers,
            course.json()["id"],
            template.json()["id"],
        )

        response = await _update_version_count(
            client, headers, template.json()["id"]
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_versions_locked"

    async def test_update_ubco_without_q1_rejects_version_count(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_ubco_template(client, headers)

        response = await _update_version_count(
            client, headers, template.json()["id"]
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "invalid_template_versions"

    async def test_update_template_question_config_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Custom Template",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                },
            },
            headers=headers,
        )
        template_id = template.json()["id"]

        patch_response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"question_config": {"1": {"choices": ["A", "B", "C"]}}},
            headers=headers,
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["question_config"]["1"]["choices"] == ["A", "B", "C"]
        assert "2" not in patch_response.json()["question_config"]
        assert patch_response.json()["sections"][0]["question_ids"] == ["1"]

    async def test_question_config_update_preserves_existing_sections(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Two Sections",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                    "3": {"choices": ["A", "B"]},
                },
                "sections": [
                    {"id": "first", "name": "First", "question_ids": ["1"]},
                    {"id": "second", "name": "Second", "question_ids": ["2", "3"]},
                ],
            },
            headers=headers,
        )

        response = await client.patch(
            f"/api/exam-templates/{template.json()['id']}",
            json={
                "question_config": {
                    "1": {"choices": ["A", "B", "C"]},
                    "3": {"choices": ["A", "B"]},
                }
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["sections"] == [
            {
                "id": "first",
                "name": "First",
                "type": "multiple_choice",
                "question_ids": ["1"],
            },
            {
                "id": "second",
                "name": "Second",
                "type": "multiple_choice",
                "question_ids": ["3"],
            },
        ]

    async def test_question_config_update_requires_sections_for_new_questions(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)

        response = await client.patch(
            f"/api/exam-templates/{template.json()['id']}",
            json={
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                }
            },
            headers=headers,
        )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "template_sections_required"

    async def test_update_template_sections_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Custom Template",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                },
            },
            headers=headers,
        )

        response = await client.patch(
            f"/api/exam-templates/{template.json()['id']}",
            json={
                "sections": [
                    {"id": "first", "name": "First", "question_ids": ["1"]},
                    {"id": "second", "name": "Second", "question_ids": ["2"]},
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert [section["name"] for section in response.json()["sections"]] == [
            "First",
            "Second",
        ]

    async def test_removing_section_deletes_its_questions(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Two Sections",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                },
                "sections": [
                    {"id": "keep", "name": "Keep", "question_ids": ["1"]},
                    {"id": "remove", "name": "Remove", "question_ids": ["2"]},
                ],
            },
            headers=headers,
        )

        response = await client.patch(
            f"/api/exam-templates/{template.json()['id']}",
            json={
                "sections": [
                    {"id": "keep", "name": "Keep", "question_ids": ["1"]}
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["total_questions"] == 1
        assert set(response.json()["question_config"]) == {"1"}

    async def test_trimming_kept_section_deletes_removed_questions(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Trim Section",
                "question_config": {
                    "1": {"choices": ["A", "B"]},
                    "2": {"choices": ["A", "B"]},
                },
                "sections": [
                    {"id": "keep", "name": "Keep", "question_ids": ["1", "2"]}
                ],
            },
            headers=headers,
        )

        response = await client.patch(
            f"/api/exam-templates/{template.json()['id']}",
            json={
                "sections": [
                    {"id": "keep", "name": "Keep", "question_ids": ["1"]}
                ]
            },
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["total_questions"] == 1
        assert set(response.json()["question_config"]) == {"1"}

    async def test_update_ubc_blueprint_question_config_conflicts(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates?blueprint=ubco_100", headers=headers
        )
        template_id = template.json()["id"]

        response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"question_config": {"1": {"choices": ["A", "B", "C"]}}},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_locked"

    async def test_update_template_name_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={"name": "Quiz", "question_config": {"1": {"choices": ["A", "B"]}}},
            headers=headers,
        )
        template_id = template.json()["id"]

        patch_response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"name": "Renamed Template"},
            headers=headers,
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "Renamed Template"

    async def test_update_template_name_keeps_ubco_prefix_on_blueprint(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates?blueprint=ubco_100", headers=headers
        )
        template_id = template.json()["id"]

        patch_response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"name": "Midterm 1"},
            headers=headers,
        )
        assert patch_response.status_code == 200
        assert patch_response.json()["name"] == "[UBCO] Midterm 1"

    async def test_rename_used_template_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, _ = await _create_used_template(client, headers)

        patch_response = await client.patch(
            f"/api/exam-templates/{template['id']}",
            json={"name": "Renamed Used Template"},
            headers=headers,
        )

        assert patch_response.status_code == 200
        # _create_used_template uses the ubco_100 blueprint, so the rename
        # keeps its "[UBCO] " prefix (see test_update_template_name_keeps_ubco_prefix_on_blueprint).
        assert patch_response.json()["name"] == "[UBCO] Renamed Used Template"

    async def test_update_used_template_question_config_conflicts(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, exam = await _create_used_template(client, headers)

        response = await client.patch(
            f"/api/exam-templates/{template['id']}",
            json={"question_config": {"1": {"choices": ["A", "B"]}}},
            headers=headers,
        )

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "template_locked"
        assert error["details"]["exams"][0]["id"] == exam["id"]

    async def test_update_generated_but_unused_template_question_config_succeeds(
        self, authenticated_client, db_session
    ):
        # A generated PDF or registered OMR template can be regenerated for
        # free as long as no exam actually uses the template yet. Only real
        # usage (see test_update_used_template_question_config_conflicts)
        # locks the layout.
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post(
            "/api/exam-templates",
            json={
                "name": "Generated Template",
                "question_config": {"1": {"choices": ["A", "B"]}},
            },
            headers=headers,
        )
        template_id = uuid.UUID(template.json()["id"])

        db_template = await db_session.get(ExamTemplate, template_id)
        db_template.generated_pdf_path = "generated/test/bubble_sheet.pdf"
        await db_session.flush()

        response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"question_config": {"1": {"choices": ["A", "B", "C"]}}},
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["question_config"]["1"]["choices"] == ["A", "B", "C"]
        assert response.json()["generated_pdf_path"] is None
        assert response.json()["omr_template_id"] is None

    async def test_update_template_forbidden_for_non_owner(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="prof_a@ubc.ca")
        template = await client_a.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        template_id = template.json()["id"]

        client_b, token_b = await authenticated_client(email="prof_b@ubc.ca")
        response = await client_b.patch(
            f"/api/exam-templates/{template_id}",
            json={"question_config": {"1": {"choices": ["A", "B"]}}},
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 403


class TestGetExamTemplate:
    async def test_get_template_by_id_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
        template_id = template.json()["id"]

        get_response = await client.get(f"/api/exam-templates/{template_id}", headers=headers)
        assert get_response.status_code == 200
        assert get_response.json()["id"] == template_id

    async def test_get_template_forbidden_for_non_owner(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="template_owner@ubc.ca")
        template = await client_a.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        template_id = template.json()["id"]

        client_b, token_b = await authenticated_client(email="template_viewer@ubc.ca")
        response = await client_b.get(
            f"/api/exam-templates/{template_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 403

    async def test_list_templates_only_returns_own_templates(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="owner_a@ubc.ca")
        client_b, token_b = await authenticated_client(email="owner_b@ubc.ca")

        own_template = await client_a.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        other_template = await client_b.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_b}"},
        )

        response = await client_a.get(
            "/api/exam-templates",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 200
        ids = {t["id"] for t in response.json()}
        assert own_template.json()["id"] in ids
        assert other_template.json()["id"] not in ids

    async def test_list_my_templates(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="owner_a@ubc.ca")
        client_b, token_b = await authenticated_client(email="owner_b@ubc.ca")

        await client_a.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        await client_b.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_b}"},
        )

        response = await client_a.get(
            "/api/exam-templates/me",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert all(t["created_by"] is not None for t in data)

    async def test_get_template_usage_lists_affected_exams(
        self, authenticated_client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, exam = await _create_used_template(client, headers)
        answer_key = await _create_answer_key(client, headers, exam["id"], template["id"])
        assert answer_key.status_code == 201

        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()
        db_session.add(
            Scan(
                exam_id=uuid.UUID(exam["id"]),
                exam_template_id=uuid.UUID(template["id"]),
                uploader_user_id=uploader.id,
                path="scans/test.pdf",
            )
        )
        await db_session.flush()

        response = await client.get(
            f"/api/exam-templates/{template['id']}/usage",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["template_id"] == template["id"]
        assert data["exam_count"] == 1
        assert data["answer_key_count"] == 1
        assert data["scan_count"] == 1
        assert data["exams"] == [
            {
                "id": exam["id"],
                "name": "Midterm",
                "course_id": exam["course_id"],
                "answer_key_count": 1,
                "scan_count": 1,
            }
        ]


class TestArchiveExamTemplate:
    async def test_archive_hides_template_without_detaching_existing_exam(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, exam = await _create_used_template(client, headers)

        archive_response = await client.post(
            f"/api/exam-templates/{template['id']}/archive",
            headers=headers,
        )

        assert archive_response.status_code == 200
        assert archive_response.json()["archived_at"] is not None

        active_response = await client.get(
            "/api/exam-templates/me",
            headers=headers,
        )
        assert template["id"] not in {
            item["id"] for item in active_response.json()
        }

        all_response = await client.get(
            "/api/exam-templates/me?include_archived=true",
            headers=headers,
        )
        archived = next(
            item for item in all_response.json() if item["id"] == template["id"]
        )
        assert archived["archived_at"] is not None

        get_response = await client.get(
            f"/api/exam-templates/{template['id']}",
            headers=headers,
        )
        assert get_response.status_code == 200

        exam_response = await client.get(
            f"/api/exams/{exam['id']}",
            headers=headers,
        )
        assert exam_response.status_code == 200
        assert exam_response.json()["exam_template_id"] == template["id"]

    async def test_restore_makes_template_active_again(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)
        template_id = template.json()["id"]

        await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )
        restored = await client.post(
            f"/api/exam-templates/{template_id}/restore",
            headers=headers,
        )

        assert restored.status_code == 200
        assert restored.json()["archived_at"] is None
        active_response = await client.get(
            "/api/exam-templates/me",
            headers=headers,
        )
        assert template_id in {item["id"] for item in active_response.json()}

    async def test_archive_and_restore_are_idempotent(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)
        template_id = template.json()["id"]

        first_archive = await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )
        second_archive = await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )
        assert second_archive.status_code == 200
        assert (
            second_archive.json()["archived_at"]
            == first_archive.json()["archived_at"]
        )

        first_restore = await client.post(
            f"/api/exam-templates/{template_id}/restore",
            headers=headers,
        )
        second_restore = await client.post(
            f"/api/exam-templates/{template_id}/restore",
            headers=headers,
        )
        assert first_restore.status_code == 200
        assert second_restore.status_code == 200
        assert second_restore.json()["archived_at"] is None

    async def test_archived_template_is_read_only(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)
        template_id = template.json()["id"]
        await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )

        response = await client.patch(
            f"/api/exam-templates/{template_id}",
            json={"name": "Archived rename"},
            headers=headers,
        )

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_archived_read_only"

    async def test_archived_template_cannot_be_generated_or_finalized(
        self, authenticated_client
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template = await _create_custom_template(client, headers)
        template_id = template.json()["id"]
        await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )

        generate_response = await client.post(
            f"/api/exam-templates/{template_id}/generate",
            headers=headers,
        )
        finalize_response = await client.post(
            f"/api/exam-templates/{template_id}/finalize",
            headers=headers,
        )

        assert generate_response.status_code == 409
        assert (
            generate_response.json()["error"]["code"]
            == "template_archived_read_only"
        )
        assert finalize_response.status_code == 409
        assert (
            finalize_response.json()["error"]["code"]
            == "template_archived_read_only"
        )

    async def test_non_owner_cannot_archive_or_restore(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="archive_owner@ubc.ca")
        template = await _create_custom_template(
            client_a,
            {"Authorization": f"Bearer {token_a}"},
        )

        client_b, token_b = await authenticated_client(email="archive_other@ubc.ca")
        other_headers = {"Authorization": f"Bearer {token_b}"}
        archive_response = await client_b.post(
            f"/api/exam-templates/{template.json()['id']}/archive",
            headers=other_headers,
        )
        restore_response = await client_b.post(
            f"/api/exam-templates/{template.json()['id']}/restore",
            headers=other_headers,
        )

        assert archive_response.status_code == 403
        assert restore_response.status_code == 403


class TestDeleteExamTemplate:
    async def test_delete_template_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        template = await client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
        template_id = template.json()["id"]

        delete_response = await client.delete(f"/api/exam-templates/{template_id}", headers=headers)
        assert delete_response.status_code == 204

        get_response = await client.get(f"/api/exam-templates/{template_id}", headers=headers)
        assert get_response.status_code == 404

    async def test_delete_used_template_returns_conflict_with_usage(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, exam = await _create_used_template(client, headers)

        response = await client.delete(
            f"/api/exam-templates/{template['id']}",
            headers=headers,
        )

        assert response.status_code == 409
        error = response.json()["error"]
        assert error["code"] == "template_in_use"
        assert error["details"]["exams"][0]["id"] == exam["id"]

    async def test_force_delete_used_template_detaches_exam_and_dependents(
        self, authenticated_client, db_session
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}
        template, exam = await _create_used_template(client, headers)
        answer_key = await _create_answer_key(client, headers, exam["id"], template["id"])
        assert answer_key.status_code == 201

        uploader = (await db_session.execute(select(User).limit(1))).scalar_one()
        scan = Scan(
            exam_id=uuid.UUID(exam["id"]),
            exam_template_id=uuid.UUID(template["id"]),
            uploader_user_id=uploader.id,
            path="scans/test.pdf",
        )
        db_session.add(scan)
        await db_session.flush()

        delete_response = await client.delete(
            f"/api/exam-templates/{template['id']}?force=true",
            headers=headers,
        )
        assert delete_response.status_code == 204

        get_template = await client.get(f"/api/exam-templates/{template['id']}", headers=headers)
        assert get_template.status_code == 404

        get_exam = await client.get(f"/api/exams/{exam['id']}", headers=headers)
        assert get_exam.status_code == 200
        exam_data = get_exam.json()
        assert exam_data["exam_template_id"] is None
        assert exam_data["template_missing"] is True
        assert exam_data["template_warning"]

        update_exam = await client.patch(
            f"/api/exams/{exam['id']}",
            json={"name": "Renamed Midterm"},
            headers=headers,
        )
        assert update_exam.status_code == 200
        update_data = update_exam.json()
        assert update_data["exam_template_id"] is None
        assert update_data["template_missing"] is True
        assert update_data["template_warning"]

        my_exams = await client.get("/api/exams/my", headers=headers)
        assert my_exams.status_code == 200
        my_exam = next(e for e in my_exams.json() if e["id"] == exam["id"])
        assert my_exam["exam_template_id"] is None
        assert my_exam["template_missing"] is True
        assert my_exam["template_warning"]

        db_answer_key = await db_session.get(ExamAnswerKey, uuid.UUID(answer_key.json()["id"]))
        db_scan = await db_session.get(Scan, scan.id)
        assert db_answer_key.exam_template_id is None
        assert db_scan.exam_template_id is None

    async def test_delete_template_forbidden_for_non_owner(self, authenticated_client):
        client_a, token_a = await authenticated_client(email="prof_a@ubc.ca")
        template = await client_a.post(
            "/api/exam-templates?blueprint=ubco_100",
            headers={"Authorization": f"Bearer {token_a}"},
        )
        template_id = template.json()["id"]

        client_b, token_b = await authenticated_client(email="prof_b@ubc.ca")
        response = await client_b.delete(
            f"/api/exam-templates/{template_id}",
            headers={"Authorization": f"Bearer {token_b}"},
        )
        assert response.status_code == 403

    async def test_delete_non_existent_template_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        response = await client.delete(
            f"/api/exam-templates/{uuid.uuid4()}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 404


class TestCreateExamWithTemplate:
    async def test_create_exam_requires_template_id(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-25T09:00:00Z",
                "end_time": "2026-06-25T10:00:00Z",
                "role": "student",
                "course_id": course.json()["id"],
            },
            headers=headers,
        )
        assert response.status_code == 422

    async def test_create_exam_with_template_id_success(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )
        template = await client.post("/api/exam-templates?blueprint=ubco_100", headers=headers)
        template_id = template.json()["id"]

        response = await client.post(
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
        assert response.status_code == 201
        data = response.json()
        assert data["exam_template_id"] == template_id

    async def test_create_exam_rejects_archived_template(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses",
            json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"},
            headers=headers,
        )
        template = await _create_custom_template(client, headers)
        template_id = template.json()["id"]
        await client.post(
            f"/api/exam-templates/{template_id}/archive",
            headers=headers,
        )

        response = await client.post(
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

        assert response.status_code == 409
        assert response.json()["error"]["code"] == "template_archived"

    async def test_create_exam_with_invalid_template_id_returns_404(self, authenticated_client):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        course = await client.post(
            "/api/courses", json={"name": "COSC 499", "academic_term_id": "00000000-0000-0000-0007-000000000001"}, headers=headers
        )

        response = await client.post(
            "/api/exams",
            json={
                "name": "Midterm",
                "start_time": "2026-06-25T09:00:00Z",
                "end_time": "2026-06-25T10:00:00Z",
                "role": "student",
                "course_id": course.json()["id"],
                "exam_template_id": str(uuid.uuid4()),
            },
            headers=headers,
        )
        assert response.status_code == 404
