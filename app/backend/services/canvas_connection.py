import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.settings import settings
from core.token_encryption import TokenCipher, TokenEncryptionError
from errors.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    RateLimitError,
    ServiceUnavailableError,
)
from integrations.canvas_client import (
    CanvasClient,
    CanvasRequestError,
    normalize_canvas_id,
)
from models.canvas_connection import CanvasConnection
from schemas.canvas_schema import CanvasConnectionResponse


MAX_ACCESS_TOKEN_LENGTH = 4096


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def is_configured() -> bool:
    urls = (settings.canvas_public_base_url, settings.canvas_api_base_url)
    parsed = [urlparse(url) for url in urls]
    allowed_schemes = {"http", "https"} if settings.debug else {"https"}
    return bool(settings.canvas_token_encryption_secret) and all(
        url.scheme in allowed_schemes and url.netloc for url in parsed
    )


def settings_url() -> str | None:
    if not is_configured():
        return None
    return urljoin(settings.canvas_public_base_url.rstrip("/") + "/", "profile/settings")


async def get_connection(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> CanvasConnection | None:
    query = select(CanvasConnection).where(CanvasConnection.user_id == user_id)
    if for_update:
        query = query.with_for_update().execution_options(populate_existing=True)
    return await db.scalar(query)


async def connect(
    db: AsyncSession,
    user_id: uuid.UUID,
    access_token: str,
) -> CanvasConnectionResponse:
    token = access_token.strip()
    if not token:
        raise BadRequestError(
            "Enter a Canvas access token",
            code="canvas_access_token_required",
        )
    if len(token) > MAX_ACCESS_TOKEN_LENGTH:
        raise BadRequestError(
            "Canvas access token is too long",
            code="invalid_canvas_access_token",
        )

    try:
        async with asyncio.timeout(settings.canvas_operation_timeout_seconds):
            async with _client() as client:
                profile = await client.get_profile(token)
    except TimeoutError as exc:
        raise ServiceUnavailableError(
            "Canvas took too long to respond",
            code="canvas_operation_timeout",
        ) from exc
    except CanvasRequestError as exc:
        if exc.status_code == 401:
            raise BadRequestError(
                "Canvas rejected this access token",
                code="invalid_canvas_access_token",
            ) from exc
        raise _service_error(exc) from exc

    canvas_user_id = normalize_canvas_id(profile.get("id"))
    if canvas_user_id is None:
        raise ServiceUnavailableError(
            "Canvas returned an invalid profile",
            code="invalid_canvas_profile",
        )

    now = utc_now()
    connection = await get_connection(db, user_id)
    if connection is None:
        connection = CanvasConnection(user_id=user_id)
        db.add(connection)
    connection.canvas_user_id = canvas_user_id
    connection.canvas_user_name = _optional_string(profile.get("name"))
    connection.canvas_user_login_id = _optional_string(profile.get("login_id"))
    connection.access_token_encrypted = _cipher().encrypt(token)
    connection.connected_at = now
    connection.last_verified_at = now
    await db.commit()
    return _connection_response(connection)


async def get_connection_status(
    db: AsyncSession, user_id: uuid.UUID
) -> CanvasConnectionResponse:
    connection = await get_connection(db, user_id)
    return _connection_response(connection)


async def disconnect(db: AsyncSession, user_id: uuid.UUID) -> None:
    connection = await get_connection(db, user_id)
    if connection is None:
        return
    await db.delete(connection)
    await db.commit()


async def call_canvas(
    db: AsyncSession,
    user_id: uuid.UUID,
    operation: Callable[[CanvasClient, str], Awaitable[Any]],
) -> Any:
    try:
        async with asyncio.timeout(settings.canvas_operation_timeout_seconds):
            async with _connection_session(db) as connection_db:
                connection = await get_connection(connection_db, user_id)
                token = _access_token(connection)

                async with _client() as client:
                    try:
                        result = await operation(client, token)
                    except CanvasRequestError as exc:
                        if exc.status_code != 401:
                            raise _service_error(exc) from exc

                        replacement = await _replacement_after_rejection(
                            connection_db, user_id, token
                        )
                        if replacement is None:
                            raise _service_error(exc) from exc
                        try:
                            result = await operation(client, replacement)
                        except CanvasRequestError as retry_error:
                            if retry_error.status_code == 401:
                                await _replacement_after_rejection(
                                    connection_db, user_id, replacement
                                )
                            raise _service_error(retry_error) from retry_error

                connection = await get_connection(connection_db, user_id)
                if connection is not None and connection.access_token_encrypted:
                    connection.last_verified_at = utc_now()
                    await connection_db.commit()
                return result
    except TimeoutError as exc:
        raise ServiceUnavailableError(
            "Canvas took too long to respond",
            code="canvas_operation_timeout",
        ) from exc


def _access_token(connection: CanvasConnection | None) -> str:
    if connection is None or connection.access_token_encrypted is None:
        raise ConflictError(
            "Connect Canvas before using this feature",
            code="canvas_not_connected",
        )
    try:
        return _cipher().decrypt(connection.access_token_encrypted)
    except TokenEncryptionError as exc:
        raise ServiceUnavailableError(
            "Reconnect Canvas to continue",
            code="canvas_reconnect_required",
        ) from exc


async def _replacement_after_rejection(
    db: AsyncSession,
    user_id: uuid.UUID,
    rejected_token: str,
) -> str | None:
    connection = await get_connection(db, user_id, for_update=True)
    if connection is None or connection.access_token_encrypted is None:
        return None
    try:
        current_token = _cipher().decrypt(connection.access_token_encrypted)
    except TokenEncryptionError:
        current_token = rejected_token
    if current_token != rejected_token:
        await db.commit()
        return current_token
    await db.delete(connection)
    await db.commit()
    return None


def _connection_response(
    connection: CanvasConnection | None,
) -> CanvasConnectionResponse:
    if connection is None or connection.access_token_encrypted is None:
        return CanvasConnectionResponse(connected=False)
    return CanvasConnectionResponse(
        connected=True,
        user_name=connection.canvas_user_name,
        login_id=connection.canvas_user_login_id,
        connected_at=connection.connected_at,
        last_verified_at=connection.last_verified_at,
    )


@asynccontextmanager
async def _connection_session(
    db: AsyncSession,
) -> AsyncIterator[AsyncSession]:
    if db.bind is None:
        raise RuntimeError("Canvas connection persistence requires a bound session")
    session_factory = async_sessionmaker(bind=db.bind, expire_on_commit=False)
    async with session_factory() as connection_db:
        yield connection_db


def _client() -> CanvasClient:
    if not is_configured():
        raise ServiceUnavailableError(
            "Canvas integration is not configured",
            code="canvas_not_configured",
        )
    return CanvasClient(
        api_base_url=settings.canvas_api_base_url,
        public_base_url=settings.canvas_public_base_url,
        timeout=settings.canvas_http_timeout_seconds,
    )


def _cipher() -> TokenCipher:
    secret = settings.canvas_token_encryption_secret
    if not secret:
        raise ServiceUnavailableError(
            "Canvas integration is not configured",
            code="canvas_not_configured",
        )
    return TokenCipher(secret)


def _service_error(error: CanvasRequestError):
    if error.status_code == 401:
        return ServiceUnavailableError(
            "Canvas rejected the saved access token. Connect Canvas again.",
            code="canvas_reconnect_required",
        )
    if error.status_code == 403:
        return ForbiddenError(
            "Canvas denied access to this resource.",
            code="canvas_permission_denied",
        )
    if error.status_code == 429:
        return RateLimitError(
            "Canvas is receiving too many requests. Please try again shortly.",
            code="canvas_rate_limited",
        )
    return ServiceUnavailableError(
        "Canvas is temporarily unavailable",
        code="canvas_unavailable",
    )


def _optional_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
