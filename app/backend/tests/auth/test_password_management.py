import pytest

from tests.auth.helpers import get_persisted_refresh_token

pytestmark = pytest.mark.db


async def test_change_password_updates_credentials_and_revokes_sessions(
    client,
    register_user,
    login_user,
    get_refresh_token_by_hash,
    get_user_by_email,
    db_session,
):
    register_response = await register_user()
    access_token = register_response.json()["access_token"]
    first_refresh_token = register_response.json()["refresh_token"]
    second_login_response = await login_user()
    second_refresh_token = second_login_response.json()["refresh_token"]
    user_before_password_change = await get_user_by_email("alice@example.com")
    password_changed_at_before = user_before_password_change.password_changed_at

    response = await client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "current_password": "Password123!",
            "new_password": "NewPassword123!",
        },
    )

    first_persisted_refresh_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        first_refresh_token,
    )
    second_persisted_refresh_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        second_refresh_token,
    )
    old_login = await login_user(password="Password123!")
    new_login = await login_user(password="NewPassword123!")
    await db_session.refresh(user_before_password_change)

    assert response.status_code == 204
    assert first_persisted_refresh_token.revoked_at is not None
    assert second_persisted_refresh_token.revoked_at is not None
    assert old_login.status_code == 401
    assert new_login.status_code == 200
    assert user_before_password_change.password_changed_at > password_changed_at_before


async def test_change_password_rejects_incorrect_current_password(
    client,
    register_user,
    login_user,
):
    register_response = await register_user()

    response = await client.post(
        "/api/auth/change-password",
        headers={
            "Authorization": f"Bearer {register_response.json()['access_token']}"
        },
        json={
            "current_password": "WrongPassword123!",
            "new_password": "NewPassword123!",
        },
    )
    original_login = await login_user(password="Password123!")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_current_password"
    assert original_login.status_code == 200


async def test_change_password_rejects_password_reuse(client, register_user):
    register_response = await register_user()

    response = await client.post(
        "/api/auth/change-password",
        headers={
            "Authorization": f"Bearer {register_response.json()['access_token']}"
        },
        json={
            "current_password": "Password123!",
            "new_password": "Password123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_reuse"


async def test_change_password_requires_authentication(client):
    response = await client.post(
        "/api/auth/change-password",
        json={
            "current_password": "Password123!",
            "new_password": "NewPassword123!",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_authorization_header"


async def test_change_password_validation_does_not_echo_password(
    client,
    register_user,
):
    register_response = await register_user()

    response = await client.post(
        "/api/auth/change-password",
        headers={
            "Authorization": f"Bearer {register_response.json()['access_token']}"
        },
        json={
            "current_password": "Password123!",
            "new_password": "weak",
        },
    )

    password_errors = [
        error
        for error in response.json()["error"]["details"]
        if error.get("loc") == ["body", "new_password"]
    ]

    assert response.status_code == 422
    assert password_errors
    assert all("input" not in error for error in password_errors)
