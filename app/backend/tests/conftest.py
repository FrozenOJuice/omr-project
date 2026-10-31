import os
import subprocess
import sys
from urllib.parse import unquote

import pytest
import pytest_asyncio
import asyncio
from argon2 import PasswordHasher
from dotenv import load_dotenv
from sqlalchemy import select
from sqlalchemy.engine import make_url
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
import uuid

load_dotenv()

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, backend_dir)

from core import tokens
from core import security
from core.security import hash_password
from dependencies.rate_limit import reset_auth_rate_limiter
from models.password_reset_token import PasswordResetToken
from models.refresh_token import RefreshToken
from models.retention_policy import RetentionPolicy
from models.user import AccountStatus
from models.user import User
from models.user import UserRole
from models.user import Institution
from services.admin_users import update_user_role


def _unique_student_number() -> str:
    return str(uuid.uuid4().int % 100_000_000).zfill(8)


@pytest.fixture
def authenticated_client(client, register_user):
    async def _authenticated_client(
        *,
        email: str = None,
        password: str = "Password123!",
    ):
        if email is None:
            email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        response = await register_user(email=email, password=password)
        assert response.status_code == 200, response.json()
        token = response.json()["access_token"]
        return client, token

    return _authenticated_client

@pytest.fixture(scope="session")
def event_loop():
    policy = asyncio.get_event_loop_policy()
    loop = policy.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
def use_test_auth_settings(monkeypatch):
    reset_auth_rate_limiter()
    monkeypatch.setattr(
        tokens.settings,
        "jwt_access_secret",
        "test-access-secret-with-at-least-32-bytes",
    )
    monkeypatch.setattr(
        tokens.settings,
        "jwt_refresh_secret",
        "test-refresh-secret-with-at-least-32-bytes",
    )
    monkeypatch.setattr(tokens.settings, "jwt_access_expire_seconds", 900)
    monkeypatch.setattr(tokens.settings, "jwt_refresh_expire_seconds", 604800)
    monkeypatch.setattr(tokens.settings, "password_reset_expire_seconds", 1800)
    monkeypatch.setattr(tokens.settings, "account_activation_expire_seconds", 259200)
    monkeypatch.setattr(tokens.settings, "course_invite_expire_seconds", 604800)
    monkeypatch.setattr(tokens.settings, "email_from", "OMR <no-reply@example.com>")
    # A real key is present in .env.dev, and the container loads it when running
    # the suite. Clearing it here makes Resend delivery fail closed so no test
    # can spend quota or mail a fixture address; tests that exercise delivery
    # set their own key or stub send_email.
    monkeypatch.setattr(tokens.settings, "resend_api_key", None)
    # .env.dev enables console email mode; pin it off so tests get deterministic
    # send/fail behavior. The console-mode test opts back in explicitly.
    monkeypatch.setattr(tokens.settings, "email_console_mode", False)
    monkeypatch.setattr(
        tokens.settings,
        "frontend_password_reset_url",
        "http://localhost:4200/reset-password",
    )
    monkeypatch.setattr(
        tokens.settings,
        "frontend_origin",
        "http://localhost:4200",
    )
    yield
    reset_auth_rate_limiter()


@pytest.fixture
def register_user(client):
    async def _register_user(
        *,
        first_name: str = "Alice",
        last_name: str = "Example",
        email: str = "alice@example.com",
        password: str = "Password123!",
        student_number: str | None = None,
    ):
        return await client.post(
            "/api/auth/register",
            json={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "password": password,
                "student_number": student_number or _unique_student_number(),
            },
        )

    return _register_user


@pytest.fixture
def login_user(client):
    async def _login_user(
        *,
        email: str = "alice@example.com",
        password: str = "Password123!",
    ):
        return await client.post(
            "/api/auth/login",
            json={
                "email": email,
                "password": password,
            },
        )

    return _login_user


@pytest.fixture
def create_user(db_session):
    async def _create_user(
        *,
        first_name: str = "Alice",
        last_name: str = "Example",
        email: str = "alice@example.com",
        password: str = "Password123!",
        role: UserRole = UserRole.STUDENT,
        status: AccountStatus = AccountStatus.ACTIVE,
        student_number: str | None = None,
        institution: Institution = Institution.UBC,
    ):
        if role == UserRole.STUDENT and student_number is None:
            student_number = _unique_student_number()

        user = User(
            first_name=first_name,
            last_name=last_name,
            email=email,
            password_hash=hash_password(password),
            role=role.value,
            status=status.value,
            student_number=student_number,
            institution=institution.value,
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)

        return user

    return _create_user


@pytest.fixture
def get_user_by_email(db_session):
    async def _get_user_by_email(email: str):
        result = await db_session.execute(select(User).where(User.email == email))

        return result.scalar_one_or_none()

    return _get_user_by_email


@pytest.fixture
def get_refresh_token_by_hash(db_session):
    async def _get_refresh_token_by_hash(token_hash: str):
        result = await db_session.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )

        return result.scalar_one_or_none()

    return _get_refresh_token_by_hash


@pytest.fixture
def get_password_reset_token_by_hash(db_session):
    async def _get_password_reset_token_by_hash(token_hash: str):
        result = await db_session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash
            )
        )

        return result.scalar_one_or_none()

    return _get_password_reset_token_by_hash


@pytest.fixture(scope="session")
def test_database_url():
    """Retrieves the testing database target URL from the runtime environment."""
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL environment variable is not set")
    return _normalize_test_database_url(database_url)


@pytest_asyncio.fixture(scope="session")
async def db_engine(test_database_url):
    """Initializes a single, persistent database engine for the entire test session."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def setup_db(test_database_url):
    """Applies Alembic migrations ONCE at the start of the test session and tears down at the very end."""
    database_url = make_url(test_database_url)
    postgres_user = database_url.username or os.getenv("POSTGRES_USER", "test")
    postgres_password = database_url.password or os.getenv("POSTGRES_PASSWORD", "test")
    postgres_db = database_url.database or os.getenv("POSTGRES_DB", "test")

    os.environ["DATABASE_URL"] = test_database_url
    os.environ["DEBUG"] = "false"
    os.environ["POSTGRES_USER"] = postgres_user
    os.environ["POSTGRES_PASSWORD"] = postgres_password
    os.environ["POSTGRES_DB"] = postgres_db
    os.environ["JWT_ACCESS_SECRET"] = "test-access-secret-with-at-least-32-bytes"
    os.environ["JWT_REFRESH_SECRET"] = "test-refresh-secret-with-at-least-32-bytes"
    os.environ["JWT_ACCESS_EXPIRE_SECONDS"] = "900"
    os.environ["JWT_REFRESH_EXPIRE_SECONDS"] = "604800"

    from core.settings import settings

    settings.database_url = test_database_url
    settings.debug = False
    settings.postgres_user = postgres_user
    settings.postgres_password = postgres_password
    settings.postgres_db = postgres_db
    settings.jwt_access_secret = "test-access-secret-with-at-least-32-bytes"
    settings.jwt_refresh_secret = "test-refresh-secret-with-at-least-32-bytes"
    settings.jwt_access_expire_seconds = 900
    settings.jwt_refresh_expire_seconds = 604800

    # Production Argon2 settings deliberately consume substantial CPU and
    # memory. Tests create many accounts, so use a fast hasher only for this
    # isolated test process; production's security settings remain unchanged.
    security.password_hasher = PasswordHasher(
        time_cost=1,
        memory_cost=1_024,
        parallelism=1,
    )
    security.DUMMY_PASSWORD_HASH = security.password_hasher.hash(
        "dummy-password-for-timing-protection"
    )

    alembic_env = os.environ.copy()
    alembic_config = os.path.join(backend_dir, "alembic.ini")

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", alembic_config, "upgrade", "head"],
        cwd=backend_dir,
        env=alembic_env,
        check=True,
    )

    yield

    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", alembic_config, "downgrade", "base"],
        cwd=backend_dir,
        env=alembic_env,
        check=True,
    )


def _normalize_test_database_url(database_url: str) -> str:
    url = make_url(database_url)
    postgres_user = url.username or os.getenv("POSTGRES_USER")
    postgres_password = url.password or os.getenv("POSTGRES_PASSWORD")
    postgres_db = url.database or os.getenv("POSTGRES_DB")

    if postgres_user:
        url = url.set(username=postgres_user)

    if postgres_password:
        url = url.set(password=unquote(postgres_password))

    if postgres_db:
        url = url.set(database=postgres_db)

    return url.render_as_string(hide_password=False)


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Wraps each test function in an isolated transaction block that automatically rolls back."""
    async with db_engine.connect() as connection:
        transaction = await connection.begin()
        
        TestSessionLocal = async_sessionmaker(
            bind=connection,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )

        async with TestSessionLocal() as session:
            yield session
            
        await transaction.rollback()


@pytest_asyncio.fixture
async def client(db_session):
    """Generates an asynchronous HTTP test client with injected database overrides."""
    from db.session import get_db
    from main import app

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        follow_redirects=True, 
    ) as test_client:
        yield test_client

    app.dependency_overrides.clear()
