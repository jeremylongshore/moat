"""
Tests for A2A discovery endpoints and tools.

Covers:
- /.well-known/agent.json (A2A standard)
- /agents listing and filtering
- /agents/{name} lookup
- POST /tools/agents.discover
- POST /tools/agents.card
"""


# ---------------------------------------------------------------------------
# /.well-known/agent.json
# ---------------------------------------------------------------------------


def test_well_known_agent_json(test_client):
    """Standard A2A discovery endpoint returns a valid AgentCard."""
    resp = test_client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "moat-mcp-server"
    assert "provider" in card
    assert card["provider"]["organization"] == "Moat"
    assert "skills" in card
    assert len(card["skills"]) >= 8  # 8 original + 2 discovery


def test_well_known_has_discovery_skills(test_client):
    """AgentCard includes the new agents.discover and agents.card skills."""
    resp = test_client.get("/.well-known/agent.json")
    card = resp.json()
    skill_ids = [s["id"] for s in card["skills"]]
    assert "agents.discover" in skill_ids
    assert "agents.card" in skill_ids


# ---------------------------------------------------------------------------
# /agents
# ---------------------------------------------------------------------------


def test_list_agents(test_client):
    """List all known agents returns all 4 Moat services."""
    resp = test_client.get("/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 4
    names = [a["name"] for a in data["agents"]]
    assert "moat-mcp-server" in names
    assert "moat-gateway" in names
    assert "moat-control-plane" in names
    assert "moat-trust-plane" in names


def test_list_agents_filter_by_skill_tag(test_client):
    """Filter agents by skill tag returns matching agents."""
    resp = test_client.get("/agents?skill_tag=execute")
    assert resp.status_code == 200
    data = resp.json()
    # Gateway and MCP server both have execute-tagged skills
    names = [a["name"] for a in data["agents"]]
    assert "moat-gateway" in names


def test_list_agents_filter_no_match(test_client):
    """Filter with non-existent tag returns empty list."""
    resp = test_client.get("/agents?skill_tag=nonexistent-xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["agents"] == []


# ---------------------------------------------------------------------------
# /agents/{agent_name}
# ---------------------------------------------------------------------------


def test_get_agent_card(test_client):
    """Get a specific agent's card by name."""
    resp = test_client.get("/agents/moat-gateway")
    assert resp.status_code == 200
    card = resp.json()
    assert card["name"] == "moat-gateway"
    assert "skills" in card


def test_get_agent_card_not_found(test_client):
    """404 for unknown agent name."""
    resp = test_client.get("/agents/nonexistent-agent")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /tools/agents.discover
# ---------------------------------------------------------------------------


def test_tool_agents_discover(test_client):
    """MCP tool: agents.discover returns all agents."""
    resp = test_client.post(
        "/tools/agents.discover",
        json={},
        headers={"X-Tenant-ID": "dev-tenant"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool"] == "agents.discover"
    assert data["result"]["total"] == 4


def test_tool_agents_discover_with_filter(test_client):
    """MCP tool: agents.discover with skill_tag filter."""
    resp = test_client.post(
        "/tools/agents.discover",
        json={"skill_tag": "trust"},
        headers={"X-Tenant-ID": "dev-tenant"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["total"] >= 1
    names = [a["name"] for a in data["result"]["agents"]]
    assert "moat-trust-plane" in names


# ---------------------------------------------------------------------------
# POST /tools/agents.card
# ---------------------------------------------------------------------------


def test_tool_agents_card(test_client):
    """MCP tool: agents.card returns a specific agent's card."""
    resp = test_client.post(
        "/tools/agents.card",
        json={"agent_name": "moat-mcp-server"},
        headers={"X-Tenant-ID": "dev-tenant"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["tool"] == "agents.card"
    assert data["result"]["name"] == "moat-mcp-server"


def test_tool_agents_card_not_found(test_client):
    """MCP tool: agents.card returns error for unknown agent."""
    resp = test_client.post(
        "/tools/agents.card",
        json={"agent_name": "nonexistent"},
        headers={"X-Tenant-ID": "dev-tenant"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data["result"]
    assert "known_agents" in data["result"]


# ---------------------------------------------------------------------------
# /tools listing includes new tools
# ---------------------------------------------------------------------------


def test_tools_listing_includes_discovery(test_client):
    """GET /tools includes the new agents.discover and agents.card tools."""
    resp = test_client.get("/tools")
    assert resp.status_code == 200
    tools = resp.json()["tools"]
    tool_names = [t["name"] for t in tools]
    assert "agents.discover" in tool_names
    assert "agents.card" in tool_names
