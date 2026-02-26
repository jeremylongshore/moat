"""
Tests for ERC-8004 metadata, registry sync, and gateway discovery.

All tests use real data structures — no mocks.
"""


# ---------------------------------------------------------------------------
# Metadata tests
# ---------------------------------------------------------------------------


class TestBuildAgentMetadata:
    """Tests for build_agent_metadata()."""

    def test_basic_agent(self):
        """Build metadata from a minimal agent dict."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "test-agent",
            "description": "A test agent",
            "url": "http://localhost:9000",
            "version": "0.2.0",
            "status": "active",
            "skills": [],
        }

        metadata = build_agent_metadata(agent)

        assert metadata["type"].endswith("#registration-v1")
        assert metadata["name"] == "test-agent"
        assert metadata["description"] == "A test agent"
        assert metadata["active"] is True
        assert metadata["x402Support"] is False
        assert metadata["supportedTrust"] == ["reputation"]
        # No skills → single default service entry
        assert len(metadata["services"]) == 1
        assert metadata["services"][0]["name"] == "test-agent"
        assert metadata["services"][0]["version"] == "0.2.0"

    def test_agent_with_skills(self):
        """Skills map to services array."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "skilled-agent",
            "description": "Has skills",
            "url": "http://localhost:9000",
            "version": "1.0.0",
            "status": "active",
            "skills": [
                {
                    "id": "triage",
                    "name": "Triage",
                    "tags": ["code", "review"],
                },
                {
                    "id": "execute",
                    "name": "Execute",
                    "tags": ["run", "deploy"],
                },
            ],
        }

        metadata = build_agent_metadata(agent)

        assert len(metadata["services"]) == 2
        assert metadata["services"][0]["name"] == "triage"
        assert metadata["services"][0]["skills"] == ["code", "review"]
        assert metadata["services"][1]["name"] == "execute"

    def test_agent_with_erc8004_identity(self):
        """Agent with on-chain identity includes registrations."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "onchain-agent",
            "description": "Has on-chain ID",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
            "erc8004_agent_id": 42,
            "erc8004_chain_id": 11155111,
            "erc8004_registry_address": "0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
        }

        metadata = build_agent_metadata(agent)

        assert len(metadata["registrations"]) == 1
        reg = metadata["registrations"][0]
        assert reg["agentId"] == 42
        assert "eip155:11155111:0xD66A" in reg["agentRegistry"]

    def test_agent_without_erc8004(self):
        """Agent without on-chain ID has empty registrations."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "offchain-agent",
            "description": "No chain ID",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
        }

        metadata = build_agent_metadata(agent)

        assert metadata["registrations"] == []

    def test_inactive_agent(self):
        """Inactive agent has active=False."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "dead-agent",
            "description": "Deactivated",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "inactive",
            "skills": [],
        }

        metadata = build_agent_metadata(agent)

        assert metadata["active"] is False

    def test_custom_chain_and_registry(self):
        """Override chain_id and registry_address."""
        from app.erc8004.metadata import build_agent_metadata

        agent = {
            "name": "custom-chain-agent",
            "description": "",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
            "erc8004_agent_id": 99,
        }

        metadata = build_agent_metadata(
            agent,
            chain_id=1,
            registry_address="0x1234567890abcdef1234567890abcdef12345678",
        )

        reg = metadata["registrations"][0]
        assert "eip155:1:0x1234" in reg["agentRegistry"]


class TestBuildFeedbackMetadata:
    """Tests for build_feedback_metadata()."""

    def test_basic_feedback(self):
        """Build basic reputation feedback metadata."""
        from app.erc8004.metadata import build_feedback_metadata

        feedback = build_feedback_metadata(
            agent_id=42,
            chain_id=11155111,
            registry_address="0xABC",
            client_address="0xDEF",
            value=95,
        )

        assert feedback["agentId"] == 42
        assert "eip155:11155111:0xABC" in feedback["agentRegistry"]
        assert "eip155:11155111:0xDEF" in feedback["clientAddress"]
        assert feedback["value"] == 95
        assert feedback["tag1"] == "moat-execution"

    def test_feedback_with_capability(self):
        """Capability ID flows to tag2."""
        from app.erc8004.metadata import build_feedback_metadata

        feedback = build_feedback_metadata(
            agent_id=1,
            capability_id="gwi.triage",
        )

        assert feedback["tag2"] == "gwi.triage"


# ---------------------------------------------------------------------------
# Registry sync tests (dry-run only — no chain access in tests)
# ---------------------------------------------------------------------------


class TestRegistrySync:
    """Tests for registry_sync.py (dry-run mode)."""

    async def test_register_agent_dry_run(self):
        """Register returns dry_run status when DRY_RUN is true."""
        from app.erc8004.registry_sync import register_agent

        result = await register_agent("https://moat.dev/.well-known/agent.json")

        assert result["status"] == "dry_run"
        assert result["agent_uri"] == "https://moat.dev/.well-known/agent.json"
        assert result["agent_id"] is None

    async def test_update_agent_uri_dry_run(self):
        """Update URI returns dry_run status."""
        from app.erc8004.registry_sync import update_agent_uri

        result = await update_agent_uri(42, "https://moat.dev/new-uri.json")

        assert result["status"] == "dry_run"
        assert result["agent_id"] == 42

    async def test_read_agent_uri_no_rpc(self):
        """Read returns None when no RPC is configured."""
        from app.erc8004.registry_sync import read_agent_uri

        result = await read_agent_uri(42)

        # No RPC URL set in tests → returns None
        assert result is None

    async def test_sync_new_agent_dry_run(self):
        """Sync a new agent (no erc8004_agent_id) triggers register."""
        from app.erc8004.registry_sync import sync_agent_to_chain

        agent = {
            "name": "new-agent",
            "description": "Brand new",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
        }

        result = await sync_agent_to_chain(
            agent,
            base_url="https://moat.dev",
        )

        assert result["action"] == "register"
        assert result["status"] == "dry_run"
        assert "new-agent" in result["agent_uri"]

    async def test_sync_agent_no_uri_skips(self):
        """Sync without URI and no base_url skips registration."""
        from app.erc8004.registry_sync import sync_agent_to_chain

        agent = {
            "name": "no-uri-agent",
            "description": "",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
        }

        result = await sync_agent_to_chain(agent, base_url="")

        assert result["action"] == "skip"

    async def test_sync_existing_agent_noop(self):
        """Sync existing agent with no URI change is noop."""
        from app.erc8004.registry_sync import sync_agent_to_chain

        agent = {
            "name": "existing-agent",
            "description": "",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
            "erc8004_agent_id": 42,
        }

        result = await sync_agent_to_chain(agent, base_url="")

        assert result["action"] == "noop"


# ---------------------------------------------------------------------------
# Gateway discovery endpoint tests
# ---------------------------------------------------------------------------


class TestGatewayDiscovery:
    """Tests for gateway's A2A and ERC-8004 discovery endpoints."""

    def test_well_known_agent_card(self, test_client):
        """GET /.well-known/agent.json returns gateway AgentCard."""
        resp = test_client.get("/.well-known/agent.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "moat-gateway"
        assert data["provider"]["organization"] == "Moat"
        assert len(data["skills"]) >= 2
        assert any(s["id"] == "execute" for s in data["skills"])
        assert any(s["id"] == "intents.inbound" for s in data["skills"])

    def test_well_known_agent_card_has_auth(self, test_client):
        """AgentCard includes authentication info."""
        resp = test_client.get("/.well-known/agent.json")
        data = resp.json()
        assert "authentication" in data
        assert "bearer" in data["authentication"]["schemes"]

    def test_erc8004_metadata_not_found(self, test_client):
        """ERC-8004 metadata 404 for unknown on-chain ID."""
        resp = test_client.get("/agents/erc8004/99999/metadata")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Intent listener tenant resolution tests
# ---------------------------------------------------------------------------


class TestDynamicTenantResolution:
    """Tests for the updated intent_listener tenant resolution."""

    def test_fallback_map_resolves_known_address(self):
        """The sync fallback still resolves the hardcoded address."""
        from app.intent_listener import _resolve_tenant

        tenant = _resolve_tenant("0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d")
        assert tenant == "automaton"

    def test_fallback_map_case_insensitive(self):
        """Address lookup is case-insensitive."""
        from app.intent_listener import _resolve_tenant

        tenant = _resolve_tenant("0x83be08ffb22b61733edf15b0ee9caf5562cd888d")
        assert tenant == "automaton"

    def test_unknown_address_returns_none(self):
        """Unknown address returns None."""
        from app.intent_listener import _resolve_tenant

        tenant = _resolve_tenant("0x0000000000000000000000000000000000000000")
        assert tenant is None

    async def test_async_resolver_falls_back(self):
        """Async resolver falls back to hardcoded map when control-plane is down."""
        from app.intent_listener import _resolve_tenant_from_registry

        # Control-plane is not running in tests → falls back
        tenant = await _resolve_tenant_from_registry(
            "0x83Be08FFB22b61733eDf15b0ee9Caf5562cd888d"
        )
        assert tenant == "automaton"

    async def test_async_resolver_unknown_address(self):
        """Async resolver returns None for unknown addresses."""
        from app.intent_listener import _resolve_tenant_from_registry

        tenant = await _resolve_tenant_from_registry(
            "0x0000000000000000000000000000000000000000"
        )
        assert tenant is None
