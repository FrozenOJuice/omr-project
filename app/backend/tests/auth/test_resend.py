import httpx
import pytest

from integrations import resend
from integrations.resend import ResendError


@pytest.mark.asyncio
async def test_resend_requires_api_key(monkeypatch):
    monkeypatch.setattr(resend.settings, "resend_api_key", None)

    with pytest.raises(ResendError):
        await resend.send_email({}, "test-idempotency-key")


@pytest.mark.asyncio
async def test_console_mode_logs_email_and_skips_resend(monkeypatch, caplog):
    monkeypatch.setattr(resend.settings, "email_console_mode", True)
    monkeypatch.setattr(resend.settings, "resend_api_key", None)

    class ExplodingClient:
        def __init__(self, *args, **kwargs):
            raise AssertionError("console mode must not call the Resend API")

    monkeypatch.setattr(resend.httpx, "AsyncClient", ExplodingClient)

    payload = {
        "to": ["student@example.com"],
        "subject": "Your OMR account is ready",
        "text": "Set your password: https://example.com/reset-password?token=abc123",
    }

    with caplog.at_level("INFO", logger="integrations.resend"):
        # Must not raise and must not construct an httpx client.
        await resend.send_email(payload, "account-created/hash")

    logged = caplog.text
    assert "DEV EMAIL" in logged
    assert "student@example.com" in logged
    # The link is logged so a developer can copy it and test the flow.
    assert "https://example.com/reset-password?token=abc123" in logged


@pytest.mark.asyncio
async def test_resend_sends_expected_request(monkeypatch):
    monkeypatch.setattr(resend.settings, "resend_api_key", "test-api-key")
    calls = []

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            assert timeout == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, headers: dict, json: dict):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    monkeypatch.setattr(resend.httpx, "AsyncClient", FakeAsyncClient)
    payload = {"to": ["alice@example.com"], "subject": "Reset"}

    await resend.send_email(payload, "password-reset/token-hash")

    assert calls == [
        {
            "url": resend.RESEND_EMAILS_URL,
            "headers": {
                "Authorization": "Bearer test-api-key",
                "Content-Type": "application/json",
                "Idempotency-Key": "password-reset/token-hash",
            },
            "json": payload,
        }
    ]


@pytest.mark.asyncio
async def test_resend_wraps_http_error(monkeypatch):
    monkeypatch.setattr(resend.settings, "resend_api_key", "test-api-key")

    class FakeResponse:
        status_code = 500

        def raise_for_status(self) -> None:
            request = httpx.Request("POST", resend.RESEND_EMAILS_URL)
            response = httpx.Response(500, request=request)
            raise httpx.HTTPStatusError(
                "Resend failed",
                request=request,
                response=response,
            )

    class FakeAsyncClient:
        def __init__(self, timeout: float):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url: str, headers: dict, json: dict):
            return FakeResponse()

    monkeypatch.setattr(resend.httpx, "AsyncClient", FakeAsyncClient)

    with pytest.raises(ResendError):
        await resend.send_email({}, "test-idempotency-key")
