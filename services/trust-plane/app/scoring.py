"""
app.scoring
~~~~~~~~~~~
Trust scoring engine for Moat capability reliability.

StatsStore
    Ingests OutcomeEvents and maintains rolling per-capability statistics.
    Computes 7-day success rate and p95 latency from recent events.

should_hide(stats) -> bool
    Returns True if the capability's success rate is below the 80% threshold
    for the trailing 7 days, warranting suppression from marketplace listings.

should_throttle(stats) -> bool
    Returns True if the capability's p95 latency exceeds 10,000 ms, warranting
    automatic request throttling at the gateway.

Data model
----------
Events are stored in memory as a deque bounded by 7 days. In production,
this should be backed by a time-series store (e.g. Redis sorted sets,
TimescaleDB, or BigQuery) to support horizontal scaling.
"""

from __future__ import annotations

import logging
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 7
_WINDOW = timedelta(days=_WINDOW_DAYS)

# Rolling window for 24h hide evaluation
_HIDE_WINDOW = timedelta(hours=24)


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
    success_rate_7d: float           # 0.0 - 1.0
    p95_latency_ms: float            # milliseconds
    total_executions_7d: int
    last_checked: datetime | None
    verified: bool


class StatsStore:
    """In-memory rolling window stats store.

    Maintains a per-capability deque of ``EventRecord`` objects covering
    the trailing 7 days. Expired events are pruned on each :meth:`record`
    call to keep memory bounded.
    """

    def __init__(self) -> None:
        # capability_id -> deque of EventRecord (7-day window)
        self._events: dict[str, deque[EventRecord]] = defaultdict(deque)
        self._last_verified: dict[str, datetime] = {}

    def record(self, event: EventRecord) -> None:
        """Ingest a new outcome event, pruning events older than 7 days."""
        q = self._events[event.capability_id]
        q.append(event)
        self._prune(event.capability_id)
        logger.debug(
            "Event recorded",
            extra={
                "capability_id": event.capability_id,
                "success": event.success,
                "latency_ms": event.latency_ms,
                "window_size": len(q),
            },
        )

    def _prune(self, capability_id: str) -> None:
        """Remove events older than the 7-day rolling window."""
        cutoff = datetime.now(timezone.utc) - _WINDOW
        q = self._events[capability_id]
        while q and q[0].occurred_at < cutoff:
            q.popleft()

    def get_stats(self, capability_id: str) -> CapabilityStats:
        """Compute current reliability stats for ``capability_id``.

        Returns
        -------
        CapabilityStats
            Computed stats. If no events have been recorded, returns zero-
            execution defaults.
        """
        self._prune(capability_id)
        events = list(self._events[capability_id])
        total = len(events)

        if total == 0:
            return CapabilityStats(
                capability_id=capability_id,
                success_rate_7d=1.0,  # Benefit of the doubt with zero data
                p95_latency_ms=0.0,
                total_executions_7d=0,
                last_checked=None,
                verified=False,
            )

        success_count = sum(1 for e in events if e.success)
        success_rate = success_count / total

        latencies = sorted(e.latency_ms for e in events)
        p95_latency = _percentile(latencies, 95)

        # A capability is considered "verified" once it has >= 10 executions
        # with a success rate above the hide threshold.
        verified = total >= 10 and success_rate >= settings.MIN_SUCCESS_RATE_7D

        last_event = max(events, key=lambda e: e.occurred_at)

        return CapabilityStats(
            capability_id=capability_id,
            success_rate_7d=round(success_rate, 4),
            p95_latency_ms=round(p95_latency, 2),
            total_executions_7d=total,
            last_checked=last_event.occurred_at,
            verified=verified,
        )

    def mark_verified(self, capability_id: str) -> None:
        """Manually mark a capability as verified (e.g. after human review)."""
        self._last_verified[capability_id] = datetime.now(timezone.utc)

    def all_capability_ids(self) -> list[str]:
        return list(self._events.keys())


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
    """Return True if the capability should be hidden from marketplace listings.

    Criteria: success rate below MIN_SUCCESS_RATE_7D for the trailing 7 days,
    AND there is enough data to make the determination (>= 5 executions).

    Parameters
    ----------
    stats:
        Pre-computed stats from :meth:`StatsStore.get_stats`.
    """
    if stats.total_executions_7d < 5:
        return False  # Not enough data - do not hide prematurely
    return stats.success_rate_7d < settings.MIN_SUCCESS_RATE_7D


def should_throttle(stats: CapabilityStats) -> bool:
    """Return True if the capability should be throttled at the gateway.

    Criteria: p95 latency exceeds MAX_P95_LATENCY_MS (default 10,000 ms).

    Parameters
    ----------
    stats:
        Pre-computed stats from :meth:`StatsStore.get_stats`.
    """
    if stats.total_executions_7d < 5:
        return False  # Not enough data
    return stats.p95_latency_ms > settings.MAX_P95_LATENCY_MS


# Module-level singleton
stats_store = StatsStore()
