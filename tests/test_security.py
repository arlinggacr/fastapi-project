import jwt
import pytest
from src.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_round_trip():
    hashed = hash_password("Passw0rd!123")
    assert hashed != "Passw0rd!123"
    assert verify_password("Passw0rd!123", hashed)
    assert not verify_password("wrong", hashed)


def test_verify_rejects_garbage_hash():
    assert not verify_password("anything", "not-a-hash")


def test_access_token_round_trip():
    token = create_access_token("user-1")
    claims = decode_token(token, expected_type="access")
    assert claims["sub"] == "user-1"
    assert claims["type"] == "access"


def test_token_type_is_enforced():
    refresh = create_refresh_token("user-1")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(refresh, expected_type="access")


def test_tampered_token_is_rejected():
    token = create_access_token("user-1")
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token[:-2] + "xx")
