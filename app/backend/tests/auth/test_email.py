from datetime import datetime, timezone

import pytest

from core.tokens import hash_token
from integrations.resend import ResendError
from services import email_service
from services.email_service import EmailDeliveryError
from services import auth_passwords


@pytest.mark.asyncio
async def test_password_reset_email_builds_resend_payload(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    monkeypatch.setattr(
        email_service.settings,
        "frontend_password_reset_url",
        "https://example.com/reset-password",
    )
    monkeypatch.setattr(
        email_service.settings,
        "password_reset_expire_seconds",
        1800,
    )
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append((payload, idempotency_key))

    monkeypatch.setattr(email_service, "send_email", capture)
    token = "password-reset-token"

    await email_service.send_password_reset_email("alice@example.com", token)

    payload, idempotency_key = calls[0]
    expected_url = f"https://example.com/reset-password?token={token}"

    assert payload["from"] == "OMR System <no-reply@mail.example.com>"
    assert payload["to"] == ["alice@example.com"]
    assert expected_url in payload["text"]
    assert expected_url in payload["html"]
    assert "30 minutes" in payload["text"]
    assert idempotency_key == f"password-reset/{hash_token(token)}"


@pytest.mark.asyncio
async def test_course_invitation_email_builds_resend_payload(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append((payload, idempotency_key))

    monkeypatch.setattr(email_service, "send_email", capture)
    token = "roster-entry:invite-link"
    expires_at = datetime(2026, 8, 3, 19, 30, tzinfo=timezone.utc)

    await email_service.send_course_invitation_email(
        "student@example.com",
        course_name="COSC 499 - Capstone",
        inviter_name="Test Professor",
        join_url="https://omr.example.com/join/abc123",
        expires_at=expires_at,
        idempotency_token=token,
    )

    payload, idempotency_key = calls[0]
    assert payload["to"] == ["student@example.com"]
    assert "COSC 499 - Capstone" in payload["subject"]
    assert "https://omr.example.com/join/abc123" in payload["text"]
    assert "August 03, 2026 at 19:30 UTC" in payload["text"]
    assert "August 03, 2026 at 19:30 UTC" in payload["html"]
    assert idempotency_key == f"course-invitation/{hash_token(token)}"


@pytest.mark.asyncio
async def test_notification_email_builds_resend_payload(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    monkeypatch.setattr(email_service.settings, "frontend_origin", "https://omr.example.com")
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append((payload, idempotency_key))

    monkeypatch.setattr(email_service, "send_email", capture)
    await email_service.send_notification_email(
        "student@example.com",
        notification_id="notification-1",
        notification_type="grade_ready",
        title="Your exam has been graded",
        body="Midterm",
        link_path="/courses",
        link_query="courseId=course-1&examId=exam-1",
    )

    payload, idempotency_key = calls[0]
    assert payload["to"] == ["student@example.com"]
    assert payload["subject"] == "OMR System: Your exam has been graded"
    assert "https://omr.example.com/courses?courseId=course-1&amp;examId=exam-1" in payload["html"]
    assert payload["tags"] == [
        {"name": "email_type", "value": "notification"},
        {"name": "notification_type", "value": "grade_ready"},
    ]
    assert idempotency_key == "notification/notification-1"


@pytest.mark.asyncio
async def test_account_created_email_builds_resend_payload(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    monkeypatch.setattr(
        email_service.settings,
        "frontend_password_reset_url",
        "https://example.com/reset-password",
    )
    monkeypatch.setattr(
        email_service.settings,
        "account_activation_expire_seconds",
        259200,
    )
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append((payload, idempotency_key))

    monkeypatch.setattr(email_service, "send_email", capture)
    token = "account-activation-token"

    await email_service.send_account_created_email(
        "student@example.com",
        full_name="New Student",
        role="student",
        token=token,
    )

    payload, idempotency_key = calls[0]
    expected_url = f"https://example.com/reset-password?token={token}"

    assert payload["to"] == ["student@example.com"]
    assert expected_url in payload["text"]
    assert expected_url in payload["html"]
    assert "72 hours" in payload["text"]
    assert idempotency_key == f"account-created/{hash_token(token)}"


@pytest.mark.asyncio
async def test_account_created_email_escapes_recipient_name(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    monkeypatch.setattr(
        email_service.settings,
        "frontend_password_reset_url",
        "https://example.com/reset-password",
    )
    calls = []

    async def capture(payload: dict, idempotency_key: str) -> None:
        calls.append(payload)

    monkeypatch.setattr(email_service, "send_email", capture)

    await email_service.send_account_created_email(
        "student@example.com",
        full_name='<script>alert("xss")</script>',
        role="student",
        token="token",
    )

    assert "<script>" not in calls[0]["html"]
    assert "&lt;script&gt;" in calls[0]["html"]


@pytest.mark.asyncio
async def test_account_created_email_requires_configuration(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_from", None)

    with pytest.raises(EmailDeliveryError):
        await email_service.send_account_created_email(
            "student@example.com",
            full_name="New Student",
            role="student",
            token="token",
        )


@pytest.mark.asyncio
async def test_background_account_created_failure_does_not_escape(monkeypatch):
    async def fail(email: str, **kwargs) -> None:
        raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(auth_passwords, "send_account_created_email", fail)

    await auth_passwords.deliver_account_created_email(
        "student@example.com",
        "token",
        "New Student",
        "student",
    )


@pytest.mark.asyncio
async def test_password_reset_email_wraps_resend_failure(monkeypatch):
    monkeypatch.setattr(
        email_service.settings,
        "email_from",
        "OMR System <no-reply@mail.example.com>",
    )
    monkeypatch.setattr(
        email_service.settings,
        "frontend_password_reset_url",
        "https://example.com/reset-password",
    )

    async def fail(payload: dict, idempotency_key: str) -> None:
        raise ResendError("delivery failed")

    monkeypatch.setattr(email_service, "send_email", fail)

    with pytest.raises(EmailDeliveryError):
        await email_service.send_password_reset_email(
            "alice@example.com",
            "password-reset-token",
        )


@pytest.mark.asyncio
async def test_password_reset_email_requires_configuration(monkeypatch):
    monkeypatch.setattr(email_service.settings, "email_from", None)

    with pytest.raises(EmailDeliveryError):
        await email_service.send_password_reset_email(
            "alice@example.com",
            "password-reset-token",
        )


@pytest.mark.asyncio
async def test_background_email_failure_does_not_escape(monkeypatch):
    async def fail(email: str, token: str) -> None:
        raise EmailDeliveryError("delivery failed")

    monkeypatch.setattr(auth_passwords, "send_password_reset_email", fail)

    await auth_passwords.deliver_password_reset_email(
        "alice@example.com",
        "password-reset-token",
    )
