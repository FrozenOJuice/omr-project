import pytest

from core import tokens
from tests.auth.helpers import get_persisted_refresh_token

pytestmark = pytest.mark.db


async def test_refresh_rotates_refresh_token(
    client,
    register_user,
    get_refresh_token_by_hash,
):
    register_response = await register_user()
    refresh_token = register_response.json()["refresh_token"]
    old_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        refresh_token,
    )

    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 200
    assert response.json()["access_token"]
    assert response.json()["refresh_token"]

    new_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        response.json()["refresh_token"],
    )

    assert new_persisted_token is not None
    assert new_persisted_token.token_hash != response.json()["refresh_token"]
    assert old_persisted_token.revoked_at is not None
    assert old_persisted_token.replaced_by_token_id == new_persisted_token.id


async def test_refresh_rejects_reused_refresh_token(client, register_user):
    register_response = await register_user()
    refresh_token = register_response.json()["refresh_token"]

    first_refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )
    reuse_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert first_refresh_response.status_code == 200
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_token_reuse_revokes_all_active_sessions(
    client,
    register_user,
    login_user,
    get_refresh_token_by_hash,
):
    register_response = await register_user()
    first_refresh_token = register_response.json()["refresh_token"]

    second_login_response = await login_user()
    second_refresh_token = second_login_response.json()["refresh_token"]

    rotation_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": first_refresh_token},
    )
    rotated_refresh_token = rotation_response.json()["refresh_token"]

    reuse_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": first_refresh_token},
    )

    second_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        second_refresh_token,
    )
    rotated_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        rotated_refresh_token,
    )

    assert rotation_response.status_code == 200
    assert reuse_response.status_code == 401
    assert reuse_response.json()["error"]["code"] == "invalid_refresh_token"
    assert second_persisted_token.revoked_at is not None
    assert rotated_persisted_token.revoked_at is not None


async def test_refresh_rejects_unpersisted_refresh_token(
    client,
    create_user,
):
    user = await create_user()
    refresh_token = tokens.create_refresh_token(str(user.id))

    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": refresh_token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_refresh_rejects_access_token(client, register_user):
    register_response = await register_user()
    access_token = register_response.json()["access_token"]

    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": access_token},
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_refresh_token"


async def test_logout_revokes_only_submitted_refresh_token(
    client,
    register_user,
    login_user,
    get_refresh_token_by_hash,
):
    register_response = await register_user()
    first_refresh_token = register_response.json()["refresh_token"]

    second_login_response = await login_user()
    second_refresh_token = second_login_response.json()["refresh_token"]

    response = await client.post(
        "/api/auth/logout",
        json={"refresh_token": first_refresh_token},
    )

    first_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        first_refresh_token,
    )
    second_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        second_refresh_token,
    )
    assert response.status_code == 204
    assert first_persisted_token.revoked_at is not None
    assert first_persisted_token.replaced_by_token_id is None
    assert second_persisted_token.revoked_at is None

    logged_out_refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": first_refresh_token},
    )
    active_refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": second_refresh_token},
    )

    assert logged_out_refresh_response.status_code == 401
    assert (
        logged_out_refresh_response.json()["error"]["code"]
        == "invalid_refresh_token"
    )
    assert active_refresh_response.status_code == 200


async def test_logout_all_revokes_all_refresh_tokens(
    client,
    register_user,
    login_user,
    get_refresh_token_by_hash,
):
    register_response = await register_user()
    first_refresh_token = register_response.json()["refresh_token"]

    second_login_response = await login_user()
    second_refresh_token = second_login_response.json()["refresh_token"]

    response = await client.post(
        "/api/auth/logout-all",
        json={"refresh_token": first_refresh_token},
    )

    first_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        first_refresh_token,
    )
    second_persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        second_refresh_token,
    )
    first_refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": first_refresh_token},
    )
    second_refresh_response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": second_refresh_token},
    )

    assert response.status_code == 204
    assert first_persisted_token.revoked_at is not None
    assert second_persisted_token.revoked_at is not None
    assert first_refresh_response.status_code == 401
    assert first_refresh_response.json()["error"]["code"] == "invalid_refresh_token"
    assert second_refresh_response.status_code == 401
    assert second_refresh_response.json()["error"]["code"] == "invalid_refresh_token"
