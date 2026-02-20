"""
moat_core.security_headers
~~~~~~~~~~~~~~~~~~~~~~~~~~
Starlette middleware that adds standard security headers to every response.
"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add security headers to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: object) -> Response:
        response: Response = await call_next(request)  # type: ignore[arg-type]
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Referrer-Policy", "strict-origin-when-cross-origin"
        )
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault("X-XSS-Protection", "1; mode=block")
        response.headers.setdefault(
            "Cache-Control", "no-store, no-cache, must-revalidate"
        )
        return response
