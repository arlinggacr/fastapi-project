"""Security headers and request-size guards.

The API is JSON-only, so a strict Content-Security-Policy plus ``nosniff``
removes the main classes of browser-side injection risk even if a client
renders a response directly.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.utils.responses import ClientError, error

MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MiB

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "X-Permitted-Cross-Domain-Policies": "none",
    "Cross-Origin-Resource-Policy": "same-site",
    "Content-Security-Policy": (
        "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
    ),
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    """Reject oversized payloads before they reach a handler."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        length = request.headers.get("content-length")
        if length is not None:
            try:
                if int(length) > MAX_BODY_BYTES:
                    return error(
                        ClientError(
                            "Request body too large",
                            413,
                            {"code": "PAYLOAD_TOO_LARGE"},
                        )
                    )
            except ValueError:
                return error(
                    ClientError(
                        "Invalid Content-Length",
                        400,
                        {"code": "BAD_REQUEST"},
                    )
                )
        return await call_next(request)
