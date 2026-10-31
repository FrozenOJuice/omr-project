import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from errors.exceptions import AppError

logger = logging.getLogger(__name__)


def _get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    request_id: str | None,
    details=None,
) -> JSONResponse:
    error = {
        "code": code,
        "message": message,
        "request_id": request_id,
    }

    if details is not None:
        error["details"] = details

    return JSONResponse(status_code=status_code, content={"error": error})


def _validation_errors(errors: list[dict]) -> list[dict]:
    sanitized_errors = []

    for error in errors:
        sanitized_error = dict(error)
        location = sanitized_error.get("loc", [])

        if any(
            isinstance(part, str)
            and any(
                secret_name in part.lower()
                for secret_name in ("password", "token", "secret")
            )
            for part in location
        ):
            sanitized_error.pop("input", None)

        sanitized_errors.append(sanitized_error)

    return sanitized_errors


async def app_error_handler(request: Request, exc: AppError):
    return _error_response(
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        request_id=_get_request_id(request),
        details=exc.details,
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    code_by_status = {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        429: "rate_limited",
    }

    return _error_response(
        status_code=exc.status_code,
        code=code_by_status.get(exc.status_code, "http_error"),
        message=str(exc.detail),
        request_id=_get_request_id(request),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error_response(
        status_code=422,
        code="validation_error",
        message="Invalid request",
        request_id=_get_request_id(request),
        details=jsonable_encoder(_validation_errors(exc.errors())),
    )


async def global_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", None)

    logger.exception(
        "event=unhandled_exception request_id=%s error_type=%s",
        request_id,
        type(exc).__name__,
    )

    return _error_response(
        status_code=500,
        code="internal_server_error",
        message="Internal server error",
        request_id=request_id,
    )
