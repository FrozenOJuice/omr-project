import uuid

import pytest

from models.user import AccountStatus
from models.user import UserRole
from services import auth_passwords
from services import email_service
from services.email_service import EmailDeliveryError

pytestmark = pytest.mark.db


async def test_admin_creates_user(client, admin_headers, get_user_by_email):
    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "Professor",
            "last_name": "Example",
            "email": "PROFESSOR@example.com",
            "password": "Password123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )
    user = await get_user_by_email("professor@example.com")

    assert response.status_code == 201
    assert response.json()["email"] == "professor@example.com"
    assert response.json()["role"] == UserRole.PROFESSOR.value
    assert user is not None
    assert user.role == UserRole.PROFESSOR.value


async def test_admin_create_rejects_duplicate_email(
    client,
    admin_headers,
    create_user,
):
    await create_user(email="duplicate@example.com")

    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "Duplicate",
            "last_name": "User",
            "email": "DUPLICATE@example.com",
            "password": "Password123!",
            "role": UserRole.STUDENT.value,
            "status": AccountStatus.ACTIVE.value,
            "student_number": "10000001",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_exists"


async def test_admin_create_student_without_student_number_rejected(
    client,
    admin_headers,
):
    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "New",
            "last_name": "Student",
            "email": "new.student@example.com",
            "password": "Password123!",
            "role": UserRole.STUDENT.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )

    assert response.status_code == 422


async def test_get_user_returns_account_for_admin(
    client,
    admin_headers,
    create_user,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)

    response = await client.get(
        f"/api/admin/users/{user.id}",
        headers=await admin_headers(),
    )

    assert response.status_code == 200
    assert response.json()["id"] == str(user.id)
    assert response.json()["email"] == "student@example.com"
    assert response.json()["role"] == UserRole.STUDENT.value
    assert response.json()["status"] == AccountStatus.ACTIVE.value


async def test_get_user_returns_not_found_for_missing_user(client, admin_headers):
    response = await client.get(
        f"/api/admin/users/{uuid.uuid4()}",
        headers=await admin_headers(),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "user_not_found"


async def test_admin_updates_user_account(
    client,
    admin_headers,
    create_user,
    get_user_by_email,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)

    response = await client.patch(
        f"/api/admin/users/{user.id}",
        headers=await admin_headers(),
        json={
            "first_name": "Updated",
            "last_name": "Student",
            "email": "UPDATED@example.com",
        },
    )
    updated_user = await get_user_by_email("updated@example.com")

    assert response.status_code == 200
    assert response.json()["first_name"] == "Updated"
    assert response.json()["last_name"] == "Student"
    assert response.json()["email"] == "updated@example.com"
    assert updated_user is not None
    assert updated_user.first_name == "Updated"
    assert updated_user.last_name == "Student"


async def test_admin_update_rejects_duplicate_email(
    client,
    admin_headers,
    create_user,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)
    await create_user(email="existing@example.com", role=UserRole.STUDENT)

    response = await client.patch(
        f"/api/admin/users/{user.id}",
        headers=await admin_headers(),
        json={"email": "EXISTING@example.com"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "user_exists"


async def test_admin_update_rejects_empty_payload(
    client,
    admin_headers,
    create_user,
):
    user = await create_user(email="student@example.com", role=UserRole.STUDENT)

    response = await client.patch(
        f"/api/admin/users/{user.id}",
        headers=await admin_headers(),
        json={},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "no_user_updates"


async def test_admin_created_account_receives_activation_email(
    client,
    admin_headers,
    monkeypatch,
):
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append((payload, idempotency_key))

    monkeypatch.setattr(email_service, "send_email", capture)
    password = "Password123!"

    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "New",
            "last_name": "Professor",
            "email": "new.professor@example.com",
            "password": password,
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )

    assert response.status_code == 201
    assert len(calls) == 1

    payload, idempotency_key = calls[0]
    assert payload["to"] == ["new.professor@example.com"]
    assert payload["subject"] == "Your OMR account is ready"
    assert payload["tags"] == [{"name": "email_type", "value": "account_created"}]
    assert "New Professor" in payload["text"]
    assert idempotency_key.startswith("account-created/")

    # The credential the admin typed must never travel by email.
    assert password not in payload["text"]
    assert password not in payload["html"]

    # 72h default, so an overnight recipient isn't locked out.
    assert "72 hours" in payload["text"]


async def test_activation_link_lets_new_account_set_its_own_password(
    client,
    admin_headers,
    login_user,
    monkeypatch,
):
    tokens_seen = []

    async def capture(
        email: str,
        *,
        full_name: str,
        role: str,
        token: str,
    ) -> None:
        tokens_seen.append(token)

    monkeypatch.setattr(auth_passwords, "send_account_created_email", capture)

    created = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "Activated",
            "last_name": "Student",
            "email": "activated.student@example.com",
            "password": "AdminChosen123!",
            "role": UserRole.STUDENT.value,
            "status": AccountStatus.ACTIVE.value,
            "student_number": "10000009",
        },
    )

    assert created.status_code == 201
    assert len(tokens_seen) == 1

    confirmed = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": tokens_seen[0], "new_password": "SelfChosen456!"},
    )

    assert confirmed.status_code == 204

    login = await login_user(
        email="activated.student@example.com",
        password="SelfChosen456!",
    )

    assert login.status_code == 200


async def test_failed_duplicate_create_sends_no_email(
    client,
    admin_headers,
    create_user,
    monkeypatch,
):
    await create_user(email="taken@example.com")
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append(payload)

    monkeypatch.setattr(email_service, "send_email", capture)

    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "Duplicate",
            "last_name": "User",
            "email": "taken@example.com",
            "password": "Password123!",
            "role": UserRole.STUDENT.value,
            "status": AccountStatus.ACTIVE.value,
            "student_number": "10000010",
        },
    )

    assert response.status_code == 409
    assert calls == []


async def test_account_created_email_failure_still_returns_created(
    client,
    admin_headers,
    get_user_by_email,
    monkeypatch,
):
    async def fail(*args, **kwargs) -> None:
        raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(auth_passwords, "send_account_created_email", fail)

    response = await client.post(
        "/api/admin/users",
        headers=await admin_headers(),
        json={
            "first_name": "Undelivered",
            "last_name": "Professor",
            "email": "undelivered@example.com",
            "password": "Password123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )

    # A mail outage must not stop an admin from provisioning accounts.
    assert response.status_code == 201
    assert await get_user_by_email("undelivered@example.com") is not None


async def test_activating_disabled_account_sends_setup_email(
    client,
    admin_headers,
    login_user,
    monkeypatch,
):
    tokens_seen = []

    async def capture(email, *, full_name, role, token):
        tokens_seen.append(token)

    monkeypatch.setattr(auth_passwords, "send_account_created_email", capture)
    headers = await admin_headers()

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "first_name": "Later",
            "last_name": "Active",
            "email": "later.active@example.com",
            "password": "AdminChosen123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.DISABLED.value,
        },
    )
    assert created.status_code == 201
    user_id = created.json()["id"]
    # Created disabled: no setup email yet.
    assert tokens_seen == []

    activated = await client.patch(
        f"/api/admin/users/{user_id}/status",
        headers=headers,
        json={"status": AccountStatus.ACTIVE.value},
    )
    assert activated.status_code == 200

    # Activation triggers the setup email, and the emailed link works.
    assert len(tokens_seen) == 1
    confirmed = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": tokens_seen[0], "new_password": "SelfChosen456!"},
    )
    assert confirmed.status_code == 204
    login = await login_user(
        email="later.active@example.com", password="SelfChosen456!"
    )
    assert login.status_code == 200


async def test_disabling_account_sends_no_setup_email(
    client,
    admin_headers,
    monkeypatch,
):
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append(payload)

    monkeypatch.setattr(email_service, "send_email", capture)
    headers = await admin_headers()

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "first_name": "Active",
            "last_name": "First",
            "email": "active.first@example.com",
            "password": "Password123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )
    user_id = created.json()["id"]
    calls.clear()  # ignore the create email

    disabled = await client.patch(
        f"/api/admin/users/{user_id}/status",
        headers=headers,
        json={"status": AccountStatus.DISABLED.value},
    )
    assert disabled.status_code == 200
    assert calls == []


async def test_resend_setup_email_queues_a_working_link(
    client,
    admin_headers,
    monkeypatch,
):
    tokens_seen = []

    async def capture(email, *, full_name, role, token):
        tokens_seen.append(token)

    monkeypatch.setattr(auth_passwords, "send_account_created_email", capture)
    headers = await admin_headers()

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "first_name": "Resend",
            "last_name": "Me",
            "email": "resend.me@example.com",
            "password": "Password123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.ACTIVE.value,
        },
    )
    user_id = created.json()["id"]
    assert len(tokens_seen) == 1  # the create email
    tokens_seen.clear()

    resend = await client.post(
        f"/api/admin/users/{user_id}/resend-setup-email",
        headers=headers,
    )
    assert resend.status_code == 202
    assert len(tokens_seen) == 1

    # The re-issued link works (and the original was revoked in the process).
    confirmed = await client.post(
        "/api/auth/password-reset/confirm",
        json={"token": tokens_seen[0], "new_password": "ResentChosen789!"},
    )
    assert confirmed.status_code == 204


async def test_resend_setup_email_rejects_disabled_account(
    client,
    admin_headers,
    monkeypatch,
):
    monkeypatch.setattr(auth_passwords, "send_account_created_email", _noop_email)
    headers = await admin_headers()

    created = await client.post(
        "/api/admin/users",
        headers=headers,
        json={
            "first_name": "Still",
            "last_name": "Disabled",
            "email": "still.disabled@example.com",
            "password": "Password123!",
            "role": UserRole.PROFESSOR.value,
            "status": AccountStatus.DISABLED.value,
        },
    )
    user_id = created.json()["id"]

    resend = await client.post(
        f"/api/admin/users/{user_id}/resend-setup-email",
        headers=headers,
    )
    assert resend.status_code == 400
    assert resend.json()["error"]["code"] == "account_not_active"


async def test_resend_setup_email_missing_user_returns_404(client, admin_headers):
    resend = await client.post(
        f"/api/admin/users/{uuid.uuid4()}/resend-setup-email",
        headers=await admin_headers(),
    )
    assert resend.status_code == 404


async def _noop_email(email, *, full_name, role, token):
    return None
