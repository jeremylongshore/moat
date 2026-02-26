"""
app.stdio_server
~~~~~~~~~~~~~~~~
MCP SDK stdio transport for the Moat MCP Server.

Exposes all 8 Moat tools (4 core + 4 scout-workflow) via the Model Context
Protocol stdio transport. This is the primary integration path for Claude
Desktop, Claude Code, and other MCP-native AI agents.

Usage::

    # Direct invocation
    python -m app.stdio_server

    # Via installed entry point
    moat-mcp-stdio

Claude Desktop / Claude Code config::

    {
        "mcpServers": {
            "moat": {
                "command": "python",
                "args": ["-m", "app.stdio_server"],
                "cwd": "/path/to/moat/services/mcp-server",
                "env": {
                    "MOAT_AUTH_DISABLED": "true",
                    "CONTROL_PLANE_URL": "http://localhost:8001",
                    "GATEWAY_URL": "http://localhost:8002",
                    "TRUST_PLANE_URL": "http://localhost:8003"
                }
            }
        }
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from mcp.server import Server
from mcp.types import TextContent, Tool

from app.http_client import (
    cp_list_capabilities,
    gw_execute,
    tp_get_stats,
)
from app.tool_definitions import TOOL_SCHEMAS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MCP Server instance
# ---------------------------------------------------------------------------

server = Server("moat-mcp")

# Default tenant for the scout agent
_DEFAULT_TENANT = "automaton"


# ---------------------------------------------------------------------------
# Tool listing
# ---------------------------------------------------------------------------


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Return all 8 Moat tools with their schemas."""
    return [
        Tool(
            name=schema["name"],
            description=schema["description"],
            inputSchema=schema["input_schema"],
        )
        for schema in TOOL_SCHEMAS
    ]


# ---------------------------------------------------------------------------
# Platform URL mapping for bounty.discover
# ---------------------------------------------------------------------------

_PLATFORM_URLS: dict[str, str] = {
    "algora": "https://console.algora.io/api/bounties",
    "gitcoin": "https://gitcoin.co/api/v0.1/bounties/",
    "polar": "https://api.polar.sh/v1/issues/search",
    "github": "https://api.github.com/search/issues",
}


# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------


def _text(data: Any) -> list[TextContent]:
    """Wrap a result dict as a JSON TextContent response."""
    return [TextContent(type="text", text=json.dumps(data, indent=2, default=str))]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Dispatch a tool call to the appropriate handler."""
    tenant = arguments.pop("tenant_id", _DEFAULT_TENANT)

    # ── Core capability tools ──────────────────────────────────────────
    if name == "capabilities.list":
        filt = arguments.get("filter", {})
        result = await cp_list_capabilities(
            provider=filt.get("provider"),
            status=filt.get("status"),
        )
        return _text(result)

    if name == "capabilities.search":
        query = arguments.get("query", "")
        data = await cp_list_capabilities()
        items = data.get("items", [])
        query_lower = query.lower()
        matches = [
            item
            for item in items
            if query_lower in item.get("name", "").lower()
            or query_lower in item.get("description", "").lower()
        ]
        return _text({"items": matches, "total": len(matches), "query": query})

    if name == "capabilities.execute":
        cap_id = arguments["capability_id"]
        result = await gw_execute(
            capability_id=cap_id,
            params=arguments.get("params", {}),
            tenant_id=tenant,
            idempotency_key=arguments.get("idempotency_key"),
            scope=arguments.get("scope", "execute"),
        )
        return _text(result)

    if name == "capabilities.stats":
        cap_id = arguments["capability_id"]
        result = await tp_get_stats(cap_id)
        return _text(result)

    # ── Scout-workflow tools ───────────────────────────────────────────
    if name == "bounty.discover":
        return _text(await _handle_bounty_discover(arguments, tenant))

    if name == "bounty.triage":
        return _text(await _handle_bounty_triage(arguments, tenant))

    if name == "bounty.execute":
        return _text(await _handle_bounty_execute(arguments, tenant))

    if name == "bounty.status":
        return _text(await _handle_bounty_status(arguments, tenant))

    # ── A2A Discovery tools ─────────────────────────────────────────
    if name == "agents.discover":
        return _text(await _handle_agents_discover(arguments))

    if name == "agents.card":
        return _text(await _handle_agents_card(arguments))

    return _text({"error": f"Unknown tool: {name}"})


# ---------------------------------------------------------------------------
# Scout-workflow handlers
# ---------------------------------------------------------------------------


async def _handle_bounty_discover(args: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Search bounty platforms via http.proxy capability."""
    platform = args.get("platform", "algora")
    query = args.get("query", "")
    max_results = args.get("max_results", 20)

    base_url = _PLATFORM_URLS.get(platform)
    if not base_url:
        return {
            "error": f"Unknown platform: {platform}",
            "supported": list(_PLATFORM_URLS.keys()),
        }

    # Build platform-specific query params
    params: dict[str, Any] = {"url": base_url, "method": "GET"}

    if platform == "algora":
        if query:
            params["url"] = f"{base_url}?q={query}&limit={max_results}"
        else:
            params["url"] = f"{base_url}?limit={max_results}"
    elif platform == "github":
        q_parts = ["type:issue", "state:open", "label:bounty"]
        if query:
            q_parts.insert(0, query)
        if args.get("language"):
            q_parts.append(f"language:{args['language']}")
        params["url"] = f"{base_url}?q={'+'.join(q_parts)}&per_page={max_results}"
    elif platform == "gitcoin":
        params["url"] = f"{base_url}?is_open=true&limit={max_results}"
        if query:
            params["url"] += f"&keyword={query}"
    elif platform == "polar":
        params["url"] = f"{base_url}?have_badge=true&limit={max_results}"
        if query:
            params["url"] += f"&q={query}"

    result = await gw_execute(
        capability_id="http.proxy",
        params=params,
        tenant_id=tenant,
        scope="execute",
    )

    return {
        "platform": platform,
        "query": query,
        "gateway_receipt": result,
    }


async def _handle_bounty_triage(args: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Triage a GitHub issue via GWI triage capability."""
    url = args["url"]
    result = await gw_execute(
        capability_id="gwi.triage",
        params={"url": url},
        tenant_id=tenant,
        scope="execute",
    )
    return {
        "url": url,
        "command": "triage",
        "gateway_receipt": result,
    }


async def _handle_bounty_execute(args: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Execute a fix via GWI issue-to-code or resolve."""
    url = args["url"]
    command = args.get("command", "issue-to-code")

    cap_id = (
        f"gwi.{command}"
        if command in ("issue-to-code", "resolve")
        else "gwi.issue-to-code"
    )

    result = await gw_execute(
        capability_id=cap_id,
        params={"url": url},
        tenant_id=tenant,
        scope="execute",
    )
    return {
        "url": url,
        "command": command,
        "gateway_receipt": result,
    }


async def _handle_bounty_status(args: dict[str, Any], tenant: str) -> dict[str, Any]:
    """Composite status: triage score + trust stats + IRSB receipt status."""
    url = args["url"]
    cap_id = args.get("capability_id", "gwi.triage")

    # Fetch trust plane stats and triage result in parallel
    stats_task = asyncio.create_task(tp_get_stats(cap_id))
    triage_task = asyncio.create_task(
        gw_execute(
            capability_id="gwi.triage",
            params={"url": url},
            tenant_id=tenant,
            scope="execute",
        )
    )

    stats, triage = await asyncio.gather(
        stats_task, triage_task, return_exceptions=True
    )

    return {
        "url": url,
        "trust_stats": stats
        if not isinstance(stats, Exception)
        else {"error": str(stats)},
        "triage_result": triage
        if not isinstance(triage, Exception)
        else {"error": str(triage)},
    }


# ---------------------------------------------------------------------------
# A2A Discovery handlers
# ---------------------------------------------------------------------------


async def _handle_agents_discover(args: dict[str, Any]) -> dict[str, Any]:
    """List all known agents, optionally filtered by skill tag."""
    from app.routers.discovery import AGENT_CARDS

    agents = list(AGENT_CARDS.values())
    skill_tag = args.get("skill_tag")

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


async def _handle_agents_card(args: dict[str, Any]) -> dict[str, Any]:
    """Get the AgentCard for a specific agent."""
    from app.routers.discovery import AGENT_CARDS

    agent_name = args.get("agent_name", "")
    card = AGENT_CARDS.get(agent_name)
    if card is None:
        return {
            "error": f"Agent '{agent_name}' not found",
            "known_agents": list(AGENT_CARDS.keys()),
        }
    return card


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def _run() -> None:
    """Start the MCP stdio server."""
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> None:
    """Synchronous entry point for the ``moat-mcp-stdio`` console script."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
