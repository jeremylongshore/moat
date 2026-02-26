"""
app.routers.tools
~~~~~~~~~~~~~~~~~
MCP-style tool endpoints for AI agent integration.

These endpoints implement the Model Context Protocol (MCP) tool calling
contract as REST endpoints. They can be swapped to a full MCP SDK transport
(stdio, SSE, WebSocket) without changing the business logic.

Tool Naming Convention
----------------------
Tools use dot-notation names mirroring the MCP convention:
``capabilities.list``, ``capabilities.search``, ``capabilities.execute``,
``capabilities.stats``.

Response Format
---------------
All tool endpoints return a standard envelope::

    {
        "tool": "<tool_name>",
        "result": { ... },
        "request_id": "<uuid>"
    }

Error responses include an ``error`` field instead of (or alongside) ``result``.

Stub Behaviour
--------------
When an upstream service (control plane, gateway, trust plane) is not
running, each tool returns a stub response with ``_stub: true`` and a
``_note`` explaining the situation. This allows the MCP server to start
and respond independently of the other services.
"""

from __future__ import annotations

import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from moat_core.auth import get_current_tenant
from pydantic import BaseModel, Field

from app.http_client import (
    cp_list_capabilities,
    gw_execute,
    gw_execute_bounty_discover,
    gw_execute_gwi_command,
    gw_execute_gwi_triage,
    tp_get_stats,
)
from app.routers.discovery import AGENT_CARDS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


# ---------------------------------------------------------------------------
# Shared response envelope
# ---------------------------------------------------------------------------


class ToolResponse(BaseModel):
    """Standard MCP tool response envelope."""

    tool: str
    result: dict[str, Any]
    request_id: str


def _response(tool: str, result: dict[str, Any], request: Request) -> ToolResponse:
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return ToolResponse(tool=tool, result=result, request_id=request_id)


# ---------------------------------------------------------------------------
# capabilities.list
# ---------------------------------------------------------------------------


class ListFilter(BaseModel):
    provider: str | None = None
    status: str | None = None
    verified: bool | None = None


class CapabilitiesListRequest(BaseModel):
    filter: ListFilter = Field(default_factory=ListFilter)


@router.post(
    "/capabilities.list",
    response_model=ToolResponse,
    summary="List available capabilities",
)
async def tool_capabilities_list(
    body: CapabilitiesListRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """List capabilities from the control plane registry.

    **MCP Tool:** ``capabilities.list``

    **Input:**
    ```json
    {
        "filter": {
            "provider": "openai",   // optional
            "status": "active",     // optional
            "verified": true        // optional - filter by trust plane verification
        }
    }
    ```

    **Output:** List of capability objects plus a ``total`` count.
    """
    data = await cp_list_capabilities(
        provider=body.filter.provider,
        status=body.filter.status,
    )

    # Apply verified filter locally (trust plane data not merged here for MVP)
    items = data.get("items", [])
    if body.filter.verified is not None:
        # For MVP, filter only if items have verified field; otherwise pass through
        items = [item for item in items if item.get("verified") == body.filter.verified]
        data = {**data, "items": items, "total": len(items)}

    logger.info(
        "Tool: capabilities.list",
        extra={"filter": body.filter.model_dump(), "returned": data.get("total", 0)},
    )
    return _response("capabilities.list", data, request)


# ---------------------------------------------------------------------------
# capabilities.search
# ---------------------------------------------------------------------------


class CapabilitiesSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query string")


@router.post(
    "/capabilities.search",
    response_model=ToolResponse,
    summary="Search capabilities by name or description",
)
async def tool_capabilities_search(
    body: CapabilitiesSearchRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Search capabilities using substring matching on name and description.

    **MCP Tool:** ``capabilities.search``

    **Input:**
    ```json
    {"query": "image generation"}
    ```

    **Output:** Filtered list of matching capabilities.

    Note: This is a simple substring match for MVP. Replace with full-text
    search (Elasticsearch, pgvector, or Vertex AI Search) for production.
    """
    # Fetch all capabilities then filter in-process for MVP
    data = await cp_list_capabilities()
    items = data.get("items", [])

    query_lower = body.query.lower()
    matches = [
        item
        for item in items
        if query_lower in item.get("name", "").lower()
        or query_lower in item.get("description", "").lower()
        or any(query_lower in tag for tag in item.get("tags", []))
    ]

    result = {"items": matches, "total": len(matches), "query": body.query}
    if data.get("_stub"):
        result["_stub"] = True
        result["_note"] = data.get("_note", "")

    logger.info(
        "Tool: capabilities.search",
        extra={"query": body.query, "matches": len(matches)},
    )
    return _response("capabilities.search", result, request)


# ---------------------------------------------------------------------------
# capabilities.execute
# ---------------------------------------------------------------------------


class CapabilitiesExecuteRequest(BaseModel):
    capability_id: str = Field(..., description="ID of the capability to execute")
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Input parameters for the capability",
    )
    tenant_id: str = Field(..., description="Tenant making the request")
    idempotency_key: str | None = Field(
        default=None,
        description="Optional idempotency key for safe retries",
    )
    scope: str = Field(default="execute", description="Permission scope")


@router.post(
    "/capabilities.execute",
    response_model=ToolResponse,
    summary="Execute a capability via the gateway",
)
async def tool_capabilities_execute(
    body: CapabilitiesExecuteRequest,
    request: Request,
    auth_tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Execute a capability through the Moat gateway pipeline.

    **MCP Tool:** ``capabilities.execute``

    **Input:**
    ```json
    {
        "capability_id": "cap-abc123",
        "params": {"input": "Hello, world"},
        "tenant_id": "tenant-xyz",
        "idempotency_key": "req-001"
    }
    ```

    **Output:** Execution receipt including status, result, and latency.

    The gateway enforces:
    - Policy evaluation (deny if policy not met)
    - Idempotency (cached receipt returned on duplicate key)
    - Outcome event emission to trust plane
    """
    if body.tenant_id != auth_tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant ID in request body does not match authenticated tenant",
        )

    result = await gw_execute(
        capability_id=body.capability_id,
        params=body.params,
        tenant_id=body.tenant_id,
        idempotency_key=body.idempotency_key,
        scope=body.scope,
    )

    logger.info(
        "Tool: capabilities.execute",
        extra={
            "capability_id": body.capability_id,
            "tenant_id": body.tenant_id,
            "status": result.get("status"),
            "cached": result.get("cached", False),
        },
    )
    return _response("capabilities.execute", result, request)


# ---------------------------------------------------------------------------
# capabilities.stats
# ---------------------------------------------------------------------------


class CapabilitiesStatsRequest(BaseModel):
    capability_id: str = Field(
        ..., description="ID of the capability to retrieve stats for"
    )


@router.post(
    "/capabilities.stats",
    response_model=ToolResponse,
    summary="Get reliability stats for a capability",
)
async def tool_capabilities_stats(
    body: CapabilitiesStatsRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Retrieve rolling 7-day reliability statistics from the trust plane.

    **MCP Tool:** ``capabilities.stats``

    **Input:**
    ```json
    {"capability_id": "cap-abc123"}
    ```

    **Output:** Reliability stats including success rate, p95 latency,
    verification status, and trust signals (should_hide, should_throttle).
    """
    result = await tp_get_stats(body.capability_id)

    logger.info(
        "Tool: capabilities.stats",
        extra={
            "capability_id": body.capability_id,
            "success_rate_7d": result.get("success_rate_7d"),
            "verified": result.get("verified"),
        },
    )
    return _response("capabilities.stats", result, request)


# ---------------------------------------------------------------------------
# bounty.discover
# ---------------------------------------------------------------------------


class BountyDiscoverRequest(BaseModel):
    platform: str = Field(default="algora", description="Bounty platform to search")
    query: str = Field(default="", description="Search query")
    language: str | None = Field(
        default=None, description="Programming language filter"
    )
    min_reward_usd: float | None = Field(
        default=None, description="Minimum reward in USD"
    )
    max_results: int = Field(default=20, description="Maximum results to return")


@router.post(
    "/bounty.discover",
    response_model=ToolResponse,
    summary="Search bounty platforms for open issues",
)
async def tool_bounty_discover(
    body: BountyDiscoverRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Search bounty platforms (Algora, Gitcoin, Polar, GitHub) for funded bounties."""
    result = await gw_execute_bounty_discover(
        platform=body.platform,
        query=body.query,
        language=body.language,
        max_results=body.max_results,
        tenant_id=tenant_id,
    )
    logger.info(
        "Tool: bounty.discover",
        extra={"platform": body.platform, "query": body.query},
    )
    return _response("bounty.discover", result, request)


# ---------------------------------------------------------------------------
# bounty.triage
# ---------------------------------------------------------------------------


class BountyTriageRequest(BaseModel):
    url: str = Field(..., description="GitHub issue or PR URL")


@router.post(
    "/bounty.triage",
    response_model=ToolResponse,
    summary="Triage a GitHub issue via GWI",
)
async def tool_bounty_triage(
    body: BountyTriageRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Triage a GitHub issue using GWI triage.

    Returns complexity score and assessment.
    """
    result = await gw_execute_gwi_triage(url=body.url, tenant_id=tenant_id)
    logger.info(
        "Tool: bounty.triage",
        extra={"url": body.url},
    )
    return _response(
        "bounty.triage",
        {"url": body.url, "command": "triage", "gateway_receipt": result},
        request,
    )


# ---------------------------------------------------------------------------
# bounty.execute
# ---------------------------------------------------------------------------


class BountyExecuteRequest(BaseModel):
    url: str = Field(..., description="GitHub issue URL to fix")
    command: str = Field(
        default="issue-to-code",
        description="GWI command: issue-to-code or resolve",
    )


@router.post(
    "/bounty.execute",
    response_model=ToolResponse,
    summary="Execute a fix via GWI",
)
async def tool_bounty_execute(
    body: BountyExecuteRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Execute a GitHub issue fix using GWI issue-to-code or resolve."""
    result = await gw_execute_gwi_command(
        url=body.url,
        command=body.command,
        tenant_id=tenant_id,
    )
    logger.info(
        "Tool: bounty.execute",
        extra={"url": body.url, "command": body.command},
    )
    return _response(
        "bounty.execute",
        {"url": body.url, "command": body.command, "gateway_receipt": result},
        request,
    )


# ---------------------------------------------------------------------------
# bounty.status
# ---------------------------------------------------------------------------


class BountyStatusRequest(BaseModel):
    url: str = Field(..., description="GitHub issue URL to check status for")
    capability_id: str = Field(
        default="gwi.triage", description="Capability ID for stats"
    )


@router.post(
    "/bounty.status",
    response_model=ToolResponse,
    summary="Composite bounty status check",
)
async def tool_bounty_status(
    body: BountyStatusRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Check bounty execution status: triage score + trust stats + IRSB receipt."""
    import asyncio

    stats_task = asyncio.create_task(tp_get_stats(body.capability_id))
    triage_task = asyncio.create_task(
        gw_execute_gwi_triage(url=body.url, tenant_id=tenant_id)
    )

    stats, triage = await asyncio.gather(
        stats_task, triage_task, return_exceptions=True
    )

    result = {
        "url": body.url,
        "trust_stats": stats
        if not isinstance(stats, Exception)
        else {"error": str(stats)},
        "triage_result": triage
        if not isinstance(triage, Exception)
        else {"error": str(triage)},
    }
    logger.info(
        "Tool: bounty.status",
        extra={"url": body.url, "capability_id": body.capability_id},
    )
    return _response("bounty.status", result, request)


# ---------------------------------------------------------------------------
# agents.discover
# ---------------------------------------------------------------------------


class AgentsDiscoverRequest(BaseModel):
    skill_tag: str | None = Field(default=None, description="Filter by skill tag")


@router.post(
    "/agents.discover",
    response_model=ToolResponse,
    summary="List all known agents in the Moat ecosystem",
)
async def tool_agents_discover(
    body: AgentsDiscoverRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """List all known agents with their A2A AgentCards.

    **MCP Tool:** ``agents.discover``

    Optionally filter by skill tag to find agents with specific capabilities.
    """
    agents = list(AGENT_CARDS.values())

    if body.skill_tag:
        tag_lower = body.skill_tag.lower()
        agents = [
            agent
            for agent in agents
            if any(
                tag_lower in tag
                for skill in agent.get("skills", [])
                for tag in skill.get("tags", [])
            )
        ]

    result = {"agents": agents, "total": len(agents)}
    logger.info(
        "Tool: agents.discover",
        extra={"skill_tag": body.skill_tag, "total": len(agents)},
    )
    return _response("agents.discover", result, request)


# ---------------------------------------------------------------------------
# agents.card
# ---------------------------------------------------------------------------


class AgentsCardRequest(BaseModel):
    agent_name: str = Field(..., description="Agent name to look up")


@router.post(
    "/agents.card",
    response_model=ToolResponse,
    summary="Get an agent's A2A AgentCard",
)
async def tool_agents_card(
    body: AgentsCardRequest,
    request: Request,
    tenant_id: Annotated[str, Depends(get_current_tenant)],
) -> ToolResponse:
    """Get the full A2A AgentCard for a specific agent.

    **MCP Tool:** ``agents.card``
    """
    card = AGENT_CARDS.get(body.agent_name)
    if card is None:
        result = {
            "error": f"Agent '{body.agent_name}' not found",
            "known_agents": list(AGENT_CARDS.keys()),
        }
    else:
        result = card

    logger.info(
        "Tool: agents.card",
        extra={"agent_name": body.agent_name, "found": card is not None},
    )
    return _response("agents.card", result, request)
