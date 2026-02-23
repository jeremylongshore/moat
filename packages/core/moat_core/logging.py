"""
moat_core.logging
~~~~~~~~~~~~~~~~~
Shared structured JSON logging configuration for all Moat services.

Provides consistent JSON-formatted logs across all services with:
- Standard fields: level, logger, message, service, timestamp
- Extra context fields from logger.info(..., extra={...})
- Automatic redaction of sensitive fields (passwords, tokens, etc.)
- Automatic exception formatting
- Uvicorn access log suppression

Usage::

    from moat_core.logging import configure_logging

    # In service main.py (before any other logging)
    configure_logging(level="INFO", service_name="moat-gateway")
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# Field names whose values should never be logged verbatim.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        "password",
        "passwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "credential",
        "credential_value",
        "credential_reference",
        "authorization",
        "x-api-key",
        "private_key",
        "client_secret",
        "jwt_secret",
    }
)


def _redact(value: Any, key: str = "") -> Any:
    """Recursively redact sensitive values from a structure."""
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging.

    Outputs one JSON object per line with standard fields plus
    any extra context provided via logger.info(..., extra={...}).
    """

    # Standard LogRecord attributes to exclude from extra fields
    _EXCLUDE_ATTRS = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "thread",
            "threadName",
            "taskName",  # asyncio task name
        }
    )

    def __init__(self, service_name: str = "moat") -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string."""
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self.service_name,
            "timestamp": self.formatTime(record),
        }

        # Add extra fields from record (with redaction)
        for key, val in record.__dict__.items():
            if key not in self._EXCLUDE_ATTRS:
                payload[key] = _redact(val, key)

        # Add exception info if present
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(
    level: str = "INFO",
    service_name: str = "moat",
    *,
    suppress_uvicorn_access: bool = True,
) -> None:
    """Configure structured JSON logging for a Moat service.

    This should be called once at service startup, before any other
    logging occurs.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        service_name: Service name to include in all log entries.
        suppress_uvicorn_access: If True, reduce uvicorn.access to WARNING.
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name=service_name))

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers = [handler]

    if suppress_uvicorn_access:
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
