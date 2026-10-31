import pytest

from core import tokens
from models.user import AccountStatus
from models.user import UserRole
from tests.auth.helpers import assert_account_disabled
from tests.auth.helpers import assert_invalid_credentials
from tests.auth.helpers import get_persisted_refresh_token

pytestmark = pytest.mark.db


async def test_register_creates_student_and_returns_tokens(
    register_user,
    get_user_by_email,
    get_refresh_token_by_hash,
):
    response = await register_user(
        first_name=" Alice ",
        last_name=" Example ",
        email="ALICE@example.com",
    )

    assert response.status_code == 200

    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"

    user = await get_user_by_email("alice@example.com")
    assert user is not None
    assert user.first_name == "Alice"
    assert user.last_name == "Example"
    assert user.role == UserRole.STUDENT.value
    assert user.status == AccountStatus.ACTIVE.value

    persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        body["refresh_token"],
    )
    refresh_payload = tokens.decode_refresh_token(body["refresh_token"])

    assert persisted_token is not None
    assert persisted_token.user_id == user.id
    assert persisted_token.token_hash == tokens.hash_token(body["refresh_token"])
    assert persisted_token.token_hash != body["refresh_token"]
    assert persisted_token.jti == refresh_payload["jti"]
    assert persisted_token.expires_at is not None
    assert persisted_token.revoked_at is None
    assert persisted_token.replaced_by_token_id is None


async def test_register_rejects_duplicate_email(register_user):
    first_response = await register_user(email="alice@example.com")
    second_response = await register_user(email="ALICE@example.com")

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "user_exists"


async def test_register_rejects_duplicate_email_from_db_race(
    client,
    create_user,
    monkeypatch,
):
    await create_user(email="alice@example.com")

    from services import auth_credentials

    async def miss_duplicate_precheck(db, email):
        return None

    monkeypatch.setattr(auth_credentials.users, "get_by_email", miss_duplicate_precheck)

    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.com",
            "password": "Password123!",
            "student_number": "10000002",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_exists"


async def test_register_rejects_weak_password_without_echoing_password(client):
    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.com",
            "password": "weak",
        },
    )

    assert response.status_code == 422

    details = response.json()["error"]["details"]
    password_errors = [
        error
        for error in details
        if error.get("loc") == ["body", "password"]
    ]
    assert password_errors
    assert all("input" not in error for error in password_errors)


async def test_register_student_without_student_number_rejected(client):
    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.com",
            "password": "Password123!",
        },
    )

    assert response.status_code == 422


async def test_register_student_with_malformed_student_number_rejected(client):
    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Alice",
            "last_name": "Example",
            "email": "alice@example.com",
            "password": "Password123!",
            "student_number": "not-a-number",
        },
    )

    assert response.status_code == 422


async def test_register_professor_with_student_number_rejected(client):
    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Prof",
            "last_name": "Example",
            "email": "prof@example.com",
            "password": "Password123!",
            "role": "professor",
            "student_number": "12345678",
        },
    )

    assert response.status_code == 422


async def test_register_professor_without_student_number_succeeds(client, get_user_by_email):
    response = await client.post(
        "/api/auth/register",
        json={
            "first_name": "Prof",
            "last_name": "Example",
            "email": "prof@example.com",
            "password": "Password123!",
            "role": "professor",
        },
    )

    assert response.status_code == 200
    user = await get_user_by_email("prof@example.com")
    assert user is not None
    assert user.student_number is None


async def test_login_returns_tokens(register_user, login_user):
    await register_user()

    response = await login_user(email="ALICE@example.com")

    assert response.status_code == 200
    assert response.json()["access_token"]


async def test_login_upgrades_outdated_password_hash(
    login_user,
    create_user,
    get_user_by_email,
    monkeypatch,
):
    await create_user(email="alice@example.com")

    from services import auth_credentials

    monkeypatch.setattr(auth_credentials, "password_needs_rehash", lambda _: True)
    monkeypatch.setattr(
        auth_credentials,
        "hash_password",
        lambda _: "upgraded-password-hash",
    )

    response = await login_user(email="alice@example.com")
    user = await get_user_by_email("alice@example.com")

    assert response.status_code == 200
    assert user.password_hash == "upgraded-password-hash"


async def test_login_persists_refresh_token_hash(
    register_user,
    login_user,
    get_refresh_token_by_hash,
):
    await register_user()

    response = await login_user(email="ALICE@example.com")

    assert response.status_code == 200

    refresh_token = response.json()["refresh_token"]
    persisted_token = await get_persisted_refresh_token(
        get_refresh_token_by_hash,
        refresh_token,
    )

    assert persisted_token is not None
    assert persisted_token.token_hash != refresh_token


async def test_login_failures_use_generic_error(register_user, login_user, create_user):
    await register_user(email="alice@example.com")
    await create_user(
        email="disabled@example.com",
        status=AccountStatus.DISABLED,
    )

    wrong_password_response = await login_user(
        email="alice@example.com",
        password="WrongPassword123!",
    )
    unknown_email_response = await login_user(email="missing@example.com")
    wrong_password_on_disabled_response = await login_user(
        email="disabled@example.com",
        password="WrongPassword123!",
    )

    assert_invalid_credentials(wrong_password_response)
    assert_invalid_credentials(unknown_email_response)
    assert_invalid_credentials(wrong_password_on_disabled_response)


async def test_login_with_correct_password_reports_disabled_account(
    login_user,
    create_user,
):
    await create_user(
        email="disabled@example.com",
        status=AccountStatus.DISABLED,
    )

    response = await login_user(email="disabled@example.com")

    assert_account_disabled(response)


async def test_unknown_email_still_verifies_a_password_hash(
    login_user,
    monkeypatch,
):
    from services import auth_credentials

    verification_calls = []

    def record_verification(password, password_hash):
        verification_calls.append((password, password_hash))
        return False

    monkeypatch.setattr(auth_credentials, "verify_password", record_verification)

    response = await login_user(email="missing@example.com")

    assert_invalid_credentials(response)
    assert verification_calls == [
        ("Password123!", auth_credentials.DUMMY_PASSWORD_HASH),
    ]


async def test_me_requires_bearer_token(client):
    response = await client.get("/api/auth/me")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_authorization_header"


async def test_me_returns_current_user(client, register_user):
    register_response = await register_user()
    access_token = register_response.json()["access_token"]

    response = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["email"] == "alice@example.com"
    assert response.json()["role"] == UserRole.STUDENT.value
    assert response.json()["status"] == AccountStatus.ACTIVE.value
    assert response.json()["password_changed_at"]
    assert response.json()["email_notifications_enabled"] is True
    assert response.json()["regrade_alerts_enabled"] is True
    assert response.json()["batch_job_complete_enabled"] is True


async def test_me_updates_notification_preferences(client, register_user):
    register_response = await register_user()
    access_token = register_response.json()["access_token"]

    response = await client.patch(
        "/api/auth/me/preferences",
        headers={"Authorization": f"Bearer {access_token}"},
        json={
            "email_notifications_enabled": False,
            "regrade_alerts_enabled": True,
            "batch_job_complete_enabled": False,
        },
    )

    assert response.status_code == 200
    assert response.json()["email_notifications_enabled"] is False
    assert response.json()["regrade_alerts_enabled"] is True
    assert response.json()["batch_job_complete_enabled"] is False

    current_user = await client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert current_user.status_code == 200
    assert current_user.json()["email_notifications_enabled"] is False
    assert current_user.json()["batch_job_complete_enabled"] is False
