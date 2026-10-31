import pytest

from models.user import AccountStatus
from models.user import UserRole

pytestmark = pytest.mark.db


async def test_list_users_requires_admin(client, register_user, auth_headers):
    register_response = await register_user()

    response = await client.get(
        "/api/admin/users",
        headers=auth_headers(register_response.json()["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"


async def test_list_users_returns_accounts_for_admin(
    client,
    admin_headers,
    create_user,
    login_user,
):
    await create_user(email="student@example.com", role=UserRole.STUDENT)
    await create_user(email="professor@example.com", role=UserRole.PROFESSOR)
    await login_user(email="student@example.com")

    response = await client.get(
        "/api/admin/users",
        headers=await admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    emails = {user["email"] for user in body["items"]}
    assert {
        "admin@example.com",
        "student@example.com",
        "professor@example.com",
    } <= emails
    assert body["total"] == 3
    assert body["limit"] == 50
    assert body["offset"] == 0
    active_sessions = {
        user["email"]: user["active_session"]
        for user in body["items"]
    }
    assert active_sessions["student@example.com"] is True
    assert active_sessions["professor@example.com"] is False


async def test_list_users_supports_pagination_search_and_filters(
    client,
    admin_headers,
    create_user,
):
    await create_user(
        first_name="Student",
        last_name="One",
        email="student@example.com",
        role=UserRole.STUDENT,
    )
    await create_user(
        first_name="Professor",
        last_name="One",
        email="professor@example.com",
        role=UserRole.PROFESSOR,
        status=AccountStatus.DISABLED,
    )

    response = await client.get(
        "/api/admin/users",
        params={
            "search": "professor",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.DISABLED.value,
            "limit": 1,
            "offset": 0,
        },
        headers=await admin_headers(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["limit"] == 1
    assert body["offset"] == 0
    assert body["items"][0]["email"] == "professor@example.com"
