"""
Tests for the A2A Skill Builder and A2A Proxy Adapter.

Tests the adapter's protocol handling and the skill builder's
capability registration logic — all real data, no mocks.
"""


class TestA2AProxyAdapter:
    """Tests for the A2A proxy adapter."""

    def test_provider_name(self):
        """Adapter registers as 'a2a'."""
        from app.adapters.a2a_proxy import A2AProxyAdapter

        adapter = A2AProxyAdapter()
        assert adapter.provider_name == "a2a"

    async def test_execute_missing_agent_url(self):
        """Returns error when agent_url is missing."""
        from app.adapters.a2a_proxy import A2AProxyAdapter

        adapter = A2AProxyAdapter()
        result = await adapter.execute(
            capability_id="test-cap",
            capability_name="Test",
            params={"message": "hello"},
            credential=None,
        )
        assert result["status"] == "error"
        assert "agent_url" in result["error"]

    async def test_execute_unreachable_agent(self):
        """Returns error when agent is unreachable."""
        from app.adapters.a2a_proxy import A2AProxyAdapter

        adapter = A2AProxyAdapter()
        result = await adapter.execute(
            capability_id="test-cap",
            capability_name="Test",
            params={
                "agent_url": "http://localhost:19999",
                "message": "hello",
            },
            credential=None,
        )
        assert result["status"] == "error"
        assert "latency_ms" in result

    def test_adapter_registered_in_gateway(self):
        """A2A adapter is registered in the gateway's adapter registry."""
        # Import execute module to trigger adapter registration
        from app.routers.execute import adapter_registry

        adapter = adapter_registry.get("a2a")
        assert adapter is not None
        assert adapter.provider_name == "a2a"


class TestSkillBuilder:
    """Tests for the skill builder utility."""

    async def test_fetch_card_unreachable(self):
        """fetch_agent_card returns None for unreachable agent."""
        from app.skill_builder import fetch_agent_card

        card = await fetch_agent_card("http://localhost:19999")
        assert card is None

    async def test_register_skills_unreachable(self):
        """register_agent_skills returns error for unreachable agent."""
        from app.skill_builder import register_agent_skills

        result = await register_agent_skills("http://localhost:19999")
        assert result["status"] == "error"
        assert result["capabilities_registered"] == 0

    def test_skill_to_capability_mapping(self):
        """A2A skill correctly maps to capability payload."""
        from app.skill_builder import _skill_to_capability

        skill = {
            "id": "code-review",
            "name": "Code Review",
            "description": "Reviews code for quality issues",
            "tags": ["code", "review"],
        }
        card = {
            "name": "review-bot",
            "url": "http://review-bot:9000",
            "version": "1.0.0",
        }

        cap = _skill_to_capability(skill, card)

        assert cap["name"] == "review-bot/code-review"
        assert cap["description"] == "Reviews code for quality issues"
        assert cap["provider"] == "a2a"
        assert cap["version"] == "1.0.0"
        assert "a2a" in cap["tags"]
        assert "agent:review-bot" in cap["tags"]
        assert "code" in cap["tags"]
        assert (
            cap["input_schema"]["properties"]["agent_url"]["default"]
            == "http://review-bot:9000"
        )

    def test_skill_to_capability_no_skill_id(self):
        """Handles skill without explicit id field."""
        from app.skill_builder import _skill_to_capability

        skill = {"name": "My Skill", "description": "Does things"}
        card = {"name": "agent-x", "url": "http://x:9000"}

        cap = _skill_to_capability(skill, card)

        assert cap["name"] == "agent-x/My Skill"


class TestSkillBuilderEndpoints:
    """Tests for the skill builder REST endpoints."""

    def test_discover_unreachable(self, test_client):
        """GET /skill-builder/discover returns error for unreachable agent."""
        resp = test_client.get(
            "/skill-builder/discover",
            params={"agent_url": "http://localhost:19999"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"

    def test_register_unreachable(self, test_client):
        """POST /skill-builder/register returns error for unreachable agent."""
        resp = test_client.post(
            "/skill-builder/register",
            json={
                "agent_url": "http://localhost:19999",
                "tenant_id": "dev-tenant",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "error"
        assert data["capabilities_registered"] == 0
