import pytest

from core import tokens


def test_access_token_round_trip(monkeypatch):
    monkeypatch.setattr(
        tokens.settings,
        "jwt_access_secret",
        "access-secret-with-enough-length",
    )
    monkeypatch.setattr(tokens.settings, "jwt_access_expire_seconds", 900)

    token = tokens.create_access_token("user-id")
    payload = tokens.decode_access_token(token)

    assert payload["sub"] == "user-id"
    assert payload["type"] == "access"
    assert payload["exp"] - payload["iat"] == 900


def test_refresh_token_rejected_as_access_token(monkeypatch):
    monkeypatch.setattr(
        tokens.settings,
        "jwt_access_secret",
        "access-secret-with-enough-length",
    )
    monkeypatch.setattr(
        tokens.settings,
        "jwt_refresh_secret",
        "refresh-secret-with-enough-length",
    )
    monkeypatch.setattr(tokens.settings, "jwt_refresh_expire_seconds", 604800)

    token = tokens.create_refresh_token("user-id")

    with pytest.raises(ValueError):
        tokens.decode_access_token(token)


def test_refresh_token_uses_configured_lifetime_in_seconds(monkeypatch):
    monkeypatch.setattr(
        tokens.settings,
        "jwt_refresh_secret",
        "refresh-secret-with-enough-length",
    )
    monkeypatch.setattr(tokens.settings, "jwt_refresh_expire_seconds", 604800)

    token = tokens.create_refresh_token("user-id")
    payload = tokens.decode_refresh_token(token)

    assert payload["exp"] - payload["iat"] == 604800
