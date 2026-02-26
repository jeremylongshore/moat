"""
app.routers.discovery
~~~~~~~~~~~~~~~~~~~~~
A2A v0.3.0 discovery and ERC-8004 metadata endpoints for the gateway.

Implements:
- ``GET /.well-known/agent.json`` — A2A AgentCard for the gateway
- ``GET /.well-known/agents/{agent_name}.json`` — ERC-8004 metadata per agent
- ``GET /agents/erc8004/{agent_id}/metadata`` — ERC-8004 metadata by on-chain ID
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.config import settings
from app.erc8004.metadata import build_agent_metadata

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])


# ---------------------------------------------------------------------------
# Gateway AgentCard (A2A v0.3.0)
# ---------------------------------------------------------------------------

_GATEWAY_AGENT_CARD: dict[str, Any] = {
    "name": "moat-gateway",
    "description": (
        "Policy-enforced execution gateway for AI agent capabilities. "
        "Routes through policy evaluation, idempotency, adapter dispatch, "
        "receipt generation, and trust-plane event emission."
    ),
    "url": f"http://{settings.HOST}:{settings.PORT}",
    "provider": {"organization": "Moat"},
    "version": "0.1.0",
    "documentation_url": "/docs",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "state_transition_history": False,
    },
    "authentication": {
        "schemes": ["bearer"],
        "credentials": (
            "JWT via Authorization header or X-Tenant-ID when auth disabled"
        ),
    },
    "default_input_modes": ["application/json"],
    "default_output_modes": ["application/json"],
    "skills": [
        {
            "id": "execute",
            "name": "Execute Pipeline",
            "description": (
                "Policy-enforced capability execution with receipts and trust scoring."
            ),
            "tags": ["execute", "policy", "receipts"],
            "examples": [
                "Execute capability via POST /execute/{capability_id}",
            ],
        },
        {
            "id": "intents.inbound",
            "name": "Inbound Intent Bridge",
            "description": (
                "Receive on-chain intents from IRSB indexer "
                "and route through execution pipeline."
            ),
            "tags": ["web3", "intents", "bridge"],
            "examples": [
                "POST /intents/inbound with intent event payload",
            ],
        },
    ],
}


@router.get(
    "/.well-known/agent.json",
    summary="A2A AgentCard discovery",
    response_model=None,
)
async def well_known_agent_card() -> dict[str, Any]:
    """Return the A2A v0.3.0 AgentCard for this gateway."""
    return _GATEWAY_AGENT_CARD


# ---------------------------------------------------------------------------
# ERC-8004 metadata endpoints
# ---------------------------------------------------------------------------


async def _get_agent_from_control_plane(
    agent_name: str | None = None,
    erc8004_agent_id: int | None = None,
) -> dict[str, Any] | None:
    """Fetch agent data from the control-plane API.

    Tries the local control-plane HTTP API. Returns the agent dict
    or None if not found/unreachable.
    """
    import httpx

    base_url = settings.CONTROL_PLANE_URL

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if agent_name:
                resp = await client.get(f"{base_url}/agents")
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    for agent in items:
                        if agent.get("name") == agent_name:
                            return agent

            if erc8004_agent_id is not None:
                resp = await client.get(f"{base_url}/agents")
                if resp.status_code == 200:
                    items = resp.json().get("items", [])
                    for agent in items:
                        if agent.get("erc8004_agent_id") == erc8004_agent_id:
                            return agent
    except Exception as exc:
        logger.warning(
            "Failed to fetch agent from control-plane",
            extra={
                "agent_name": agent_name,
                "erc8004_agent_id": erc8004_agent_id,
                "error": str(exc),
            },
        )

    return None


@router.get(
    "/.well-known/agents/{agent_name}.json",
    summary="ERC-8004 agent metadata",
    response_model=None,
)
async def well_known_agent_metadata(agent_name: str) -> dict[str, Any]:
    """Serve ERC-8004 registration metadata for a named agent.

    This is the JSON document that an on-chain agentURI points to.
    Fetches the agent from the control-plane registry and builds
    ERC-8004 compliant metadata.
    """
    agent = await _get_agent_from_control_plane(agent_name=agent_name)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent '{agent_name}' not found in registry",
        )

    return build_agent_metadata(agent)


@router.get(
    "/agents/erc8004/{agent_id}/metadata",
    summary="ERC-8004 metadata by on-chain ID",
    response_model=None,
)
async def erc8004_agent_metadata(agent_id: int) -> dict[str, Any]:
    """Serve ERC-8004 metadata for an agent by its on-chain agent ID.

    Looks up the agent in the control-plane registry by its
    erc8004_agent_id field and builds the registration JSON.
    """
    agent = await _get_agent_from_control_plane(erc8004_agent_id=agent_id)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No agent found with on-chain ID {agent_id}",
        )

    return build_agent_metadata(agent)
