"""
app.idempotency_store
~~~~~~~~~~~~~~~~~~~~~
Async DB-backed idempotency store.

Ensures that if a caller retries a request with the same key,
they receive the same response without re-executing the capability.

Supports TTL-based expiry via the ``expires_at`` column.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from moat_core.db import IdempotencyCacheRow
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 86_400  # 24 hours


class IdempotencyStore:
    """Async DB-backed idempotency cache."""

    def __init__(self) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError(
                "IdempotencyStore not configured. Call configure() during lifespan."
            )
        return self._session_factory()

    async def get(self, tenant_id: str, idempotency_key: str) -> dict[str, Any] | None:
        """Return the cached receipt for this idempotency key, or None."""
        async with self._session() as session:
            stmt = (
                select(IdempotencyCacheRow)
                .where(IdempotencyCacheRow.tenant_id == tenant_id)
                .where(IdempotencyCacheRow.idempotency_key == idempotency_key)
            )
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()

            if row is None:
                return None

            # Check expiry
            now = datetime.now(UTC)
            if row.expires_at.tzinfo is None:
                # Handle naive datetimes from SQLite
                expires = row.expires_at.replace(tzinfo=UTC)
            else:
                expires = row.expires_at

            if now >= expires:
                await session.delete(row)
                await session.commit()
                return None

            logger.debug(
                "Idempotency cache hit",
                extra={"tenant_id": tenant_id, "idempotency_key": idempotency_key},
            )
            return row.receipt_data

    async def set(
        self,
        tenant_id: str,
        idempotency_key: str,
        receipt: dict[str, Any],
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
    ) -> None:
        """Cache the receipt for this idempotency key with TTL."""
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=ttl_seconds)

        async with self._session() as session:
            # Upsert: delete existing then insert
            stmt = (
                select(IdempotencyCacheRow)
                .where(IdempotencyCacheRow.tenant_id == tenant_id)
                .where(IdempotencyCacheRow.idempotency_key == idempotency_key)
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing:
                await session.delete(existing)

            row = IdempotencyCacheRow(
                tenant_id=tenant_id,
                idempotency_key=idempotency_key,
                receipt_data=receipt,
                stored_at=now,
                expires_at=expires_at,
            )
            session.add(row)
            await session.commit()

            logger.debug(
                "Idempotency entry stored",
                extra={"tenant_id": tenant_id, "idempotency_key": idempotency_key},
            )


# Module-level singleton
idempotency_store = IdempotencyStore()
