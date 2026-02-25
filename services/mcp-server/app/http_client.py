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


# ---------------------------------------------------------------------------
# Scout-workflow helpers
# ---------------------------------------------------------------------------

# Platform API base URLs for bounty discovery
PLATFORM_URLS: dict[str, str] = {
    "algora": "https://console.algora.io/api/bounties",
    "gitcoin": "https://gitcoin.co/api/v0.1/bounties/",
    "polar": "https://api.polar.sh/v1/issues/search",
    "github": "https://api.github.com/search/issues",
}


async def gw_execute_bounty_discover(
    platform: str = "algora",
    query: str = "",
    language: str | None = None,
    max_results: int = 20,
    tenant_id: str = "automaton",
) -> dict[str, Any]:
    """Search bounty platforms via the http.proxy capability."""
    base_url = PLATFORM_URLS.get(platform)
    if not base_url:
        return {
            "error": f"Unknown platform: {platform}",
            "supported": list(PLATFORM_URLS.keys()),
        }

    # Build platform-specific query URL
    if platform == "algora":
        url = f"{base_url}?limit={max_results}"
        if query:
            url = f"{base_url}?q={query}&limit={max_results}"
    elif platform == "github":
        q_parts = ["type:issue", "state:open", "label:bounty"]
        if query:
            q_parts.insert(0, query)
        if language:
            q_parts.append(f"language:{language}")
        url = f"{base_url}?q={'+'.join(q_parts)}&per_page={max_results}"
    elif platform == "gitcoin":
        url = f"{base_url}?is_open=true&limit={max_results}"
        if query:
            url += f"&keyword={query}"
    elif platform == "polar":
        url = f"{base_url}?have_badge=true&limit={max_results}"
        if query:
            url += f"&q={query}"
    else:
        url = base_url

    result = await gw_execute(
        capability_id="http.proxy",
        params={"url": url, "method": "GET"},
        tenant_id=tenant_id,
        scope="execute",
    )
    return {"platform": platform, "query": query, "gateway_receipt": result}


async def gw_execute_gwi_triage(
    url: str,
    tenant_id: str = "automaton",
) -> dict[str, Any]:
    """Triage a GitHub issue via the gwi.triage capability."""
    return await gw_execute(
        capability_id="gwi.triage",
        params={"url": url},
        tenant_id=tenant_id,
        scope="execute",
    )


async def gw_execute_gwi_command(
    url: str,
    command: str = "issue-to-code",
    tenant_id: str = "automaton",
) -> dict[str, Any]:
    """Execute a GWI command (issue-to-code or resolve) via the gateway."""
    cap_id = (
        f"gwi.{command}"
        if command in ("issue-to-code", "resolve")
        else "gwi.issue-to-code"
    )
    return await gw_execute(
        capability_id=cap_id,
        params={"url": url},
        tenant_id=tenant_id,
        scope="execute",
    )
