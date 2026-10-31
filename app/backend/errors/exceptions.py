from typing import Any


class AppError(Exception):
    status_code = 400
    code = "bad_request"
    message = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: Any = None,
    ):
        self.message = message or self.message
        self.code = code or self.code
        self.details = details


class BadRequestError(AppError):
    status_code = 400
    code = "bad_request"
    message = "Bad request"


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    message = "Unauthorized"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    message = "Forbidden"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    message = "Not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    message = "Conflict"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    message = "Too many requests"


class ServiceUnavailableError(AppError):
    status_code = 502
    code = "service_unavailable"
    message = "An upstream service is unavailable"
