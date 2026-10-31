from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urljoin

from sqlalchemy.ext.asyncio import AsyncSession

from core.datetime_utils import is_expired
from core.settings import settings
from models.course import Course
from models.course_roster_entry import CourseRosterEntry
from models.user import User
from repositories import course_roster_entries
from services.canvas_batch import bounded_map
from services.email_service import EmailDeliveryError
from services.email_service import send_course_invitation_email


@dataclass(frozen=True)
class InviteDelivery:
    sent: int
    failed: int


def join_url_for(course: Course) -> str:
    """Absolute join link for a course invite.

    Requires ``FRONTEND_ORIGIN``. A missing origin used to silently fall back
    to ``http://localhost:4200``, which in production mails students a link
    pointing at their own machine. Failing here instead surfaces as a delivery
    failure (the entry stays pending and retriable) rather than a dead link.
    """
    if not settings.frontend_origin:
        raise EmailDeliveryError(
            "Invitation email is not configured: FRONTEND_ORIGIN is unset"
        )
    if is_expired(course.invite_link_expires_at):
        raise EmailDeliveryError(
            "Course invite link has expired; regenerate it before sending invitations"
        )
    return urljoin(
        settings.frontend_origin.rstrip("/") + "/",
        f"/join/{course.invite_link}",
    )


def pending_invites(entries: list[CourseRosterEntry]) -> list[CourseRosterEntry]:
    """Entries that still need an invitation email.

    Entries already linked to an account (``user_id``) are enrolled and don't
    need a join link, and ``invited_at`` keeps a repeat roster upload or sync
    from emailing the same student twice.
    """
    return [entry for entry in entries if not entry.user_id and not entry.invited_at]


async def deliver_invitations(
    db: AsyncSession,
    inviter: User,
    course: Course,
    entries: list[CourseRosterEntry],
) -> InviteDelivery:
    """Email a join link to each pending roster entry and record who got one.

    Callers must have committed the roster rows first: delivery is best effort,
    so a bounced email marks the entry as still pending rather than undoing the
    enrolment that produced it.
    """
    pending = pending_invites(entries)
    if not pending:
        return InviteDelivery(sent=0, failed=0)

    async def deliver(entry: CourseRosterEntry) -> None:
        # Built per delivery so a missing FRONTEND_ORIGIN is captured by
        # bounded_map as a per-entry failure, exactly like a missing
        # EMAIL_FROM, instead of aborting the whole batch.
        join_url = join_url_for(course)
        await send_course_invitation_email(
            entry.email,
            course_name=course.name,
            inviter_name=inviter.full_name,
            join_url=join_url,
            expires_at=course.invite_link_expires_at,
            idempotency_token=(
                f"{entry.id}:{course.invite_link}:"
                f"{course_roster_entries.normalize_email(entry.email)}"
            ),
        )

    results = await bounded_map(
        pending,
        deliver,
        concurrency=settings.canvas_batch_concurrency,
        timeout=settings.canvas_operation_timeout_seconds,
    )

    invited_at = datetime.now(timezone.utc)
    sent = failed = 0
    for entry, result in zip(pending, results, strict=True):
        if result.error is None:
            entry.invited_at = invited_at
            sent += 1
        else:
            failed += 1

    await db.commit()
    return InviteDelivery(sent=sent, failed=failed)
