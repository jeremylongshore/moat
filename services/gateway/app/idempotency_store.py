"""
app.idempotency_store
~~~~~~~~~~~~~~~~~~~~~
In-memory idempotency store for MVP.

Idempotency ensures that if a caller retries a request with the same key,
they receive the same response without re-executing the capability.

Production considerations
-------------------------
- Replace with Redis-backed store using SETNX + TTL
- Set expiry (e.g. 24 hours) to prevent unbounded growth
- Use a distributed lock to prevent concurrent execution of the same key
- Store payloads in a compressed format (msgpack/orjson) to reduce memory

Format of stored keys: ``"{tenant_id}:{idempotency_key}"``
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# TTL is not enforced in the in-memory implementation.
# In production (Redis), use EXPIRE.
_DEFAULT_TTL_SECONDS = 86_400  # 24 hours


class IdempotencyStore:
    """Thread-safe (for asyncio) in-memory idempotency cache."""

    def __init__(self) -> None:
        # Key: "{tenant_id}:{idempotency_key}"
        # Value: {"receipt": dict, "stored_at": str}
        self._store: dict[str, dict[str, Any]] = {}

    def _make_key(self, tenant_id: str, idempotency_key: str) -> str:
        return f"{tenant_id}:{idempotency_key}"

    def get(self, tenant_id: str, idempotency_key: str) -> dict[str, Any] | None:
        """Return the cached receipt for this idempotency key, or None."""
        key = self._make_key(tenant_id, idempotency_key)
        entry = self._store.get(key)
        if entry:
            logger.debug(
                "Idempotency cache hit",
                extra={
                    "tenant_id": tenant_id,
                    "idempotency_key": idempotency_key,
                    "stored_at": entry.get("stored_at"),
                },
            )
        return entry.get("receipt") if entry else None

    def set(self, tenant_id: str, idempotency_key: str, receipt: dict[str, Any]) -> None:
        """Cache the receipt for this idempotency key."""
        key = self._make_key(tenant_id, idempotency_key)
        self._store[key] = {
            "receipt": receipt,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }
        logger.debug(
            "Idempotency entry stored",
            extra={"tenant_id": tenant_id, "idempotency_key": idempotency_key},
        )

    def exists(self, tenant_id: str, idempotency_key: str) -> bool:
        key = self._make_key(tenant_id, idempotency_key)
        return key in self._store

    def __len__(self) -> int:
        return len(self._store)


# Module-level singleton
idempotency_store = IdempotencyStore()
