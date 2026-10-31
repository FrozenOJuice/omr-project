import logging

import httpx

from core.settings import settings

logger = logging.getLogger(__name__)

RESEND_EMAILS_URL = "https://api.resend.com/emails"


class ResendError(Exception):
    pass


def _log_dev_email(payload: dict) -> None:
    """Print an email to the logs instead of sending it.

    Lets developers read and click links (activation, invitations, password
    resets) without a Resend account or any external dependency.
    """
    recipients = ", ".join(payload.get("to", []) or [])
    logger.info(
        "\n%s\n[DEV EMAIL] Console mode — not sent via Resend.\n"
        "To:      %s\n"
        "Subject: %s\n"
        "%s\n"
        "%s\n"
        "%s",
        "=" * 70,
        recipients,
        payload.get("subject", ""),
        "-" * 70,
        payload.get("text", ""),
        "=" * 70,
    )


async def send_email(payload: dict, idempotency_key: str) -> None:
    # Development escape hatch: print the message (with its links) to the logs
    # instead of calling Resend, so email flows can be tested with no external
    # service. Never enable this in production.
    if settings.email_console_mode:
        _log_dev_email(payload)
        return

    if not settings.resend_api_key:
        raise ResendError("Resend API key is not configured")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                RESEND_EMAILS_URL,
                headers={
                    "Authorization": f"Bearer {settings.resend_api_key}",
                    "Content-Type": "application/json",
                    "Idempotency-Key": idempotency_key,
                },
                json=payload,
            )
            response.raise_for_status()
    except httpx.HTTPError as exc:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        logger.error(
            "event=resend_request_failed status_code=%s error_type=%s",
            status_code,
            type(exc).__name__,
        )
        raise ResendError("Resend request failed") from exc
