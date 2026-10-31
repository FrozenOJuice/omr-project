import uuid

import pytest

from core.tokens import hash_token
from models.user import UserRole

pytestmark = pytest.mark.db


async def test_admin_logout_user_sessions_requires_admin(
    client,
    register_user,
    auth_headers,
):
    register_response = await register_user()

    response = await client.post(
        f"/api/admin/users/{uuid.uuid4()}/logout-all",
        headers=auth_headers(register_response.json()["access_token"]),
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "insufficient_permissions"


async def test_admin_logout_user_sessions_revokes_active_refresh_tokens(
    client,
    admin_headers,
    create_user,
    login_user,
    get_refresh_token_by_hash,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)
    login_response = await login_user(email="student@example.com")
    refresh_token = login_response.json()["refresh_token"]

    response = await client.post(
        f"/api/admin/users/{user.id}/logout-all",
        headers=await admin_headers(),
    )
    persisted_refresh_token = await get_refresh_token_by_hash(hash_token(refresh_token))
    refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 204
    assert persisted_refresh_token.revoked_at is not None
    assert refresh_response.status_code == 401


async def test_admin_logout_user_sessions_returns_not_found_for_missing_user(
    client,
    admin_headers,
):
    response = await client.post(
        f"/api/admin/users/{uuid.uuid4()}/logout-all",
        headers=await admin_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"
