"""Response envelopes, translated from the C# ``ResHandler``.

Every response is wrapped in one of two shapes::

    {"status": true,  "data": ..., "message": "...", "pagination": ... | null}
    {"status": false, "message": "...", "error": ...}

The JSON keys keep the original camelCase spelling (``totalData``,
``totalPage``) so the wire format stays identical to the C# implementation.

Differences from the C# original, all deliberate:

* The unused ``HttpResponse? res`` parameter is gone. It was accepted and then
  never referenced in either method.
* ``success`` runs its payload through ``jsonable_encoder`` so callers may pass
  ORM rows, Pydantic models, UUIDs, datetimes and Decimals directly.
* Database-unavailable detection walks the exception's ``__cause__`` chain
  because SQLAlchemy wraps driver errors; ``Exception.ToString()`` flattened
  that chain for free in .NET.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

VALIDATION_FAILED_MESSAGE = "Validation failed"
DATABASE_UNAVAILABLE_MESSAGE = "Database service is currently unavailable. Please try again later."
SERVER_ERROR_MESSAGE = "Maaf, terjadi kegagalan pada server kami."


@dataclass(frozen=True, slots=True)
class PageHandler:
    """Pagination metadata carried alongside a list payload."""

    total_data: int
    total_page: int
    page: int

    @classmethod
    def build(cls, *, total_data: int, page: int, page_size: int) -> PageHandler:
        """Derive ``total_page`` from a total count and a page size."""
        total_page = -(-total_data // page_size) if page_size > 0 else 0
        return cls(total_data=total_data, total_page=total_page, page=page)

    def as_dict(self) -> dict[str, int]:
        return {
            "totalData": self.total_data,
            "totalPage": self.total_page,
            "page": self.page,
        }


class ClientError(Exception):
    """An error whose status code and details are safe to return to clients."""

    def __init__(self, message: str, status_code: int = 400, errors: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.errors = errors


class ValidationError(ClientError):
    def __init__(self, message: str, errors: Any = None) -> None:
        super().__init__(message, 400, errors)


class NotFoundError(ClientError):
    def __init__(self, message: str, errors: Any = None) -> None:
        super().__init__(message, 404, errors)


class InvariantError(ClientError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 400)


class AuthorizationError(ClientError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 403)


class AuthenticationError(ClientError):
    def __init__(self, message: str) -> None:
        super().__init__(message, 401)


def success(
    data: Any,
    message: str,
    pagination: PageHandler | None = None,
) -> dict[str, Any]:
    """Build a success envelope.

    Returns a plain dict rather than a ``JSONResponse`` so FastAPI still runs
    it through ``response_model=SuccessEnvelope[...]``. That keeps the OpenAPI
    schema honest and lets ORM rows be converted to DTOs on the way out. The
    HTTP status comes from the route's ``status_code``.
    """
    return {
        "status": True,
        "data": data,
        "message": message,
        "pagination": pagination.as_dict() if pagination is not None else None,
    }


# Markers copied verbatim from the C# implementation. They are matched against
# the flattened exception text, case-insensitively.
_DB_ERROR_MARKERS = (
    "PgBouncer",
    "Npgsql",
    "connection to database",
    "failed to connect",
    "timeout",
    "An error occurred using the connection to database",
)


def _exception_text(exc: BaseException) -> str:
    """Flatten an exception and its wrapped causes into one searchable string."""
    parts: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        parts.append(f"{type(current).__name__}: {current}")
        wrapped = current.__cause__ or current.__context__
        current = wrapped if isinstance(wrapped, BaseException) else None
    return "\n".join(parts)


def _is_database_unavailable(exc: BaseException) -> bool:
    text = _exception_text(exc)
    if "ECONNREFUSED" not in text:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _DB_ERROR_MARKERS)


def from_http_exception(exc: StarletteHTTPException) -> JSONResponse:
    """Translate an ``HTTPException`` into the error envelope.

    The project's :class:`~src.common.responses.errors.ApiError` stores
    ``{"code": ..., "message": ..., **extra}`` in ``detail``. The stable code
    is preserved inside the envelope's ``error`` field so clients keep a
    machine-readable identifier.
    """
    # Starlette types ``detail`` as ``str``, but FastAPI allows any payload
    # here (ApiError stores a dict), so widen before narrowing with isinstance.
    detail: Any = exc.detail
    error_payload: Any = None

    if isinstance(detail, dict) and "message" in detail:
        message = str(detail["message"])
        extra = {key: value for key, value in detail.items() if key != "message"}
        error_payload = extra or None
    else:
        message = str(detail)

    return JSONResponse(
        content=jsonable_encoder(
            {"status": False, "message": message, "error": error_payload}
        ),
        status_code=exc.status_code,
        headers=exc.headers,
    )


def error(exc: BaseException | Sequence[str]) -> JSONResponse:
    """Translate any failure into the error envelope."""
    if isinstance(exc, ClientError):
        return JSONResponse(
            content=jsonable_encoder(
                {"status": False, "message": exc.message, "error": exc.errors}
            ),
            status_code=exc.status_code,
        )

    if isinstance(exc, StarletteHTTPException):
        return from_http_exception(exc)

    # A sequence of messages is treated as validation output. str/bytes are
    # sequences too, so they are excluded to avoid iterating characters.
    if isinstance(exc, Sequence) and not isinstance(exc, str | bytes | bytearray):
        return JSONResponse(
            content={
                "status": False,
                "message": VALIDATION_FAILED_MESSAGE,
                "error": [str(item) for item in exc],
            },
            status_code=400,
        )

    if isinstance(exc, BaseException) and _is_database_unavailable(exc):
        return JSONResponse(
            content={"status": False, "message": DATABASE_UNAVAILABLE_MESSAGE},
            status_code=503,
        )

    if isinstance(exc, BaseException):
        logger.error("unhandled error", exc_info=exc)
    else:
        logger.error("unhandled error: %r", exc)
    return JSONResponse(
        content={"status": False, "message": SERVER_ERROR_MESSAGE},
        status_code=500,
    )
