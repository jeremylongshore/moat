"""
app.routers.stats
~~~~~~~~~~~~~~~~~
Reliability statistics endpoints for the trust plane.

Returns rolling 7-day success rates, p95 latency, and trust signals
(hide / throttle recommendations) for any capability.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.scoring import CapabilityStats, should_hide, should_throttle, stats_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/capabilities", tags=["stats"])


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class StatsResponse(BaseModel):
    """Reliability statistics for a single capability."""

    capability_id: str
    success_rate_7d: float
    p95_latency_ms: float
    total_executions_7d: int
    last_checked: str | None  # ISO 8601 or null
    verified: bool

    # Trust signals
    should_hide: bool = False
    should_throttle: bool = False


class AllStatsResponse(BaseModel):
    items: list[StatsResponse]
    total: int


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/{capability_id}/stats",
    response_model=StatsResponse,
    summary="Get reliability stats for a capability",
)
async def get_capability_stats(capability_id: str) -> StatsResponse:
    """Return rolling 7-day reliability statistics for ``capability_id``.

    **Fields:**

    - ``success_rate_7d``: Fraction of successful executions in the trailing
      7 days. Range ``[0.0, 1.0]``.
    - ``p95_latency_ms``: 95th-percentile execution latency in milliseconds.
    - ``total_executions_7d``: Total execution count in the 7-day window.
    - ``last_checked``: ISO 8601 timestamp of the most recent recorded event,
      or ``null`` if no events have been recorded.
    - ``verified``: ``true`` once >= 10 executions with >= 80% success rate.
    - ``should_hide``: Marketplace listing suppression recommendation.
    - ``should_throttle``: Gateway throttling recommendation.
    """
    stats: CapabilityStats = stats_store.get_stats(capability_id)
    logger.debug(
        "Stats retrieved",
        extra={
            "capability_id": capability_id,
            "success_rate_7d": stats.success_rate_7d,
            "p95_latency_ms": stats.p95_latency_ms,
            "total_executions_7d": stats.total_executions_7d,
        },
    )
    return StatsResponse(
        capability_id=stats.capability_id,
        success_rate_7d=stats.success_rate_7d,
        p95_latency_ms=stats.p95_latency_ms,
        total_executions_7d=stats.total_executions_7d,
        last_checked=stats.last_checked.isoformat() if stats.last_checked else None,
        verified=stats.verified,
        should_hide=should_hide(stats),
        should_throttle=should_throttle(stats),
    )


@router.get(
    "",
    response_model=AllStatsResponse,
    summary="List stats for all tracked capabilities",
)
async def list_all_stats() -> AllStatsResponse:
    """Return stats for every capability that has recorded at least one event."""
    items: list[StatsResponse] = []
    for capability_id in stats_store.all_capability_ids():
        stats = stats_store.get_stats(capability_id)
        items.append(
            StatsResponse(
                capability_id=stats.capability_id,
                success_rate_7d=stats.success_rate_7d,
                p95_latency_ms=stats.p95_latency_ms,
                total_executions_7d=stats.total_executions_7d,
                last_checked=stats.last_checked.isoformat() if stats.last_checked else None,
                verified=stats.verified,
                should_hide=should_hide(stats),
                should_throttle=should_throttle(stats),
            )
        )
    return AllStatsResponse(items=items, total=len(items))
