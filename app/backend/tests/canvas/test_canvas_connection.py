import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock
import uuid

import pytest
from sqlalchemy import select

import db.base  # Register the complete SQLAlchemy model graph.
from core.settings import settings
from errors.exceptions import (
    BadRequestError,
    ForbiddenError,
    RateLimitError,
    ServiceUnavailableError,
)
from integrations.canvas_client import CanvasRequestError
from models.canvas_connection import CanvasConnection
from models.user import UserRole
from services import canvas_connection


class ClientContext:
    def __init__(self, client):
        self.client = client

    async def __aenter__(self):
        return self.client

    async def __aexit__(self, *_args):
        return None


def profile(
    user_id: str = "9007199254740993",
    name: str = "Professor Canvas",
    login_id: str = "professor@example.com",
) -> dict[str, str]:
    return {"id": user_id, "name": name, "login_id": login_id}


def test_canvas_configuration_requires_dedicated_encryption_secret(monkeypatch):
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "canvas_public_base_url", "http://localhost:6700")
    monkeypatch.setattr(settings, "canvas_api_base_url", "http://canvas:6700")
    monkeypatch.setattr(settings, "canvas_token_encryption_secret", None)

    assert canvas_connection.is_configured() is False
    with pytest.raises(ServiceUnavailableError) as error:
        canvas_connection._cipher()

    assert error.value.code == "canvas_not_configured"


@pytest.mark.asyncio
async def test_connect_validates_and_encrypts_personal_access_token(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-connect@example.com",
        student_number=None,
    )
    client = AsyncMock()
    client.get_profile.return_value = profile()
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(client)
    )

    response = await canvas_connection.connect(
        db_session, professor.id, "  personal-access-token  "
    )
    connection = await canvas_connection.get_connection(db_session, professor.id)

    assert response.connected is True
    assert response.user_name == "Professor Canvas"
    assert "token" not in response.model_dump()
    assert connection.access_token_encrypted != "personal-access-token"
    assert (
        canvas_connection._cipher().decrypt(connection.access_token_encrypted)
        == "personal-access-token"
    )
    assert connection.canvas_user_id == "9007199254740993"
    assert connection.connected_at is not None
    assert connection.last_verified_at is not None
    client.get_profile.assert_awaited_once_with("personal-access-token")


@pytest.mark.asyncio
async def test_invalid_replacement_preserves_existing_connection(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-replace-invalid@example.com",
        student_number=None,
    )
    connection = CanvasConnection(
        user_id=professor.id,
        canvas_user_id="1",
        access_token_encrypted=canvas_connection._cipher().encrypt("old-token"),
    )
    db_session.add(connection)
    await db_session.commit()
    client = AsyncMock()
    client.get_profile.side_effect = CanvasRequestError("invalid token", 401)
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(client)
    )

    with pytest.raises(BadRequestError) as error:
        await canvas_connection.connect(db_session, professor.id, "bad-token")

    await db_session.refresh(connection)
    assert error.value.code == "invalid_canvas_access_token"
    assert (
        canvas_connection._cipher().decrypt(connection.access_token_encrypted)
        == "old-token"
    )
    assert connection.canvas_user_id == "1"


@pytest.mark.asyncio
async def test_replacing_token_updates_canvas_identity(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-replace@example.com",
        student_number=None,
    )
    connection = CanvasConnection(
        user_id=professor.id,
        canvas_user_id="1",
        canvas_user_name="Old Name",
        access_token_encrypted=canvas_connection._cipher().encrypt("old-token"),
    )
    db_session.add(connection)
    await db_session.commit()
    client = AsyncMock()
    client.get_profile.return_value = profile("2", "New Name", "new@example.com")
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(client)
    )

    response = await canvas_connection.connect(
        db_session, professor.id, "new-token"
    )

    await db_session.refresh(connection)
    assert response.user_name == "New Name"
    assert connection.canvas_user_id == "2"
    assert connection.canvas_user_login_id == "new@example.com"
    assert (
        canvas_connection._cipher().decrypt(connection.access_token_encrypted)
        == "new-token"
    )


@pytest.mark.asyncio
async def test_connect_rejects_empty_token_without_calling_canvas(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-empty@example.com",
        student_number=None,
    )
    client_factory = Mock()
    monkeypatch.setattr(canvas_connection, "_client", client_factory)

    with pytest.raises(BadRequestError) as error:
        await canvas_connection.connect(db_session, professor.id, "   ")

    assert error.value.code == "canvas_access_token_required"
    client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_connect_rejects_invalid_canvas_profile(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-profile@example.com",
        student_number=None,
    )
    client = AsyncMock()
    client.get_profile.return_value = {"id": "not-an-id"}
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(client)
    )

    with pytest.raises(ServiceUnavailableError) as error:
        await canvas_connection.connect(db_session, professor.id, "token")

    assert error.value.code == "invalid_canvas_profile"
    assert await canvas_connection.get_connection(db_session, professor.id) is None


@pytest.mark.asyncio
async def test_call_canvas_uses_saved_token_without_committing_caller(monkeypatch):
    db = AsyncMock()
    connection_db = AsyncMock()
    connection = CanvasConnection(
        user_id=uuid.uuid4(),
        access_token_encrypted=canvas_connection._cipher().encrypt("saved-token"),
    )
    client = AsyncMock()
    operation = AsyncMock(return_value={"ok": True})

    @asynccontextmanager
    async def connection_session(_db):
        yield connection_db

    monkeypatch.setattr(canvas_connection, "_connection_session", connection_session)
    monkeypatch.setattr(
        canvas_connection, "get_connection", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(client)
    )

    result = await canvas_connection.call_canvas(
        db, connection.user_id, operation
    )

    assert result == {"ok": True}
    operation.assert_awaited_once_with(client, "saved-token")
    db.commit.assert_not_awaited()
    connection_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_unauthorized_canvas_call_invalidates_saved_token(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-revoked@example.com",
        student_number=None,
    )
    connection = CanvasConnection(
        user_id=professor.id,
        access_token_encrypted=canvas_connection._cipher().encrypt("revoked-token"),
    )
    db_session.add(connection)
    await db_session.commit()
    monkeypatch.setattr(
        canvas_connection,
        "_client",
        lambda: ClientContext(AsyncMock()),
    )

    with pytest.raises(ServiceUnavailableError) as error:
        await canvas_connection.call_canvas(
            db_session,
            professor.id,
            AsyncMock(side_effect=CanvasRequestError("unauthorized", 401)),
        )

    assert error.value.code == "canvas_reconnect_required"
    assert await canvas_connection.get_connection(db_session, professor.id) is None
    assert (
        await canvas_connection.get_connection_status(db_session, professor.id)
    ).connected is False


@pytest.mark.asyncio
async def test_canvas_call_retries_token_replaced_during_request(monkeypatch):
    connection_db = AsyncMock()
    user_id = uuid.uuid4()
    initial = CanvasConnection(
        user_id=user_id,
        access_token_encrypted=canvas_connection._cipher().encrypt("old-token"),
    )
    replacement = CanvasConnection(
        user_id=user_id,
        access_token_encrypted=canvas_connection._cipher().encrypt("new-token"),
    )
    get_connection = AsyncMock(side_effect=[initial, replacement, replacement])
    operation = AsyncMock(
        side_effect=[CanvasRequestError("unauthorized", 401), {"ok": True}]
    )

    @asynccontextmanager
    async def connection_session(_db):
        yield connection_db

    monkeypatch.setattr(canvas_connection, "_connection_session", connection_session)
    monkeypatch.setattr(canvas_connection, "get_connection", get_connection)
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(AsyncMock())
    )

    assert await canvas_connection.call_canvas(
        AsyncMock(), user_id, operation
    ) == {"ok": True}
    assert operation.await_args_list[0].args[1] == "old-token"
    assert operation.await_args_list[1].args[1] == "new-token"
    assert replacement.access_token_encrypted is not None


@pytest.mark.asyncio
async def test_permission_error_does_not_invalidate_token(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-forbidden@example.com",
        student_number=None,
    )
    connection = CanvasConnection(
        user_id=professor.id,
        access_token_encrypted=canvas_connection._cipher().encrypt("valid-token"),
    )
    db_session.add(connection)
    await db_session.commit()
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(AsyncMock())
    )

    with pytest.raises(ForbiddenError):
        await canvas_connection.call_canvas(
            db_session,
            professor.id,
            AsyncMock(side_effect=CanvasRequestError("forbidden", 403)),
        )

    await db_session.refresh(connection)
    assert connection.access_token_encrypted is not None


def test_canvas_rate_limits_have_a_distinct_api_error():
    error = canvas_connection._service_error(CanvasRequestError("throttled", 429))

    assert isinstance(error, RateLimitError)
    assert error.code == "canvas_rate_limited"


@pytest.mark.asyncio
async def test_call_canvas_enforces_end_to_end_deadline(monkeypatch):
    connection_db = AsyncMock()
    connection = CanvasConnection(
        user_id=uuid.uuid4(),
        access_token_encrypted=canvas_connection._cipher().encrypt("token"),
    )

    @asynccontextmanager
    async def connection_session(_db):
        yield connection_db

    async def never_finishes(_client, _token):
        await asyncio.Event().wait()

    monkeypatch.setattr(settings, "canvas_operation_timeout_seconds", 0.01)
    monkeypatch.setattr(canvas_connection, "_connection_session", connection_session)
    monkeypatch.setattr(
        canvas_connection, "get_connection", AsyncMock(return_value=connection)
    )
    monkeypatch.setattr(
        canvas_connection, "_client", lambda: ClientContext(AsyncMock())
    )

    with pytest.raises(ServiceUnavailableError) as error:
        await canvas_connection.call_canvas(
            AsyncMock(), connection.user_id, never_finishes
        )
    assert error.value.code == "canvas_operation_timeout"


@pytest.mark.asyncio
async def test_disconnect_deletes_only_omr_token_copy(
    db_session, create_user, monkeypatch
):
    professor = await create_user(
        role=UserRole.PROFESSOR,
        email="token-disconnect@example.com",
        student_number=None,
    )
    db_session.add(
        CanvasConnection(
            user_id=professor.id,
            access_token_encrypted=canvas_connection._cipher().encrypt("token"),
        )
    )
    await db_session.commit()
    client_factory = Mock()
    monkeypatch.setattr(canvas_connection, "_client", client_factory)

    await canvas_connection.disconnect(db_session, professor.id)

    assert await db_session.scalar(
        select(CanvasConnection).where(CanvasConnection.user_id == professor.id)
    ) is None
    client_factory.assert_not_called()
