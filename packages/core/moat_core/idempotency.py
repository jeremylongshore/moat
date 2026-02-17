"""
moat_core.idempotency
~~~~~~~~~~~~~~~~~~~~~
Idempotency key generation and storage contracts.

An idempotency key is a stable, deterministic string derived from the
*logical identity* of a request.  If a caller retries an operation with
the same key, the system returns the previously recorded Receipt without
re-executing the capability.

Design
------
* ``generate_idempotency_key`` is a pure function - same inputs always
  produce the same key.  Callers may also supply their own keys.
* ``IdempotencyStore`` is a ``Protocol`` (structural subtyping) rather
  than an ABC, so any object with the right async interface satisfies
  it without explicit inheritance.
* ``InMemoryIdempotencyStore`` is a thread-safe (via asyncio coroutines)
  in-memory store suitable for local development and testing.  It
  respects the TTL contract via ``expiry_at`` timestamps.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable

from moat_core.models import Receipt


# ---------------------------------------------------------------------------
# Key generation
# ---------------------------------------------------------------------------


def generate_idempotency_key(
    capability_id: str,
    tenant_id: str,
    input_data: dict,
) -> str:
    """Return a deterministic idempotency key for the given request triple.

    The key is derived from the SHA-256 digest of a JSON-encoded
    ``(capability_id, tenant_id, input_data)`` tuple.  Key insertion
    order in *input_data* does not affect the result (``sort_keys=True``).

    Args:
        capability_id: The capability being invoked.
        tenant_id: The tenant making the request.
        input_data: The raw (pre-redaction) input payload.

    Returns:
        A 64-character lowercase hex string suitable for use as a cache key.

    Example::

        >>> k1 = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        >>> k2 = generate_idempotency_key("cap_v1", "t1", {"q": "hello"})
        >>> k1 == k2
        True
        >>> k1 == generate_idempotency_key("cap_v1", "t1", {"q": "world"})
        False
    """
    payload = json.dumps(
        {
            "capability_id": capability_id,
            "tenant_id": tenant_id,
            "input_data": input_data,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Store protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class IdempotencyStore(Protocol):
    """Async key-value store mapping idempotency keys to Receipts.

    Implementers must honour the ``ttl_seconds`` contract: a stored
    Receipt must not be returned after its TTL has elapsed.

    Any class that provides ``get`` and ``set`` with matching signatures
    satisfies this Protocol without explicit inheritance.
    """

    async def get(self, key: str) -> Receipt | None:
        """Return the Receipt for *key*, or ``None`` if absent / expired.

        Args:
            key: Idempotency key (e.g. from :func:`generate_idempotency_key`).

        Returns:
            The previously stored :class:`~moat_core.models.Receipt`, or
            ``None`` if the key is not found or has expired.
        """
        ...

    async def set(
        self,
        key: str,
        receipt: Receipt,
        ttl_seconds: int = 86_400,
    ) -> None:
        """Persist *receipt* under *key* for *ttl_seconds*.

        Implementations should silently overwrite an existing entry with
        the same key (idempotent store).  Expiry behaviour is mandatory:
        after ``ttl_seconds`` the entry must no longer be returned by
        :meth:`get`.

        Args:
            key: Idempotency key to store under.
            receipt: The Receipt produced by the capability invocation.
            ttl_seconds: Time-to-live in seconds (default 24 hours).
        """
        ...


# ---------------------------------------------------------------------------
# In-memory implementation
# ---------------------------------------------------------------------------


class _Entry:
    """Internal container holding a Receipt and its expiry timestamp."""

    __slots__ = ("receipt", "expiry_at")

    def __init__(self, receipt: Receipt, expiry_at: datetime) -> None:
        self.receipt = receipt
        self.expiry_at = expiry_at


class InMemoryIdempotencyStore:
    """Thread-safe (asyncio) in-memory :class:`IdempotencyStore`.

    Suitable for local development, unit tests, and single-process
    deployments.  Not suitable for multi-process or distributed use.

    The store performs lazy expiry: expired entries are evicted when
    :meth:`get` is called, not on a background timer.

    Example::

        store = InMemoryIdempotencyStore()
        await store.set("my-key", receipt, ttl_seconds=300)
        cached = await store.get("my-key")
        assert cached == receipt
    """

    def __init__(self) -> None:
        # Using a plain dict guarded by an asyncio.Lock for coroutine safety.
        self._store: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Receipt | None:
        """Return the stored Receipt, or ``None`` if absent or expired.

        Expired entries are evicted as a side-effect of this call.
        """
        async with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            now = datetime.now(tz=timezone.utc)
            if now >= entry.expiry_at:
                del self._store[key]
                return None
            return entry.receipt

    async def set(
        self,
        key: str,
        receipt: Receipt,
        ttl_seconds: int = 86_400,
    ) -> None:
        """Store *receipt* under *key*, expiring after *ttl_seconds*."""
        expiry_at = datetime.now(tz=timezone.utc) + timedelta(seconds=ttl_seconds)
        async with self._lock:
            self._store[key] = _Entry(receipt=receipt, expiry_at=expiry_at)

    async def clear(self) -> None:
        """Remove all entries.  Useful for test isolation."""
        async with self._lock:
            self._store.clear()

    @property
    def size(self) -> int:
        """Return the current number of (possibly expired) entries."""
        return len(self._store)
