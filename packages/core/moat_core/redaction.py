"""
moat_core.redaction
~~~~~~~~~~~~~~~~~~~
Utilities for scrubbing secrets from request/response data before hashing
or logging.

Design principles
-----------------
* **Default-deny on secret keys** - a curated ``REDACT_KEYS`` frozenset
  covers the most common credential field names.  Callers can extend it
  via the ``denylist`` parameter.
* **Recursive** - nested dicts are walked so secrets buried inside
  structured payloads are caught.
* **Non-destructive** - all functions return *new* objects; originals are
  never mutated.
* **Deterministic** - ``hash_redacted`` produces the same SHA-256 digest
  for semantically identical data regardless of key insertion order,
  because the data is first sorted during JSON serialisation.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# ---------------------------------------------------------------------------
# Sensitive key registry
# ---------------------------------------------------------------------------

REDACT_KEYS: frozenset[str] = frozenset(
    {
        "authorization",
        "api_key",
        "api-key",
        "token",
        "password",
        "secret",
        "credential",
        "credentials",
        "access_token",
        "refresh_token",
        "client_secret",
        "private_key",
        "x-api-key",
        "x_api_key",
        "bearer",
        "session_token",
        "signing_key",
    }
)

_REDACTED_SENTINEL = "[REDACTED]"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_sensitive(key: str, denylist: frozenset[str]) -> bool:
    """Return True if *key* (case-insensitive) is in the denylist."""
    return key.lower() in denylist


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def redact_headers(headers: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of *headers* with sensitive values replaced by
    ``'[REDACTED]'``.

    Key comparison is case-insensitive and uses the built-in
    :data:`REDACT_KEYS` registry.

    Args:
        headers: Mapping of HTTP header names to their values.

    Returns:
        A new dict with the same keys; sensitive values are replaced.

    Example::

        >>> redact_headers({"Authorization": "Bearer tok",
        ...                  "Content-Type": "application/json"})
        {'Authorization': '[REDACTED]', ...}
    """
    return {
        k: _REDACTED_SENTINEL if _is_sensitive(k, REDACT_KEYS) else v
        for k, v in headers.items()
    }


def redact_body(
    body: dict[str, Any],
    denylist: frozenset[str] | None = None,
) -> dict[str, Any]:
    """Recursively redact sensitive keys in a nested dict.

    Args:
        body: Request or response body as a plain dict.
        denylist: Additional keys to redact beyond the defaults in
            :data:`REDACT_KEYS`.  The two sets are unioned; REDACT_KEYS
            is always applied.

    Returns:
        A new dict (deep copy of structure) with secrets replaced.

    Example::

        >>> redact_body({"user": "alice", "password": "s3cr3t",
        ...             "nested": {"api_key": "abc"}})
        {'user': 'alice', 'password': '[REDACTED]', ...}
    """
    effective_denylist = REDACT_KEYS if denylist is None else REDACT_KEYS | denylist
    return _redact_recursive(body, effective_denylist)


def _redact_recursive(
    obj: Any,
    denylist: frozenset[str],
) -> Any:
    """Internal recursive worker; handles dicts, lists, and scalars."""
    if isinstance(obj, dict):
        return {
            k: _REDACTED_SENTINEL
            if _is_sensitive(k, denylist)
            else _redact_recursive(v, denylist)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact_recursive(item, denylist) for item in obj]
    # Scalars (str, int, float, bool, None) are returned as-is
    return obj


def hash_redacted(data: Any, denylist: frozenset[str] | None = None) -> str:
    """Produce a deterministic SHA-256 hex digest of *data* after redaction.

    If *data* is a dict, :func:`redact_body` is applied first.
    The dict (or any other serialisable value) is then JSON-encoded with
    ``sort_keys=True`` to ensure key-order independence.

    Args:
        data: Any JSON-serialisable value.  Dicts are redacted first.
        denylist: Optional extra keys to redact (see :func:`redact_body`).

    Returns:
        64-character lowercase SHA-256 hex digest.

    Raises:
        TypeError: If *data* contains non-JSON-serialisable types after
            redaction.

    Example::

        >>> digest = hash_redacted({"user": "alice", "password": "s3cr3t"})
        >>> len(digest)
        64
        >>> digest == hash_redacted(  # order-independent
        ...     {"password": "s3cr3t", "user": "alice"})

        True
    """
    if isinstance(data, dict):
        data = redact_body(data, denylist)

    serialised = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(serialised.encode()).hexdigest()
