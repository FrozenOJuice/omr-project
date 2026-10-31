import pytest

from models.user import UserRole


@pytest.fixture
def admin_access_token(client, create_user, login_user):
    async def _admin_access_token(
        *,
        email: str = "admin@example.com",
        password: str = "Password123!",
    ):
        await create_user(email=email, password=password, role=UserRole.ADMIN)
        response = await login_user(email=email, password=password)

        assert response.status_code == 200, response.json()

        return response.json()["access_token"]

    return _admin_access_token


@pytest.fixture
def auth_headers():
    def _auth_headers(token: str):
        return {"Authorization": f"Bearer {token}"}

    return _auth_headers


@pytest.fixture
def admin_headers(admin_access_token, auth_headers):
    async def _admin_headers(**kwargs):
        token = await admin_access_token(**kwargs)

        return auth_headers(token)

    return _admin_headers
