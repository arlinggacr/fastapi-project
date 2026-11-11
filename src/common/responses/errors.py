"""Errors that controllers and services raise.

These are *raise* helpers, not response builders: raise one and the registered
handlers in ``src.main`` convert it into the error envelope defined in
``src.utils.responses``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status


class ApiError(HTTPException):
    """HTTP error carrying a stable machine-readable ``code``."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        **extra: Any,
    ) -> None:
        detail: dict[str, Any] = {"code": code, "message": message}
        detail.update(extra)
        super().__init__(status_code=status_code, detail=detail)
        self.code = code


def not_found(resource: str = "Resource") -> ApiError:
    return ApiError(status.HTTP_404_NOT_FOUND, "NOT_FOUND", f"{resource} not found")


def forbidden(message: str = "You do not have permission to do that") -> ApiError:
    return ApiError(status.HTTP_403_FORBIDDEN, "FORBIDDEN", message)


def conflict(code: str, message: str, **extra: Any) -> ApiError:
    return ApiError(status.HTTP_409_CONFLICT, code, message, **extra)


def unauthorized(message: str = "Invalid or expired credentials") -> ApiError:
    return ApiError(status.HTTP_401_UNAUTHORIZED, "UNAUTHORIZED", message)


def too_many_requests(message: str = "Too many requests, slow down") -> ApiError:
    return ApiError(status.HTTP_429_TOO_MANY_REQUESTS, "RATE_LIMITED", message)
