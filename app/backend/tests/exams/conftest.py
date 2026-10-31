import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.auth.conftest import use_test_auth_settings

from models.user import UserRole


@pytest.fixture
def staff_client(client, create_user, db_session):
    """Return (client, token) for a PROFESSOR-role user."""
    async def _staff_client(email: str = None, password: str = "Password123!"):
        from services import auth_sessions

        if email is None:
            email = f"prof_{uuid.uuid4().hex[:8]}@example.com"
        user = await create_user(email=email, password=password, role=UserRole.PROFESSOR)
        token_pair = await auth_sessions.issue_token_pair(db_session, user)
        return client, token_pair["access_token"]
    return _staff_client


@pytest.fixture
def mock_storage(client):
    """Override get_storage_repo with a MagicMock for the duration of the test."""
    from dependencies.storage_dep import get_storage_repo
    from main import app

    storage = MagicMock()
    storage.upload_file.return_value = {"status": "uploaded"}
    storage.download_file.return_value = b"%PDF-1.4 test-pdf-bytes"

    app.dependency_overrides[get_storage_dep := get_storage_repo] = lambda: storage
    yield storage


@pytest.fixture
def mock_omr_client():
    """Mock the OMR service upload calls so tests don't need a live OMR server."""
    with patch(
        "services.exam_generator.upload_preprocessing_template",
        new_callable=AsyncMock,
        return_value="pt-test",
    ), patch(
        "services.exam_generator.upload_marking_template",
        new_callable=AsyncMock,
        return_value="mt-test",
    ):
        yield

from sqlalchemy import update
from models.user import User, UserRole

@pytest.fixture
def authenticated_client(client, register_user, db_session):
    async def _authenticated_client(
        *,
        email: str = None,
        password: str = "Password123!",
    ):
        if email is None:
            email = f"user_{uuid.uuid4().hex[:8]}@example.com"

        response = await register_user(email=email, password=password)
        assert response.status_code == 200, response.json()
        token = response.json()["access_token"]

        await db_session.execute(
            update(User).where(User.email == email).values(role=UserRole.ADMIN.value)
        )
        await db_session.commit()

        return client, token

    return _authenticated_client


@pytest.fixture
def create_template(authenticated_client):
    """Create a standalone exam template and return its id."""
    async def _create_template(
        *,
        name: str = "Test Template",
        blueprint: str | None = "ubco_100",
        question_config: dict | None = None,
        n_versions: int = 4,
    ):
        client, token = await authenticated_client()
        headers = {"Authorization": f"Bearer {token}"}

        if blueprint:
            resp = await client.post(
                f"/api/exam-templates?blueprint={blueprint}&n_versions={n_versions}",
                headers=headers,
            )
        else:
            resp = await client.post(
                "/api/exam-templates",
                json={"name": name, "question_config": question_config, "n_versions": n_versions},
                headers=headers,
            )
        assert resp.status_code == 201, resp.json()
        return resp.json()["id"]

    return _create_template


@pytest.fixture
def create_exam(authenticated_client, create_template):
    async def _create_exam(
        *,
        course_id: str,
        exam_template_id: str | None = None,
        name: str = "Midterm",
        description: str = "2026S midterm 1",
        start_time: str = None,
        end_time: str = None,
        role: str = "student"
    ):
        client, token = await authenticated_client()

        if not exam_template_id:
            exam_template_id = await create_template()

        if not start_time:
            start_time = datetime.now(timezone.utc).isoformat()
        if not end_time:
            end_time = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()

        return await client.post(
            "/api/exams",
            json={
                "name": name,
                "description": description,
                "start_time": start_time,
                "end_time": end_time,
                "role": role,
                "course_id": course_id,
                "exam_template_id": exam_template_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    return _create_exam
