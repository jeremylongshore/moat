"""
app.routers.discovery
~~~~~~~~~~~~~~~~~~~~~
A2A v0.3.0 discovery endpoints for the Moat MCP Server.

Implements:
- ``GET /.well-known/agent.json`` — standard A2A AgentCard discovery
- ``GET /agents`` — list known agents (this server + upstream services)
- ``GET /agents/{agent_name}`` — get a specific agent's card
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["discovery"])

# ---------------------------------------------------------------------------
# AgentCard definitions for Moat services
# ---------------------------------------------------------------------------

_MCP_SERVER_CARD: dict[str, Any] = {
    "name": "moat-mcp-server",
    "description": (
        "Agent-facing tool surface for the Moat "
        "policy-enforced execution platform. Exposes "
        "capability discovery, execution, trust "
        "scoring, and bounty workflow tools."
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
        "credentials": "JWT via Authorization header or X-Tenant-ID when auth disabled",
    },
    "default_input_modes": ["application/json"],
    "default_output_modes": ["application/json"],
    "skills": [
        {
            "id": "capabilities.list",
            "name": "List Capabilities",
            "description": "List capabilities from the registry with optional filters.",
            "tags": ["capabilities", "registry", "discovery"],
            "examples": [
                "List all active capabilities",
                "Show capabilities from provider openai",
            ],
        },
        {
            "id": "capabilities.search",
            "name": "Search Capabilities",
            "description": "Search capabilities by name, description, or tags.",
            "tags": ["capabilities", "search"],
            "examples": [
                "Find image generation capabilities",
                "Search for web search tools",
            ],
        },
        {
            "id": "capabilities.execute",
            "name": "Execute Capability",
            "description": "Execute a capability through the policy-enforced gateway.",
            "tags": ["capabilities", "execute", "gateway"],
            "examples": ["Execute capability cap-abc123 with params"],
        },
        {
            "id": "capabilities.stats",
            "name": "Capability Stats",
            "description": "Get 7-day reliability stats and trust signals.",
            "tags": ["capabilities", "trust", "stats"],
            "examples": ["Get reliability stats for cap-abc123"],
        },
        {
            "id": "bounty.discover",
            "name": "Discover Bounties",
            "description": "Search bounty platforms for funded open issues.",
            "tags": ["bounty", "discovery", "algora", "gitcoin"],
            "examples": [
                "Find Rust bounties on Algora",
                "Search GitHub bounties for TypeScript",
            ],
        },
        {
            "id": "bounty.triage",
            "name": "Triage Issue",
            "description": "Triage a GitHub issue via GWI for complexity and approach.",
            "tags": ["bounty", "triage", "gwi"],
            "examples": ["Triage https://github.com/org/repo/issues/42"],
        },
        {
            "id": "bounty.execute",
            "name": "Execute Fix",
            "description": "Execute a fix for a GitHub issue via GWI.",
            "tags": ["bounty", "execute", "gwi"],
            "examples": ["Fix https://github.com/org/repo/issues/42"],
        },
        {
            "id": "bounty.status",
            "name": "Bounty Status",
            "description": (
                "Composite status check: triage + trust stats + IRSB receipt."
            ),
            "tags": ["bounty", "status"],
            "examples": ["Check status of https://github.com/org/repo/issues/42"],
        },
        {
            "id": "agents.discover",
            "name": "Discover Agents",
            "description": "List all known agents in the Moat ecosystem.",
            "tags": ["agents", "discovery", "a2a"],
            "examples": [
                "List all Moat agents",
                "Find agents with execution capabilities",
            ],
        },
        {
            "id": "agents.card",
            "name": "Agent Card",
            "description": "Get the A2A AgentCard for a specific agent.",
            "tags": ["agents", "a2a", "card"],
            "examples": ["Get agent card for moat-gateway"],
        },
    ],
}

_GATEWAY_CARD: dict[str, Any] = {
    "name": "moat-gateway",
    "description": (
        "Execution choke-point: policy evaluation, idempotency, adapter dispatch, "
        "receipt generation, and trust-plane event emission."
    ),
    "url": settings.GATEWAY_URL,
    "provider": {"organization": "Moat"},
    "version": "0.1.0",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "state_transition_history": False,
    },
    "skills": [
        {
            "id": "execute",
            "name": "Execute Pipeline",
            "description": "Policy-enforced capability execution with receipts.",
            "tags": ["execute", "policy", "receipts"],
        },
    ],
}

_CONTROL_PLANE_CARD: dict[str, Any] = {
    "name": "moat-control-plane",
    "description": "Capability registry, tenant connections, and vault abstraction.",
    "url": settings.CONTROL_PLANE_URL,
    "provider": {"organization": "Moat"},
    "version": "0.1.0",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "state_transition_history": False,
    },
    "skills": [
        {
            "id": "registry",
            "name": "Capability Registry",
            "description": "CRUD for capability manifests.",
            "tags": ["capabilities", "registry"],
        },
    ],
}

_TRUST_PLANE_CARD: dict[str, Any] = {
    "name": "moat-trust-plane",
    "description": "Reliability scoring, outcome event ingestion, and SLO tracking.",
    "url": settings.TRUST_PLANE_URL,
    "provider": {"organization": "Moat"},
    "version": "0.1.0",
    "capabilities": {
        "streaming": False,
        "push_notifications": False,
        "state_transition_history": False,
    },
    "skills": [
        {
            "id": "scoring",
            "name": "Trust Scoring",
            "description": "Rolling 7-day reliability scoring for capabilities.",
            "tags": ["trust", "scoring", "stats"],
        },
    ],
}

# Agent registry — keyed by name for lookup
AGENT_CARDS: dict[str, dict[str, Any]] = {
    "moat-mcp-server": _MCP_SERVER_CARD,
    "moat-gateway": _GATEWAY_CARD,
    "moat-control-plane": _CONTROL_PLANE_CARD,
    "moat-trust-plane": _TRUST_PLANE_CARD,
}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get(
    "/.well-known/agent.json",
    summary="A2A AgentCard discovery",
    response_model=None,
)
async def well_known_agent_card() -> dict[str, Any]:
    """Return the A2A v0.3.0 AgentCard for this MCP server.

    Standard endpoint per the Agent-to-Agent protocol specification.
    Other agents fetch this to discover skills and capabilities.
    """
    return _MCP_SERVER_CARD


@router.get(
    "/agents",
    summary="List all known agents",
    response_model=None,
)
async def list_agents(
    skill_tag: str | None = None,
) -> dict[str, Any]:
    """List all known agents in the Moat ecosystem.

    Optionally filter by skill tag (e.g. ``?skill_tag=execute``).
    """
    agents = list(AGENT_CARDS.values())

    if skill_tag:
        tag_lower = skill_tag.lower()
        agents = [
            agent
            for agent in agents
            if any(
                tag_lower in tag
                for skill in agent.get("skills", [])
                for tag in skill.get("tags", [])
            )
        ]

    return {"agents": agents, "total": len(agents)}


@router.get(
    "/agents/{agent_name}",
    summary="Get a specific agent's card",
    response_model=None,
)
async def get_agent_card(agent_name: str) -> dict[str, Any]:
    """Return the AgentCard for a specific agent by name."""
    card = AGENT_CARDS.get(agent_name)
    if card is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Agent '{agent_name}' not found. "
                f"Known agents: {list(AGENT_CARDS.keys())}"
            ),
        )
    return card
