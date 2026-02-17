"""
app.routers.events
~~~~~~~~~~~~~~~~~~
Outcome event ingestion endpoint.

The gateway POSTs an OutcomeEvent here after each capability execution.
Events drive the rolling reliability statistics in the StatsStore.

This endpoint is an internal service-to-service API. It is not exposed
to end users or MCP clients.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from app.scoring import EventRecord, stats_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------

class OutcomeEventRequest(BaseModel):
    """Outcome event payload sent by the gateway after each execution."""

    event_id: str = Field(..., description="Unique event ID (UUID v4)")
    capability_id: str = Field(..., description="Capability that was executed")
    tenant_id: str = Field(default="", description="Tenant that triggered execution")
    receipt_id: str = Field(default="", description="Receipt ID from the gateway")
    execution_status: str = Field(
        ...,
        description="Execution result: 'success' or 'failure'",
    )
    latency_ms: float = Field(
        default=0.0,
        ge=0,
        description="End-to-end execution latency in milliseconds",
    )
    occurred_at: str | None = Field(
        default=None,
        description="ISO 8601 timestamp when the execution occurred (defaults to now)",
    )


class EventIngestResponse(BaseModel):
    event_id: str
    capability_id: str
    accepted: bool
    message: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=EventIngestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest an outcome event",
)
async def ingest_event(body: OutcomeEventRequest) -> EventIngestResponse:
    """Accept an execution outcome event from the gateway and update rolling stats.

    **Caller:** ``moat-gateway`` (internal service-to-service call)

    Each event increments the 7-day rolling window for the capability's
    success rate and latency percentiles. Events older than 7 days are
    automatically pruned.
    """
    occurred_at: datetime
    if body.occurred_at:
        try:
            occurred_at = datetime.fromisoformat(body.occurred_at)
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)
        except ValueError:
            logger.warning(
                "Invalid occurred_at format, using current time",
                extra={"event_id": body.event_id, "occurred_at": body.occurred_at},
            )
            occurred_at = datetime.now(timezone.utc)
    else:
        occurred_at = datetime.now(timezone.utc)

    success = body.execution_status.lower() in ("success", "succeeded", "ok")

    event = EventRecord(
        capability_id=body.capability_id,
        success=success,
        latency_ms=body.latency_ms,
        occurred_at=occurred_at,
        tenant_id=body.tenant_id,
        receipt_id=body.receipt_id,
    )

    stats_store.record(event)

    logger.info(
        "Outcome event ingested",
        extra={
            "event_id": body.event_id,
            "capability_id": body.capability_id,
            "success": success,
            "latency_ms": body.latency_ms,
        },
    )

    return EventIngestResponse(
        event_id=body.event_id,
        capability_id=body.capability_id,
        accepted=True,
        message="Event accepted and stats updated.",
    )


@router.get(
    "/count",
    summary="Return total ingested event count across all capabilities",
    tags=["events"],
)
async def event_count() -> dict[str, int]:
    """Return the total number of events currently in the 7-day rolling window."""
    total = sum(
        stats.total_executions_7d
        for cid in stats_store.all_capability_ids()
        for stats in [stats_store.get_stats(cid)]
    )
    return {"total_events_in_window": total}
