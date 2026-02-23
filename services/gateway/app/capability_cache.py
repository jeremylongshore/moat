"""
app.capability_cache
~~~~~~~~~~~~~~~~~~~~
Local cache for capability metadata fetched from the control plane.

The gateway fetches capability details from the control plane on the first
request for a given capability_id and caches the result in memory for
subsequent requests. This avoids a round-trip per execution.

Production upgrade path
-----------------------
- Replace with Redis cache (TTL-based invalidation)
- Subscribe to control-plane capability change events to invalidate on status updates
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Cache TTL - after this time, capability data is re-fetched from control plane
_CACHE_TTL = timedelta(minutes=5)


class CapabilityCache:
    """Simple in-process TTL cache for capability metadata."""

    def __init__(self) -> None:
        self._cache: dict[str, dict[str, Any]] = {}
        self._fetched_at: dict[str, datetime] = {}

    def _is_expired(self, capability_id: str) -> bool:
        fetched = self._fetched_at.get(capability_id)
        if fetched is None:
            return True
        return datetime.now(UTC) - fetched > _CACHE_TTL

    def get(self, capability_id: str) -> dict[str, Any] | None:
        if self._is_expired(capability_id):
            return None
        return self._cache.get(capability_id)

    def set(self, capability_id: str, capability: dict[str, Any]) -> None:
        self._cache[capability_id] = capability
        self._fetched_at[capability_id] = datetime.now(UTC)

    def invalidate(self, capability_id: str) -> None:
        self._cache.pop(capability_id, None)
        self._fetched_at.pop(capability_id, None)


# Module-level singleton
_cache = CapabilityCache()


async def get_capability(capability_id: str) -> dict[str, Any] | None:
    """Fetch capability metadata, using the local cache when possible.

    Returns
    -------
    dict or None
        Capability data dict, or None if the capability was not found.

    Notes
    -----
    Falls back to a synthetic stub capability if the control plane is
    unreachable. This prevents cascading failures in development.
    """
    cached = _cache.get(capability_id)
    if cached is not None:
        logger.debug("Capability cache hit", extra={"capability_id": capability_id})
        return cached

    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT) as client:
            # Try by ID first (UUID)
            response = await client.get(
                f"{settings.CONTROL_PLANE_URL}/capabilities/{capability_id}"
            )
            if response.status_code == 404:
                # Fall back to name-based search (e.g. "openai.inference")
                list_resp = await client.get(
                    f"{settings.CONTROL_PLANE_URL}/capabilities"
                )
                if list_resp.status_code == 200:
                    data = list_resp.json()
                    # Control plane returns {"items": [...], "total": N}
                    items = data.get("items", []) if isinstance(data, dict) else data
                    for cap in items:
                        if isinstance(cap, dict) and cap.get("name") == capability_id:
                            _cache.set(capability_id, cap)
                            logger.debug(
                                "Capability found by name",
                                extra={
                                    "capability_id": capability_id,
                                    "name": cap.get("name"),
                                },
                            )
                            return cap
                return None
            response.raise_for_status()
            capability = response.json()
            _cache.set(capability_id, capability)
            logger.debug(
                "Capability fetched from control plane",
                extra={"capability_id": capability_id},
            )
            return capability
    except httpx.HTTPError as exc:
        logger.warning(
            "Control plane unreachable, using stub capability for development",
            extra={"capability_id": capability_id, "error": str(exc)},
        )
        # Return a synthetic stub so the gateway pipeline can still run
        stub = {
            "capability_id": capability_id,
            "name": f"stub:{capability_id}",
            "description": "Stub capability (control plane unreachable)",
            "provider": "stub",
            "version": "0.0.0",
            "input_schema": {},
            "output_schema": {},
            "status": "active",
            "tags": [],
            "created_at": datetime.now(UTC).isoformat(),
            "_stub": True,
        }
        _cache.set(capability_id, stub)
        return stub
