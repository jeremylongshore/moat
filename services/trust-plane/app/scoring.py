"""
app.scoring
~~~~~~~~~~~
Trust scoring engine for Moat capability reliability.

Persists OutcomeEvents to the database and computes rolling 7-day
statistics using SQL queries with Python-side aggregation.

should_hide(stats) -> bool
    Returns True if the capability's success rate is below the 80% threshold
    for the trailing 7 days, warranting suppression from marketplace listings.

should_throttle(stats) -> bool
    Returns True if the capability's p95 latency exceeds 10,000 ms, warranting
    automatic request throttling at the gateway.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from moat_core.db import OutcomeEventRow
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 7
_WINDOW = timedelta(days=_WINDOW_DAYS)


@dataclass
class EventRecord:
    """Single outcome event recorded for a capability."""

    capability_id: str
    success: bool
    latency_ms: float
    occurred_at: datetime
    tenant_id: str = ""
    receipt_id: str = ""


@dataclass
class CapabilityStats:
    """Computed reliability stats for a single capability."""

    capability_id: str
    success_rate_7d: float  # 0.0 - 1.0
    p95_latency_ms: float  # milliseconds
    total_executions_7d: int
    last_checked: datetime | None
    verified: bool


class StatsStore:
    """DB-backed rolling window stats store.

    Persists outcome events and computes 7-day stats by querying
    the database and aggregating in Python (works with both
    Postgres and SQLite).
    """

    def __init__(self) -> None:
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    def configure(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def _session(self) -> AsyncSession:
        if self._session_factory is None:
            raise RuntimeError(
                "StatsStore not configured. Call configure() during lifespan."
            )
        return self._session_factory()

    async def record(self, event: EventRecord, event_id: str = "") -> None:
        """Persist a new outcome event."""
        from uuid import uuid4

        async with self._session() as session:
            row = OutcomeEventRow(
                event_id=event_id or str(uuid4()),
                capability_id=event.capability_id,
                tenant_id=event.tenant_id,
                receipt_id=event.receipt_id,
                success=event.success,
                latency_ms=event.latency_ms,
                occurred_at=event.occurred_at,
            )
            session.add(row)
            await session.commit()

        logger.debug(
            "Event recorded",
            extra={
                "capability_id": event.capability_id,
                "success": event.success,
                "latency_ms": event.latency_ms,
            },
        )

    async def get_stats(self, capability_id: str) -> CapabilityStats:
        """Compute current reliability stats for ``capability_id``.

        Fetches events from the last 7 days and computes stats in Python.
        """
        cutoff = datetime.now(UTC) - _WINDOW

        async with self._session() as session:
            stmt = (
                select(OutcomeEventRow)
                .where(OutcomeEventRow.capability_id == capability_id)
                .where(OutcomeEventRow.occurred_at >= cutoff)
                .order_by(OutcomeEventRow.occurred_at)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

        total = len(rows)

        if total == 0:
            return CapabilityStats(
                capability_id=capability_id,
                success_rate_7d=1.0,
                p95_latency_ms=0.0,
                total_executions_7d=0,
                last_checked=None,
                verified=False,
            )

        success_count = sum(1 for r in rows if r.success)
        success_rate = success_count / total

        latencies = sorted(r.latency_ms for r in rows)
        p95_latency = _percentile(latencies, 95)

        verified = total >= 10 and success_rate >= settings.MIN_SUCCESS_RATE_7D

        last_event = max(rows, key=lambda r: r.occurred_at)

        return CapabilityStats(
            capability_id=capability_id,
            success_rate_7d=round(success_rate, 4),
            p95_latency_ms=round(p95_latency, 2),
            total_executions_7d=total,
            last_checked=last_event.occurred_at,
            verified=verified,
        )

    async def all_capability_ids(self) -> list[str]:
        """Return all capability IDs that have recorded events."""
        async with self._session() as session:
            stmt = select(distinct(OutcomeEventRow.capability_id))
            result = await session.execute(stmt)
            return [row[0] for row in result.all()]


def _percentile(sorted_values: list[float], pct: int) -> float:
    """Compute the ``pct``-th percentile of a sorted list using linear interpolation."""
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (len(sorted_values) - 1) * pct / 100
    lo = int(k)
    hi = lo + 1
    if hi >= len(sorted_values):
        return sorted_values[-1]
    frac = k - lo
    return sorted_values[lo] + frac * (sorted_values[hi] - sorted_values[lo])


def should_hide(stats: CapabilityStats) -> bool:
    """Return True if the capability should be hidden from marketplace listings."""
    if stats.total_executions_7d < 5:
        return False
    return stats.success_rate_7d < settings.MIN_SUCCESS_RATE_7D


def should_throttle(stats: CapabilityStats) -> bool:
    """Return True if the capability should be throttled at the gateway."""
    if stats.total_executions_7d < 5:
        return False
    return stats.p95_latency_ms > settings.MAX_P95_LATENCY_MS


# Module-level singleton
stats_store = StatsStore()
