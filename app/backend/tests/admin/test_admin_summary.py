import pytest

from models.user import AccountStatus
from models.user import UserRole

pytestmark = pytest.mark.db


async def test_admin_summary_requires_admin(client, register_user, auth_headers):
    register_response = await register_user()

    response = await client.get(
        "/api/admin/summary",
        headers=auth_headers(register_response.json()["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"


async def test_admin_summary_returns_user_and_session_counts(
    client,
    admin_headers,
    create_user,
):
    await create_user(email="student@example.com", role=UserRole.STUDENT)
    await create_user(
        email="professor@example.com",
        role=UserRole.PROFESSOR,
        status=AccountStatus.DISABLED,
    )

    response = await client.get(
        "/api/admin/summary",
        headers=await admin_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "total_users": 3,
        "active_users": 2,
        "disabled_users": 1,
        "admins": 1,
        "professors": 1,
        "students": 1,
        "active_sessions": 1,
    }
