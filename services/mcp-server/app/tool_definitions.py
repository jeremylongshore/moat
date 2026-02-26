"""
app.tool_definitions
~~~~~~~~~~~~~~~~~~~~
Single source of truth for all MCP tool schemas.

Used by both the REST surface (routers/tools.py) and the stdio transport
(stdio_server.py) so tool names, descriptions, and input schemas are always
in sync.
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Tool schema type
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    # ── Core capability tools ──────────────────────────────────────────────
    {
        "name": "capabilities.list",
        "description": "List capabilities from the registry with optional filters",
        "input_schema": {
            "type": "object",
            "properties": {
                "filter": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "status": {
                            "type": "string",
                            "enum": ["active", "inactive", "deprecated"],
                        },
                        "verified": {"type": "boolean"},
                    },
                },
            },
        },
    },
    {
        "name": "capabilities.search",
        "description": "Search capabilities by name, description, or tags",
        "input_schema": {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    },
    {
        "name": "capabilities.execute",
        "description": "Execute a capability through the policy-enforced gateway",
        "input_schema": {
            "type": "object",
            "required": ["capability_id", "tenant_id"],
            "properties": {
                "capability_id": {"type": "string"},
                "params": {"type": "object"},
                "tenant_id": {"type": "string"},
                "idempotency_key": {"type": "string"},
                "scope": {"type": "string"},
            },
        },
    },
    {
        "name": "capabilities.stats",
        "description": "Get 7-day reliability stats and trust signals for a capability",
        "input_schema": {
            "type": "object",
            "required": ["capability_id"],
            "properties": {"capability_id": {"type": "string"}},
        },
    },
    # ── Scout-workflow tools ───────────────────────────────────────────────
    {
        "name": "bounty.discover",
        "description": (
            "Search bounty platforms (Algora, Gitcoin, Polar, GitHub) for open issues "
            "and funded bounties. Returns a list of opportunities with reward amounts, "
            "complexity estimates, and platform links."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "platform": {
                    "type": "string",
                    "enum": ["algora", "gitcoin", "polar", "github"],
                    "default": "algora",
                    "description": "Bounty platform to search",
                },
                "query": {
                    "type": "string",
                    "default": "",
                    "description": "Search query (keywords, language, etc.)",
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Filter by programming language (e.g. 'rust', 'typescript')"
                    ),
                },
                "min_reward_usd": {
                    "type": "number",
                    "description": "Minimum reward amount in USD",
                },
                "max_results": {
                    "type": "integer",
                    "default": 20,
                    "description": "Maximum number of results to return",
                },
            },
        },
    },
    {
        "name": "bounty.triage",
        "description": (
            "Triage a GitHub issue or PR using GWI (git-with-intent). Returns a "
            "complexity score, estimated effort, risk assessment, and recommended "
            "approach for solving the issue."
        ),
        "input_schema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "GitHub issue or PR URL (e.g. https://github.com/org/repo/issues/42)",
                },
            },
        },
    },
    {
        "name": "bounty.execute",
        "description": (
            "Execute a fix for a GitHub issue using GWI issue-to-code or resolve. "
            "Generates code changes, creates a branch, and optionally opens a PR."
        ),
        "input_schema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "GitHub issue URL to fix",
                },
                "command": {
                    "type": "string",
                    "enum": ["issue-to-code", "resolve"],
                    "default": "issue-to-code",
                    "description": (
                        "GWI command: issue-to-code (generate fix) "
                        "or resolve (apply + PR)"
                    ),
                },
            },
        },
    },
    {
        "name": "bounty.status",
        "description": (
            "Check the status of a bounty execution: GWI triage score, trust plane "
            "reliability stats, and IRSB receipt status. Composite view across "
            "multiple Moat subsystems."
        ),
        "input_schema": {
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "GitHub issue URL to check status for",
                },
                "capability_id": {
                    "type": "string",
                    "default": "gwi.triage",
                    "description": "Capability ID to check stats for",
                },
            },
        },
    },
    # ── A2A Discovery tools ──────────────────────────────────────────────
    {
        "name": "agents.discover",
        "description": (
            "List all known agents in the Moat ecosystem. Returns A2A AgentCards "
            "with skills, capabilities, and connection details. Optionally filter "
            "by skill tag."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_tag": {
                    "type": "string",
                    "description": (
                        "Filter agents by skill tag (e.g. 'execute', 'trust')"
                    ),
                },
            },
        },
    },
    {
        "name": "agents.card",
        "description": (
            "Get the A2A AgentCard for a specific agent by name. Returns full "
            "details including skills, authentication requirements, and capabilities."
        ),
        "input_schema": {
            "type": "object",
            "required": ["agent_name"],
            "properties": {
                "agent_name": {
                    "type": "string",
                    "description": (
                        "Agent name (e.g. 'moat-gateway', 'moat-mcp-server', "
                        "'moat-control-plane', 'moat-trust-plane')"
                    ),
                },
            },
        },
    },
]


def get_tool_schema(name: str) -> dict[str, Any] | None:
    """Return the tool schema for the given tool name, or None."""
    for tool in TOOL_SCHEMAS:
        if tool["name"] == name:
            return tool
    return None


def get_all_tool_names() -> list[str]:
    """Return a list of all registered tool names."""
    return [t["name"] for t in TOOL_SCHEMAS]
