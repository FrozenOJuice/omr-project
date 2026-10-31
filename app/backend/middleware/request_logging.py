import logging
import time

from fastapi import Request

from middleware.request_id import get_or_create_request_id

logger = logging.getLogger(__name__)


async def log_request(request: Request, call_next):
    request_id = get_or_create_request_id(request)
    start_time = time.perf_counter()

    logger.info(
        "event=request_started method=%s path=%s request_id=%s",
        request.method,
        request.url.path,
        request_id,
    )

    try:
        response = await call_next(request)
    except Exception:
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.warning(
            "event=request_failed method=%s path=%s duration_ms=%.2f request_id=%s",
            request.method,
            request.url.path,
            duration_ms,
            request_id,
        )
        raise

    duration_ms = (time.perf_counter() - start_time) * 1000
    logger.info(
        "event=request_completed method=%s path=%s status_code=%s duration_ms=%.2f request_id=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
    )

    return response
