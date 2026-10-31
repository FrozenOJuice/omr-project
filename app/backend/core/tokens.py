import hashlib
import time
import uuid

import jwt

from core.settings import settings

JWT_ALGORITHM = "HS256"
CANVAS_STUDENT_ACCESS_TOKEN_TYPE = "canvas_student_access"
CANVAS_STUDENT_ACCESS_TOKEN_AUDIENCE = "canvas_marked_result"


def create_access_token(subject: str) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        secret=settings.jwt_access_secret,
        expires_in_seconds=settings.jwt_access_expire_seconds,
    )


def create_refresh_token(subject: str) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        secret=settings.jwt_refresh_secret,
        expires_in_seconds=settings.jwt_refresh_expire_seconds,
        jti=str(uuid.uuid4()),
    )


def create_canvas_student_access_token(
    student_id: str | uuid.UUID,
    exam_grade_id: str | uuid.UUID,
    canvas_user_id: str,
) -> str:
    return _create_token(
        subject=_uuid_identifier(student_id, "student_id"),
        token_type=CANVAS_STUDENT_ACCESS_TOKEN_TYPE,
        secret=settings.jwt_access_secret,
        expires_in_seconds=settings.canvas_student_access_token_expire_seconds,
        jti=str(uuid.uuid4()),
        audience=CANVAS_STUDENT_ACCESS_TOKEN_AUDIENCE,
        additional_claims={
            "exam_grade_id": _uuid_identifier(exam_grade_id, "exam_grade_id"),
            "canvas_user_id": _non_empty_string(canvas_user_id, "canvas_user_id"),
        },
    )


def decode_access_token(token: str) -> dict:
    return _decode_token(
        token=token,
        token_type="access",
        secret=settings.jwt_access_secret,
    )


def decode_refresh_token(token: str) -> dict:
    return _decode_token(
        token=token,
        token_type="refresh",
        secret=settings.jwt_refresh_secret,
    )


def decode_canvas_student_access_token(token: str) -> dict:
    payload = _decode_token(
        token=token,
        token_type=CANVAS_STUDENT_ACCESS_TOKEN_TYPE,
        secret=settings.jwt_access_secret,
        audience=CANVAS_STUDENT_ACCESS_TOKEN_AUDIENCE,
        required_claims=(
            "sub",
            "type",
            "iat",
            "exp",
            "jti",
            "aud",
            "exam_grade_id",
            "canvas_user_id",
        ),
    )
    _uuid_identifier(payload["sub"], "student_id")
    _uuid_identifier(payload["exam_grade_id"], "exam_grade_id")
    _uuid_identifier(payload["jti"], "jti")
    _non_empty_string(payload["canvas_user_id"], "canvas_user_id")
    return payload


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _create_token(
    subject: str,
    token_type: str,
    secret: str,
    expires_in_seconds: int,
    jti: str | None = None,
    audience: str | None = None,
    additional_claims: dict | None = None,
) -> str:
    now = int(time.time())
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_in_seconds,
    }

    if jti:
        payload["jti"] = jti
    if audience:
        payload["aud"] = audience
    if additional_claims:
        if payload.keys() & additional_claims.keys():
            raise ValueError("Additional claims cannot override token claims")
        payload.update(additional_claims)

    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def _decode_token(
    token: str,
    token_type: str,
    secret: str,
    audience: str | None = None,
    required_claims: tuple[str, ...] = (),
) -> dict:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=audience,
            options={"require": list(required_claims)},
        )
    except jwt.PyJWTError as exc:
        raise ValueError("Invalid token") from exc

    if payload.get("type") != token_type:
        raise ValueError("Invalid token type")

    return payload


def _uuid_identifier(value: str | uuid.UUID, claim_name: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {claim_name}") from exc


def _non_empty_string(value: str, claim_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Invalid {claim_name}")
    return value.strip()
