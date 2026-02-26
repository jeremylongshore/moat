"""
Tests for the control-plane agent registry API.

All tests use a real temporary SQLite database — no mocks.
"""

from __future__ import annotations


def _agent_payload(**overrides):
    """Base agent creation payload."""
    base = {
        "name": "test-agent",
        "description": "A test agent",
        "url": "http://localhost:9000",
        "version": "0.1.0",
        "provider_org": "Moat",
        "skills": [
            {
                "id": "test-skill",
                "name": "Test Skill",
                "description": "Does testing",
                "tags": ["test"],
                "examples": ["Run a test"],
            }
        ],
        "capabilities": {
            "streaming": False,
            "push_notifications": False,
            "state_transition_history": False,
        },
        "authentication": {"schemes": ["bearer"]},
    }
    base.update(overrides)
    return base


class TestAgentCRUD:
    """Test agent create, read, update, delete operations."""

    def test_create_agent(self, test_client):
        """Create a new agent with A2A fields."""
        resp = test_client.post(
            "/agents",
            json=_agent_payload(name="create-test"),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "create-test"
        assert data["url"] == "http://localhost:9000"
        assert data["version"] == "0.1.0"
        assert data["status"] == "active"
        assert "agent_id" in data
        assert "created_at" in data
        assert len(data["skills"]) == 1
        assert data["skills"][0]["id"] == "test-skill"

    def test_create_agent_with_erc8004(self, test_client):
        """Create an agent with ERC-8004 on-chain identity."""
        resp = test_client.post(
            "/agents",
            json=_agent_payload(
                name="erc8004-agent",
                erc8004={
                    "agent_id": 42,
                    "chain_id": 11155111,
                    "registry_address": ("0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c"),
                    "agent_uri": ("https://moat.dev/.well-known/agent.json"),
                },
            ),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["erc8004_agent_id"] == 42
        assert data["erc8004_chain_id"] == 11155111
        assert "0xD66A" in data["erc8004_registry_address"]
        assert data["erc8004_agent_uri"] is not None

    def test_create_agent_with_spiffe(self, test_client):
        """Create an agent with SPIFFE workload identity."""
        resp = test_client.post(
            "/agents",
            json=_agent_payload(
                name="spiffe-agent",
                spiffe_id=("spiffe://moat.dev/agent/gateway"),
            ),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["spiffe_id"] == ("spiffe://moat.dev/agent/gateway")

    def test_create_duplicate_name_409(self, test_client):
        """409 when agent name already exists."""
        test_client.post(
            "/agents",
            json=_agent_payload(name="dupe-test"),
        )
        resp = test_client.post(
            "/agents",
            json=_agent_payload(name="dupe-test"),
        )
        assert resp.status_code == 409

    def test_list_agents(self, test_client):
        """List all agents."""
        test_client.post(
            "/agents",
            json=_agent_payload(name="list-agent-1"),
        )
        test_client.post(
            "/agents",
            json=_agent_payload(name="list-agent-2"),
        )
        resp = test_client.get("/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        names = [a["name"] for a in data["items"]]
        assert "list-agent-1" in names
        assert "list-agent-2" in names

    def test_list_agents_filter_by_status(self, test_client):
        """Filter agents by status."""
        resp = test_client.get("/agents?status=active")
        assert resp.status_code == 200

    def test_get_agent(self, test_client):
        """Get a single agent by ID."""
        create_resp = test_client.post(
            "/agents",
            json=_agent_payload(name="get-test"),
        )
        agent_id = create_resp.json()["agent_id"]

        resp = test_client.get(f"/agents/{agent_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "get-test"

    def test_get_agent_not_found(self, test_client):
        """404 for nonexistent agent."""
        resp = test_client.get("/agents/nonexistent-id")
        assert resp.status_code == 404

    def test_update_agent(self, test_client):
        """Update agent metadata."""
        create_resp = test_client.post(
            "/agents",
            json=_agent_payload(name="update-test"),
        )
        agent_id = create_resp.json()["agent_id"]

        resp = test_client.patch(
            f"/agents/{agent_id}",
            json={
                "description": "Updated description",
                "version": "0.2.0",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["description"] == "Updated description"
        assert data["version"] == "0.2.0"

    def test_update_agent_erc8004(self, test_client):
        """Bind ERC-8004 identity to existing agent."""
        create_resp = test_client.post(
            "/agents",
            json=_agent_payload(name="bind-erc8004"),
        )
        agent_id = create_resp.json()["agent_id"]

        resp = test_client.patch(
            f"/agents/{agent_id}",
            json={
                "erc8004": {
                    "agent_id": 99,
                    "chain_id": 1,
                    "registry_address": ("0x742d35Cc6634C0532925a3b844Bc9e7595f2bD08"),
                },
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["erc8004_agent_id"] == 99
        assert data["erc8004_chain_id"] == 1

    def test_update_agent_not_found(self, test_client):
        """404 when updating nonexistent agent."""
        resp = test_client.patch(
            "/agents/nonexistent-id",
            json={"description": "nope"},
        )
        assert resp.status_code == 404

    def test_delete_agent(self, test_client):
        """Delete an agent."""
        create_resp = test_client.post(
            "/agents",
            json=_agent_payload(name="delete-test"),
        )
        agent_id = create_resp.json()["agent_id"]

        resp = test_client.delete(f"/agents/{agent_id}")
        assert resp.status_code == 204

        # Verify it's gone
        get_resp = test_client.get(f"/agents/{agent_id}")
        assert get_resp.status_code == 404

    def test_delete_agent_not_found(self, test_client):
        """404 when deleting nonexistent agent."""
        resp = test_client.delete("/agents/nonexistent-id")
        assert resp.status_code == 404
