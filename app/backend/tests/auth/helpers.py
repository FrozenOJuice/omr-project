from core import tokens


async def get_persisted_refresh_token(get_refresh_token_by_hash, refresh_token: str):
    return await get_refresh_token_by_hash(tokens.hash_token(refresh_token))


def assert_invalid_credentials(response):
    error = response.json()["error"]

    assert response.status_code == 401
    assert error["code"] == "invalid_credentials"
    assert error["message"] == "Invalid email or password"


def assert_account_disabled(response):
    error = response.json()["error"]

    assert response.status_code == 401
    assert error["code"] == "account_disabled"
    assert error["message"] == "Your account has been disabled"
