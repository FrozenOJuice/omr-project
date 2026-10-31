import uuid

import jwt
import pytest

from core import tokens


TEST_SECRET = "canvas-student-token-secret-with-at-least-32-bytes"


def _configure_canvas_student_tokens(monkeypatch, expires_in_seconds=604800):
    monkeypatch.setattr(tokens.settings, "jwt_access_secret", TEST_SECRET)
    monkeypatch.setattr(
        tokens.settings,
        "canvas_student_access_token_expire_seconds",
        expires_in_seconds,
    )


def _create_token(monkeypatch):
    _configure_canvas_student_tokens(monkeypatch)
    student_id = uuid.uuid4()
    exam_grade_id = uuid.uuid4()
    token = tokens.create_canvas_student_access_token(
        student_id,
        exam_grade_id,
        "canvas-user-42",
    )
    return token, student_id, exam_grade_id


def test_canvas_student_access_token_is_scoped_and_time_limited(monkeypatch):
    token, student_id, exam_grade_id = _create_token(monkeypatch)

    payload = tokens.decode_canvas_student_access_token(token)

    assert payload["sub"] == str(student_id)
    assert payload["exam_grade_id"] == str(exam_grade_id)
    assert payload["canvas_user_id"] == "canvas-user-42"
    assert payload["type"] == tokens.CANVAS_STUDENT_ACCESS_TOKEN_TYPE
    assert payload["aud"] == tokens.CANVAS_STUDENT_ACCESS_TOKEN_AUDIENCE
    assert payload["exp"] - payload["iat"] == 604800
    uuid.UUID(payload["jti"])


def test_canvas_student_access_tokens_are_unique(monkeypatch):
    _configure_canvas_student_tokens(monkeypatch)
    student_id = uuid.uuid4()
    exam_grade_id = uuid.uuid4()

    first = tokens.create_canvas_student_access_token(
        student_id,
        exam_grade_id,
        "canvas-user-42",
    )
    second = tokens.create_canvas_student_access_token(
        student_id,
        exam_grade_id,
        "canvas-user-42",
    )

    assert first != second
    assert (
        tokens.decode_canvas_student_access_token(first)["jti"]
        != tokens.decode_canvas_student_access_token(second)["jti"]
    )


def test_canvas_student_access_token_rejects_general_access_token(monkeypatch):
    _configure_canvas_student_tokens(monkeypatch)
    monkeypatch.setattr(tokens.settings, "jwt_access_expire_seconds", 900)
    access_token = tokens.create_access_token(str(uuid.uuid4()))

    with pytest.raises(ValueError):
        tokens.decode_canvas_student_access_token(access_token)


def test_general_access_decoder_rejects_canvas_student_token(monkeypatch):
    token, _, _ = _create_token(monkeypatch)

    with pytest.raises(ValueError):
        tokens.decode_access_token(token)


def test_canvas_student_access_token_expires(monkeypatch):
    _configure_canvas_student_tokens(monkeypatch, expires_in_seconds=-1)
    token = tokens.create_canvas_student_access_token(
        uuid.uuid4(),
        uuid.uuid4(),
        "canvas-user-42",
    )

    with pytest.raises(ValueError):
        tokens.decode_canvas_student_access_token(token)


def test_canvas_student_access_token_rejects_tampered_scope(monkeypatch):
    token, _, _ = _create_token(monkeypatch)
    payload = jwt.decode(token, options={"verify_signature": False})
    payload["exam_grade_id"] = str(uuid.uuid4())
    tampered_token = jwt.encode(
        payload,
        "attacker-secret-with-at-least-32-bytes",
        algorithm=tokens.JWT_ALGORITHM,
    )

    with pytest.raises(ValueError):
        tokens.decode_canvas_student_access_token(tampered_token)


@pytest.mark.parametrize(
    "missing_claim",
    ["sub", "exam_grade_id", "canvas_user_id", "jti", "iat", "exp", "aud"],
)
def test_canvas_student_access_token_requires_all_claims(monkeypatch, missing_claim):
    token, _, _ = _create_token(monkeypatch)
    payload = jwt.decode(token, options={"verify_signature": False})
    payload.pop(missing_claim)
    incomplete_token = jwt.encode(
        payload,
        TEST_SECRET,
        algorithm=tokens.JWT_ALGORITHM,
    )

    with pytest.raises(ValueError):
        tokens.decode_canvas_student_access_token(incomplete_token)


@pytest.mark.parametrize(
    ("claim", "invalid_value"),
    [
        ("sub", "not-a-uuid"),
        ("exam_grade_id", "not-a-uuid"),
        ("jti", "not-a-uuid"),
        ("canvas_user_id", "   "),
    ],
)
def test_canvas_student_access_token_rejects_invalid_scope_claims(
    monkeypatch,
    claim,
    invalid_value,
):
    token, _, _ = _create_token(monkeypatch)
    payload = jwt.decode(token, options={"verify_signature": False})
    payload[claim] = invalid_value
    invalid_token = jwt.encode(
        payload,
        TEST_SECRET,
        algorithm=tokens.JWT_ALGORITHM,
    )

    with pytest.raises(ValueError):
        tokens.decode_canvas_student_access_token(invalid_token)


@pytest.mark.parametrize(
    ("student_id", "exam_grade_id", "canvas_user_id"),
    [
        ("not-a-uuid", uuid.uuid4(), "canvas-user-42"),
        (uuid.uuid4(), "not-a-uuid", "canvas-user-42"),
        (uuid.uuid4(), uuid.uuid4(), "   "),
    ],
)
def test_canvas_student_access_token_rejects_invalid_scope_on_creation(
    monkeypatch,
    student_id,
    exam_grade_id,
    canvas_user_id,
):
    _configure_canvas_student_tokens(monkeypatch)

    with pytest.raises(ValueError):
        tokens.create_canvas_student_access_token(
            student_id,
            exam_grade_id,
            canvas_user_id,
        )
