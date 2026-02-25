"""
moat_cli.client
~~~~~~~~~~~~~~~
Synchronous httpx client for calling Moat services.

All methods are sync (blocking) since the CLI is a short-lived process
and async adds complexity for no benefit here.
"""

from __future__ import annotations

from typing import Any

import httpx


class MoatClient:
    """HTTP client for communicating with Moat services."""

    def __init__(
        self,
        gateway_url: str = "http://localhost:8002",
        control_plane_url: str = "http://localhost:8001",
        trust_plane_url: str = "http://localhost:8003",
        tenant_id: str = "automaton",
        timeout: float = 30.0,
    ) -> None:
        self.gateway_url = gateway_url.rstrip("/")
        self.control_plane_url = control_plane_url.rstrip("/")
        self.trust_plane_url = trust_plane_url.rstrip("/")
        self.tenant_id = tenant_id
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    # ── Control Plane ──────────────────────────────────────────────────

    def list_capabilities(
        self,
        provider: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """List capabilities from the control plane."""
        params: dict[str, str] = {}
        if provider:
            params["provider"] = provider
        if status:
            params["status"] = status
        resp = self._client.get(f"{self.control_plane_url}/capabilities", params=params or None)
        resp.raise_for_status()
        return resp.json()

    def search_capabilities(self, query: str) -> dict[str, Any]:
        """Search capabilities by substring match."""
        data = self.list_capabilities()
        items = data.get("items", [])
        q = query.lower()
        matches = [
            item for item in items if q in item.get("name", "").lower() or q in item.get("description", "").lower()
        ]
        return {"items": matches, "total": len(matches), "query": query}

    def register_capability(
        self,
        name: str,
        provider: str,
        version: str = "0.0.1",
        description: str = "",
        method: str = "POST /execute",
        risk_class: str = "low",
    ) -> dict[str, Any]:
        """Register a new capability with the control plane."""
        payload = {
            "name": name,
            "provider": provider,
            "version": version,
            "description": description or f"Capability: {name}",
            "method": method,
            "risk_class": risk_class,
        }
        resp = self._client.post(f"{self.control_plane_url}/capabilities", json=payload)
        resp.raise_for_status()
        return resp.json()

    # ── Gateway ────────────────────────────────────────────────────────

    def execute(
        self,
        capability_id: str,
        params: dict[str, Any] | None = None,
        scope: str = "execute",
        idempotency_key: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a capability through the gateway pipeline."""
        payload: dict[str, Any] = {
            "params": params or {},
            "tenant_id": tenant_id or self.tenant_id,
            "scope": scope,
        }
        if idempotency_key:
            payload["idempotency_key"] = idempotency_key

        headers: dict[str, str] = {}
        headers["X-Tenant-ID"] = tenant_id or self.tenant_id

        resp = self._client.post(
            f"{self.gateway_url}/execute/{capability_id}",
            json=payload,
            headers=headers,
        )
        resp.raise_for_status()
        return resp.json()

    # ── Trust Plane ────────────────────────────────────────────────────

    def get_stats(self, capability_id: str) -> dict[str, Any]:
        """Get reliability stats from the trust plane."""
        resp = self._client.get(f"{self.trust_plane_url}/capabilities/{capability_id}/stats")
        resp.raise_for_status()
        return resp.json()
