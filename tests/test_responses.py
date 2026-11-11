"""Response envelope behaviour.

The success/error shapes are a cross-cutting contract, so they are covered
directly here as well as through the endpoints.
"""

from __future__ import annotations

import json

import pytest
from src.utils.responses import (
    AuthenticationError,
    AuthorizationError,
    ClientError,
    InvariantError,
    NotFoundError,
    PageHandler,
    ValidationError,
    error,
    success,
)


def _body(response) -> dict:
    return json.loads(response.body)


# --------------------------------------------------------------------------- #
# success
# --------------------------------------------------------------------------- #
def test_success_shape_without_pagination():
    body = success({"id": 1}, "Created")

    assert body == {
        "status": True,
        "data": {"id": 1},
        "message": "Created",
        "pagination": None,
    }


def test_success_shape_with_pagination():
    body = success([1, 2], "OK", PageHandler(total_data=42, total_page=3, page=2))

    assert body["status"] is True
    assert body["data"] == [1, 2]
    # camelCase keys are part of the wire contract.
    assert body["pagination"] == {"totalData": 42, "totalPage": 3, "page": 2}


@pytest.mark.parametrize(
    ("total", "page_size", "expected_pages"),
    [(0, 10, 0), (1, 10, 1), (10, 10, 1), (11, 10, 2), (554, 3, 185)],
)
def test_page_handler_build_rounds_up(total, page_size, expected_pages):
    page = PageHandler.build(total_data=total, page=1, page_size=page_size)
    assert page.total_page == expected_pages


# --------------------------------------------------------------------------- #
# client errors
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("exc", "status_code"),
    [
        (ValidationError("bad", ["x"]), 400),
        (InvariantError("nope"), 400),
        (AuthenticationError("who"), 401),
        (AuthorizationError("no"), 403),
        (NotFoundError("gone"), 404),
        (ClientError("teapot", 418, {"k": "v"}), 418),
    ],
)
def test_client_error_maps_status_and_shape(exc, status_code):
    response = error(exc)
    body = _body(response)

    assert response.status_code == status_code
    assert body["status"] is False
    assert body["message"] == exc.message
    assert body["error"] == exc.errors


def test_validation_message_list_uses_generic_message():
    body = _body(error(["email is invalid", "password too short"]))

    assert body == {
        "status": False,
        "message": "Validation failed",
        "error": ["email is invalid", "password too short"],
    }


# --------------------------------------------------------------------------- #
# infrastructure failures
# --------------------------------------------------------------------------- #
def test_database_unavailable_returns_503():
    exc = ConnectionRefusedError("ECONNREFUSED 127.0.0.1:5432 connecting to PgBouncer")
    response = error(exc)

    assert response.status_code == 503
    assert "unavailable" in _body(response)["message"].lower()


def test_database_unavailable_detected_through_wrapped_cause():
    """SQLAlchemy wraps driver errors, so the cause chain must be inspected."""
    try:
        try:
            raise ConnectionRefusedError("ECONNREFUSED 127.0.0.1:5432")
        except ConnectionRefusedError as inner:
            raise RuntimeError("failed to connect to database") from inner
    except RuntimeError as wrapped:
        response = error(wrapped)

    assert response.status_code == 503


def test_non_database_connection_error_is_not_503():
    # ECONNREFUSED alone is not enough; the markers must also match.
    response = error(ConnectionRefusedError("ECONNREFUSED some other service"))
    assert response.status_code == 500


def test_unexpected_exception_returns_generic_500():
    response = error(ValueError("boom"))
    body = _body(response)

    assert response.status_code == 500
    assert body == {
        "status": False,
        "message": "Maaf, terjadi kegagalan pada server kami.",
    }
    # The real message must never reach the client.
    assert "boom" not in json.dumps(body)


def test_plain_string_does_not_crash():
    """A str is not an exception and not a message list; it falls back to 500."""
    response = error("just a string")  # type: ignore[arg-type]
    assert response.status_code == 500


# --------------------------------------------------------------------------- #
# HTTP exceptions
# --------------------------------------------------------------------------- #
def test_api_error_keeps_machine_readable_code():
    from src.common.responses import conflict

    body = _body(error(conflict("EMAIL_TAKEN", "That email is already registered")))

    assert body["status"] is False
    assert body["message"] == "That email is already registered"
    assert body["error"] == {"code": "EMAIL_TAKEN"}


def test_api_error_keeps_extra_fields():
    from src.common.responses import conflict

    body = _body(error(conflict("BID_TOO_LOW", "too low", min_next_bid="110.00")))

    assert body["error"] == {"code": "BID_TOO_LOW", "min_next_bid": "110.00"}


# --------------------------------------------------------------------------- #
# coverage: every operation must advertise the envelope
# --------------------------------------------------------------------------- #
def _operations() -> list[tuple[str, str, dict]]:
    from src.main import app

    spec = app.openapi()
    return [
        (method.upper(), path, operation)
        for path, methods in spec["paths"].items()
        for method, operation in methods.items()
        if method in {"get", "post", "patch", "put", "delete"}
    ]


def test_every_operation_documents_the_success_envelope():
    """A new endpoint that forgets the envelope fails this test."""
    offenders: list[str] = []

    for method, path, operation in _operations():
        for code, response in operation["responses"].items():
            if not code.startswith("2") or code == "204":
                continue
            schema = response.get("content", {}).get("application/json", {}).get("schema", {})
            if "SuccessEnvelope" not in schema.get("$ref", ""):
                offenders.append(f"{method} {path} -> {code} {schema}")

    assert not offenders, offenders


def test_bodyless_operations_declare_no_content():
    """204 must not advertise a body: HTTP forbids one."""
    offenders: list[str] = []

    for method, path, operation in _operations():
        response = operation["responses"].get("204")
        if response is None:
            continue
        if response.get("content"):
            offenders.append(f"{method} {path}")

    assert not offenders, offenders


def test_every_operation_documents_error_envelopes():
    """Errors are documented once at app level, so check it is wired."""
    from src.main import app

    spec = app.openapi()
    components = spec["components"]["schemas"]

    assert any("ErrorEnvelope" in name for name in components)
    for method, path, operation in _operations():
        if not path.startswith(("/docs", "/redoc", "/openapi")):
            assert operation["responses"], f"{method} {path} has no documented responses"

