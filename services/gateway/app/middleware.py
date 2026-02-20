"""
app.middleware
~~~~~~~~~~~~~~
Gateway middleware components.

RedactionMiddleware
    Intercepts request/response logging and scrubs sensitive field values
    before they can be emitted to any log sink.

RequestIDMiddleware
    Generates a UUID for each inbound request and attaches it to both
    ``request.state`` and the outbound ``X-Request-ID`` response header.
    Accepts an existing ``X-Request-ID`` from the caller for end-to-end
    request tracing across services.
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

logger = logging.getLogger(__name__)

# Field names whose values should never appear in logs
_SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "credential_reference",
        "authorization",
        "x-api-key",
        "private_key",
        "client_secret",
        "access_token",
        "refresh_token",
    }
)


def redact_dict(data: Any, _depth: int = 0) -> Any:
    """Recursively replace sensitive values with ``[REDACTED]``.

    Limits recursion to 10 levels to guard against deeply nested payloads.
    """
    if _depth > 10:
        return data
    if isinstance(data, dict):
        return {
            k: "[REDACTED]"
            if k.lower() in _SENSITIVE_KEYS
            else redact_dict(v, _depth + 1)
            for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact_dict(item, _depth + 1) for item in data]
    return data


class RedactionMiddleware(BaseHTTPMiddleware):
    """Log sanitiser that redacts secret fields from request/response context.

    This middleware does NOT modify the actual request or response bodies -
    it only ensures that when request context is written to logs it is safe.
    The redaction is applied to ``request.state.log_context`` which other
    middleware and handlers may populate.
    """

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next: object) -> Response:
        # Attach a mutable log context dict to state so handlers can add fields
        # without worrying about accidental secret leakage.
        request.state.log_context: dict[str, Any] = {}

        response: Response = await call_next(request)  # type: ignore[arg-type]

        # Redact the context before it can be emitted.
        safe_ctx = redact_dict(request.state.log_context)
        if safe_ctx:
            logger.debug("Request context (redacted)", extra=safe_ctx)

        return response


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Attach a per-request UUID for end-to-end tracing.

    Reads ``X-Request-ID`` from the inbound request if present (allowing
    callers to propagate their own IDs). Otherwise generates a new UUID v4.

    The ID is stored in ``request.state.request_id`` and echoed back in
    the ``X-Request-ID`` response header.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id

        start = time.monotonic()
        response: Response = await call_next(request)  # type: ignore[arg-type]
        duration_ms = (time.monotonic() - start) * 1000

        response.headers["X-Request-ID"] = request_id

        logger.info(
            "Request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response
