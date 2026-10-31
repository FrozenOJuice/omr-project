from datetime import datetime
from datetime import timezone


def is_expired(expires_at: datetime, now: datetime | None = None) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    return expires_at <= (now or datetime.now(timezone.utc))
