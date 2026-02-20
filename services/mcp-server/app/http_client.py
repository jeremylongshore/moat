"""
app.http_client
~~~~~~~~~~~~~~~
Shared async HTTP client helpers for calling upstream Moat services.

Each function makes a best-effort call to an upstream service. If the
service is unreachable, a stub response is returned with a ``_stub: true``
field so callers can distinguish real from fallback data.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


async def _get(
    url: str,
    *,
    params: dict[str, str] | None = None,
    stub_response: dict[str, Any],
) -> dict[str, Any]:
    """Perform a GET request, returning ``stub_response`` on any HTTP error."""
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Upstream GET failed", extra={"url": url, "error": str(exc)})
        return {**stub_response, "_stub": True, "_error": str(exc)}


async def _post(
    url: str,
    payload: dict[str, Any],
    *,
    stub_response: dict[str, Any],
) -> dict[str, Any]:
    """Perform a POST request, returning ``stub_response`` on any HTTP error."""
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning("Upstream POST failed", extra={"url": url, "error": str(exc)})
        return {**stub_response, "_stub": True, "_error": str(exc)}


# ---------------------------------------------------------------------------
# Control Plane
# ---------------------------------------------------------------------------


async def cp_list_capabilities(
    provider: str | None = None,
    status: str | None = None,
) -> dict[str, Any]:
    url = f"{settings.CONTROL_PLANE_URL}/capabilities"
    query_params: dict[str, str] = {}
    if provider:
        query_params["provider"] = provider
    if status:
        query_params["status"] = status
    return await _get(
        url,
        params=query_params or None,
        stub_response={
            "items": [],
            "total": 0,
            "_note": "Control plane unreachable - returning empty stub",
        },
    )


async def cp_get_capability(capability_id: str) -> dict[str, Any] | None:
    url = f"{settings.CONTROL_PLANE_URL}/capabilities/{capability_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            return resp.json()
    except httpx.HTTPError as exc:
        logger.warning(
            "Control plane unreachable",
            extra={"capability_id": capability_id, "error": str(exc)},
        )
        return {
            "_stub": True,
            "_error": str(exc),
            "capability_id": capability_id,
            "_note": "Control plane unreachable",
        }


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------


async def gw_execute(
    capability_id: str,
    params: dict[str, Any],
    tenant_id: str,
    idempotency_key: str | None = None,
    scope: str = "execute",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "params": params,
        "tenant_id": tenant_id,
        "scope": scope,
    }
    if idempotency_key:
        payload["idempotency_key"] = idempotency_key

    return await _post(
        f"{settings.GATEWAY_URL}/execute/{capability_id}",
        payload,
        stub_response={
            "receipt_id": "stub-receipt",
            "capability_id": capability_id,
            "tenant_id": tenant_id,
            "status": "stub",
            "result": {},
            "executed_at": "N/A",
            "latency_ms": 0,
            "cached": False,
            "_note": "Gateway unreachable - returning stub receipt",
        },
    )


# ---------------------------------------------------------------------------
# Trust Plane
# ---------------------------------------------------------------------------


async def tp_get_stats(capability_id: str) -> dict[str, Any]:
    url = f"{settings.TRUST_PLANE_URL}/capabilities/{capability_id}/stats"
    return await _get(
        url,
        stub_response={
            "capability_id": capability_id,
            "success_rate_7d": 1.0,
            "p95_latency_ms": 0.0,
            "total_executions_7d": 0,
            "last_checked": None,
            "verified": False,
            "_note": "Trust plane unreachable - returning stub stats",
        },
    )
