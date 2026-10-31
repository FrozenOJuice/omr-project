from datetime import datetime
from datetime import timedelta
from datetime import timezone

import pytest

from core.tokens import hash_token
from models.password_reset_token import PasswordResetToken
from models.user import AccountStatus
from tests.auth.helpers import get_persisted_refresh_token

pytestmark = pytest.mark.db

GENERIC_MESSAGE = "If an account exists for that email, a reset link has been sent."


@pytest.fixture
def capture_reset_email(monkeypatch):
    deliveries = []

    async def capture(email: str, token: str) -> None:
        deliveries.append({"email": email, "token": token})

    from services import auth_passwords

    monkeypatch.setattr(auth_passwords, "send_password_reset_email", capture)

    return deliveries


async def test_password_reset_request_is_generic_for_unknown_email(
    client,
    capture_reset_email,
):
    response = await client.post(
        "/api/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )

    assert response.status_code == 202
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert capture_reset_email == []


async def test_password_reset_request_stores_only_hash_and_sends_raw_token(
    client,
    register_user,
    capture_reset_email,
    get_password_reset_token_by_hash,
):
    await register_user()

    response = await client.post(
        "/api/auth/password-reset/request",
        json={"email": "ALICE@example.com"},
    )

    assert response.status_code == 202
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert len(capture_reset_email) == 1

    delivery = capture_reset_email[0]
    persisted_token = await get_password_reset_token_by_hash(
        hash_token(delivery["token"])
    )

    assert delivery["email"] == "alice@example.com"
    assert persisted_token is not None
    assert persisted_token.token_hash == hash_token(delivery["token"])
    assert persisted_token.token_hash != delivery["token"]
    remaining_lifetime = persisted_token.expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=29) < remaining_lifetime <= timedelta(minutes=30)
    assert persisted_token.used_at is None
    assert persisted_token.revoked_at is None


async def test_password_reset_request_is_generic_for_disabled_account(
    client,
    create_user,
    capture_reset_email,
):
    await create_user(
        email="disabled@example.com",
        status=AccountStatus.DISABLED,
    )

    response = await client.post(
        "/api/auth/password-reset/request",
        json={"email": "disabled@example.com"},
    )

    assert response.status_code == 202
    assert response.json() == {"message": GENERIC_MESSAGE}
    assert capture_reset_email == []


async def test_new_password_reset_request_revokes_previous_token(
    client,
    register_user,
    capture_reset_email,
    get_password_reset_token_by_hash,
):
    await register_user()

    await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )
    first_token = capture_reset_email[-1]["token"]

    await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )
    second_token = capture_reset_email[-1]["token"]

    first_persisted = await get_password_reset_token_by_hash(hash_token(first_token))
    second_persisted = await get_password_reset_token_by_hash(
        hash_token(second_token)
    )

    assert first_persisted.revoked_at is not None
    assert second_persisted.revoked_at is None

    revoked_response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": first_token,
            "new_password": "NewPassword123!",
        },
    )

    assert revoked_response.status_code == 400
    assert revoked_response.json()["error"]["code"] == "invalid_reset_token"


async def test_password_reset_confirm_updates_password_and_revokes_sessions(
    client,
    register_user,
    login_user,
    capture_reset_email,
    get_password_reset_token_by_hash,
    get_refresh_token_by_hash,
):
    register_response = await register_user()
    first_refresh_token = register_response.json()["refresh_token"]
    second_login_response = await login_user()
    second_refresh_token = second_login_response.json()["refresh_token"]
    await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )
    reset_token = capture_reset_email[0]["token"]

    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "NewPassword123!",
        },
    )

    persisted_reset_token = await get_password_reset_token_by_hash(
        hash_token(reset_token)
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

    assert response.status_code == 204
    assert persisted_reset_token.used_at is not None
    assert first_persisted_refresh_token.revoked_at is not None
    assert second_persisted_refresh_token.revoked_at is not None
    assert old_login.status_code == 401
    assert new_login.status_code == 200


async def test_password_reset_rejects_current_password(
    client,
    register_user,
    capture_reset_email,
):
    await register_user()
    await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )

    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": capture_reset_email[0]["token"],
            "new_password": "Password123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "password_reuse"


async def test_password_reset_token_cannot_be_reused(
    client,
    register_user,
    capture_reset_email,
):
    await register_user()
    await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )
    reset_token = capture_reset_email[0]["token"]
    payload = {
        "token": reset_token,
        "new_password": "NewPassword123!",
    }

    first_response = await client.post(
        "/api/auth/password-reset/confirm",
        json=payload,
    )
    reuse_response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": reset_token,
            "new_password": "AnotherPassword123!",
        },
    )

    assert first_response.status_code == 204
    assert reuse_response.status_code == 400
    assert reuse_response.json()["error"]["code"] == "invalid_reset_token"


async def test_password_reset_confirm_rejects_expired_token(
    client,
    create_user,
    db_session,
):
    user = await create_user()
    raw_token = "expired-password-reset-token-value-123456"
    db_session.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await db_session.commit()

    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": raw_token,
            "new_password": "NewPassword123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_reset_token"


async def test_password_reset_confirm_rejects_unknown_token(client):
    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": "unknown-password-reset-token-value-123456",
            "new_password": "NewPassword123!",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_reset_token"


async def test_password_reset_validation_does_not_echo_password(client):
    response = await client.post(
        "/api/auth/password-reset/confirm",
        json={
            "token": "unknown-password-reset-token-value-123456",
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
