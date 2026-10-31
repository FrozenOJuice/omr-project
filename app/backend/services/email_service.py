from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode

from core.settings import settings
from core.tokens import hash_token
from integrations.resend import ResendError
from integrations.resend import send_email


class EmailDeliveryError(Exception):
    pass


def _format_utc_datetime(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%B %d, %Y at %H:%M UTC")


async def send_password_reset_email(email: str, token: str) -> None:
    if not all(
        (
            settings.email_from,
            settings.frontend_password_reset_url,
        )
    ):
        raise EmailDeliveryError("Password reset email is not configured")

    query = urlencode({"token": token})
    reset_url = f"{settings.frontend_password_reset_url}?{query}"
    safe_reset_url = escape(reset_url, quote=True)
    expiry_minutes = max(1, settings.password_reset_expire_seconds // 60)

    payload = {
        "from": settings.email_from,
        "to": [email],
        "subject": "Reset your password",
        "text": (
            f"Reset your password using this link: {reset_url}\n\n"
            f"This link expires in {expiry_minutes} minutes. "
            "If you did not request this, you can ignore this email."
        ),
        "html": (
            "<p>Use the link below to reset your password.</p>"
            f'<p><a href="{safe_reset_url}">Reset password</a></p>'
            f"<p>This link expires in {expiry_minutes} minutes.</p>"
            "<p>If you did not request this, you can ignore this email.</p>"
        ),
        "tags": [{"name": "email_type", "value": "password_reset"}],
    }

    try:
        await send_email(
            payload,
            idempotency_key=f"password-reset/{hash_token(token)}",
        )
    except ResendError as exc:
        raise EmailDeliveryError("Unable to send password reset email") from exc


async def send_account_created_email(
    email: str,
    *,
    full_name: str,
    role: str,
    token: str,
) -> None:
    """Tell someone an admin made them an account and let them set a password.

    The password the admin typed is deliberately never included: the recipient
    gets a one-time activation link instead, which reuses the password reset
    flow so there is only one place that can set a credential by email.
    """
    if not all(
        (
            settings.email_from,
            settings.frontend_password_reset_url,
        )
    ):
        raise EmailDeliveryError("Account created email is not configured")

    query = urlencode({"token": token})
    activation_url = f"{settings.frontend_password_reset_url}?{query}"
    safe_activation_url = escape(activation_url, quote=True)
    safe_full_name = escape(full_name)
    safe_role = escape(role)
    expiry_hours = max(1, settings.account_activation_expire_seconds // 3600)

    payload = {
        "from": settings.email_from,
        "to": [email],
        "subject": "Your OMR account is ready",
        "text": (
            f"Hi {full_name},\n\n"
            f"An administrator created an OMR {role} account for you using "
            f"this email address.\n\n"
            f"Set your password to get started: {activation_url}\n\n"
            f"This link expires in {expiry_hours} hours. If it expires, use "
            '"Forgot password" on the sign-in page to get a new one.'
        ),
        "html": (
            f"<p>Hi {safe_full_name},</p>"
            f"<p>An administrator created an OMR <strong>{safe_role}</strong> "
            "account for you using this email address.</p>"
            f'<p><a href="{safe_activation_url}">Set your password</a></p>'
            f"<p>This link expires in {expiry_hours} hours. If it expires, use "
            '"Forgot password" on the sign-in page to get a new one.</p>'
        ),
        "tags": [{"name": "email_type", "value": "account_created"}],
    }

    try:
        await send_email(
            payload,
            idempotency_key=f"account-created/{hash_token(token)}",
        )
    except ResendError as exc:
        raise EmailDeliveryError("Unable to send account created email") from exc


async def send_course_invitation_email(
    email: str,
    *,
    course_name: str,
    inviter_name: str,
    join_url: str,
    expires_at: datetime,
    idempotency_token: str,
) -> None:
    if not settings.email_from:
        raise EmailDeliveryError("Course invitation email is not configured")

    safe_course_name = escape(course_name)
    safe_inviter_name = escape(inviter_name)
    safe_join_url = escape(join_url, quote=True)
    formatted_expiry = _format_utc_datetime(expires_at)
    payload = {
        "from": settings.email_from,
        "to": [email],
        "subject": f"You're invited to {course_name} in OMR",
        "text": (
            f"{inviter_name} invited you to {course_name} in OMR.\n\n"
            f"Join the course: {join_url}\n\n"
            f"This link expires on {formatted_expiry}. If it expires, ask "
            "your instructor for a new link.\n\n"
            "Sign in with your existing OMR student account, or create one "
            "using this email address."
        ),
        "html": (
            f"<p>{safe_inviter_name} invited you to "
            f"<strong>{safe_course_name}</strong> in OMR.</p>"
            f'<p><a href="{safe_join_url}">Join course</a></p>'
            f"<p>This link expires on {formatted_expiry}. If it expires, ask "
            "your instructor for a new link.</p>"
            "<p>Sign in with your existing OMR student account, or create one "
            "using this email address.</p>"
        ),
        "tags": [{"name": "email_type", "value": "course_invitation"}],
    }

    try:
        await send_email(
            payload,
            idempotency_key=f"course-invitation/{hash_token(idempotency_token)}",
        )
    except ResendError as exc:
        raise EmailDeliveryError("Unable to send course invitation email") from exc


async def send_notification_email(
    email: str,
    *,
    notification_id: str,
    notification_type: str,
    title: str,
    body: str | None,
    link_path: str | None,
    link_query: str | None,
) -> None:
    """Send an email copy of an in-app notification.

    The notification UUID is the idempotency key, so retrying delivery cannot
    produce duplicate email for the same in-app event.
    """
    if not settings.email_from:
        raise EmailDeliveryError("Notification email is not configured")

    notification_url = _notification_url(link_path, link_query)
    safe_title = escape(title)
    safe_body = escape(body) if body else None
    safe_url = escape(notification_url, quote=True) if notification_url else None
    text_parts = [title]
    if body:
        text_parts.append(body)
    if notification_url:
        text_parts.append(f"View this notification: {notification_url}")

    html_parts = [f"<p><strong>{safe_title}</strong></p>"]
    if safe_body:
        html_parts.append(f"<p>{safe_body}</p>")
    if safe_url:
        html_parts.append(f'<p><a href="{safe_url}">View notification</a></p>')

    payload = {
        "from": settings.email_from,
        "to": [email],
        "subject": f"OMR System: {title}",
        "text": "\n\n".join(text_parts),
        "html": "".join(html_parts),
        "tags": [
            {"name": "email_type", "value": "notification"},
            {"name": "notification_type", "value": notification_type},
        ],
    }

    try:
        await send_email(payload, idempotency_key=f"notification/{notification_id}")
    except ResendError as exc:
        raise EmailDeliveryError("Unable to send notification email") from exc


def _notification_url(link_path: str | None, link_query: str | None) -> str | None:
    if not settings.frontend_origin or not link_path:
        return None

    url = f"{settings.frontend_origin.rstrip('/')}/{link_path.lstrip('/')}"
    return f"{url}?{link_query}" if link_query else url
