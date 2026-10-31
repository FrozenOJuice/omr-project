from collections import defaultdict
from collections import deque
from dataclasses import dataclass
from threading import Lock
import time

from fastapi import Request

from errors.exceptions import RateLimitError


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    """Single-process limiter; use Redis or another shared store in production."""

    def __init__(self):
        self._hits = defaultdict(deque)
        self._lock = Lock()

    def hit(self, key: str, rule: RateLimitRule) -> bool:
        now = time.monotonic()
        window_start = now - rule.window_seconds

        with self._lock:
            hits = self._hits[key]

            while hits and hits[0] <= window_start:
                hits.popleft()

            if len(hits) >= rule.limit:
                return False

            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def clear_key(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


_limiter = InMemoryRateLimiter()

_AUTH_IP_RULES = {
    "register": RateLimitRule(limit=5, window_seconds=10 * 60),
    "login": RateLimitRule(limit=20, window_seconds=5 * 60),
    "refresh": RateLimitRule(limit=60, window_seconds=5 * 60),
    "password_reset_request": RateLimitRule(limit=10, window_seconds=15 * 60),
    "password_reset_confirm": RateLimitRule(limit=20, window_seconds=15 * 60),
}
_LOGIN_EMAIL_RULE = RateLimitRule(limit=5, window_seconds=5 * 60)
_PASSWORD_RESET_EMAIL_RULE = RateLimitRule(limit=3, window_seconds=60 * 60)
_AUTH_EMAIL_RULES = {
    "login": _LOGIN_EMAIL_RULE,
    "password_reset_request": _PASSWORD_RESET_EMAIL_RULE,
}


def enforce_auth_rate_limit(
    request: Request,
    action: str,
    email: str | None = None,
) -> None:
    ip_address = _client_ip(request)
    ip_rule = _AUTH_IP_RULES[action]

    if not _limiter.hit(f"auth:{action}:ip:{ip_address}", ip_rule):
        raise RateLimitError()

    email_rule = _AUTH_EMAIL_RULES.get(action)

    if email and email_rule:
        normalized_email = email.strip().lower()

        if not _limiter.hit(
            f"auth:{action}:email:{normalized_email}",
            email_rule,
        ):
            raise RateLimitError()


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def reset_auth_rate_limiter() -> None:
    _limiter.reset()


def clear_login_rate_limit(email: str) -> None:
    normalized_email = email.strip().lower()
    _limiter.clear_key(f"auth:login:email:{normalized_email}")
