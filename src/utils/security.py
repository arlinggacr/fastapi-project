"""Password hashing and JWT helpers."""

from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from src.core.config import get_settings
from src.core.time import utcnow

_password_hash = PasswordHash.recommended()

# Argon2 needs a bounded input; refuse absurd payloads outright.
MAX_PASSWORD_BYTES = 1024


def hash_password(password: str) -> str:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("password is too long")
    return _password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return _password_hash.verify(password, hashed)
    except Exception:
        return False


def _create_token(subject: UUID | str, token_type: str, ttl: timedelta) -> str:
    settings = get_settings()
    now = utcnow()
    payload = {
        "sub": str(subject),
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": uuid4().hex,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: UUID | str) -> str:
    settings = get_settings()
    return _create_token(user_id, "access", timedelta(minutes=settings.access_token_ttl_minutes))


def create_refresh_token(user_id: UUID | str) -> str:
    settings = get_settings()
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_ttl_days))


def decode_token(token: str, *, expected_type: str | None = None) -> dict[str, Any]:
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub", "type"]},
    )
    if expected_type and payload.get("type") != expected_type:
        raise jwt.InvalidTokenError(f"expected a {expected_type} token")
    return payload
