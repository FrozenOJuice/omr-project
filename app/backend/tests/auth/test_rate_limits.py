import pytest

pytestmark = pytest.mark.db


async def test_register_rate_limit_is_per_ip(register_user):
    for index in range(5):
        response = await register_user(email=f"user-{index}@example.com")
        assert response.status_code == 200

    response = await register_user(email="user-5@example.com")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


async def test_login_rate_limit_is_per_email(register_user, login_user):
    await register_user()

    for _ in range(5):
        response = await login_user(password="WrongPassword123!")
        assert response.status_code == 401

    response = await login_user(password="WrongPassword123!")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


async def test_login_rate_limit_is_per_ip(login_user):
    for index in range(20):
        response = await login_user(email=f"missing-{index}@example.com")
        assert response.status_code == 401

    response = await login_user(email="missing-20@example.com")

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


async def test_refresh_rate_limit_is_per_ip(client):
    for index in range(60):
        response = await client.post(
            "/api/auth/refresh",
            json={"refresh_token": f"not-a-refresh-token-{index}"},
        )
        assert response.status_code == 401

    response = await client.post(
        "/api/auth/refresh",
        json={"refresh_token": "not-a-refresh-token-60"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"


async def test_password_reset_request_rate_limit_is_per_email(client):
    for _ in range(3):
        response = await client.post(
            "/api/auth/password-reset/request",
            json={"email": "alice@example.com"},
        )
        assert response.status_code == 202

    response = await client.post(
        "/api/auth/password-reset/request",
        json={"email": "alice@example.com"},
    )

    assert response.status_code == 429
    assert response.json()["error"]["code"] == "rate_limited"
