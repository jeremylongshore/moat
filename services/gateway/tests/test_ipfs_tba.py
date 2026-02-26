"""
Tests for IPFS pinning and ERC-6551 Token Bound Accounts.

All tests run in dry-run mode — no actual IPFS or chain access.
"""


# ---------------------------------------------------------------------------
# IPFS pinning tests
# ---------------------------------------------------------------------------


class TestIPFSPinning:
    """Tests for IPFS pin operations (dry-run mode)."""

    async def test_pin_json_dry_run(self):
        """Pin JSON in dry-run mode returns deterministic CID."""
        from app.erc8004.ipfs import pin_json

        result = await pin_json({"test": "data"}, name="test-pin")

        assert result["status"] == "dry_run"
        assert result["ipfs_hash"].startswith("bafybeig")
        assert "gateway.pinata.cloud" in result["gateway_url"]
        assert result["size"] > 0

    async def test_pin_json_deterministic(self):
        """Same input produces same CID in dry-run."""
        from app.erc8004.ipfs import pin_json

        data = {"name": "test-agent", "version": "1.0.0"}

        r1 = await pin_json(data, name="test")
        r2 = await pin_json(data, name="test")

        assert r1["ipfs_hash"] == r2["ipfs_hash"]

    async def test_pin_json_different_data(self):
        """Different input produces different CID."""
        from app.erc8004.ipfs import pin_json

        r1 = await pin_json({"a": 1}, name="test")
        r2 = await pin_json({"b": 2}, name="test")

        assert r1["ipfs_hash"] != r2["ipfs_hash"]

    async def test_pin_agent_metadata(self):
        """Pin agent metadata returns metadata + pin info."""
        from app.erc8004.ipfs import pin_agent_metadata

        agent = {
            "name": "ipfs-test-agent",
            "description": "Testing IPFS pinning",
            "url": "http://localhost:9000",
            "version": "0.1.0",
            "status": "active",
            "skills": [],
        }

        result = await pin_agent_metadata(agent)

        assert "metadata" in result
        assert "pin" in result
        assert result["pin"]["status"] == "dry_run"
        assert result["agent_uri"].startswith("https://")
        assert result["metadata"]["name"] == "ipfs-test-agent"

    async def test_pin_service_catalog(self):
        """Pin a full service catalog."""
        from app.erc8004.ipfs import pin_service_catalog

        agents = [
            {"name": "agent-1", "description": "First", "url": "http://a1:9000"},
            {"name": "agent-2", "description": "Second", "url": "http://a2:9000"},
        ]

        result = await pin_service_catalog(agents)

        assert result["status"] == "dry_run"
        assert result["ipfs_hash"].startswith("bafybeig")


# ---------------------------------------------------------------------------
# ERC-6551 TBA tests
# ---------------------------------------------------------------------------


class TestERC6551TBA:
    """Tests for ERC-6551 Token Bound Account operations (dry-run mode)."""

    async def test_create_tba_dry_run(self):
        """Create TBA in dry-run mode returns deterministic address."""
        from app.erc8004.tba import create_tba

        result = await create_tba(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=42,
        )

        assert result["status"] == "dry_run"
        assert result["tba_address"].startswith("0x")
        assert len(result["tba_address"]) == 42
        assert result["token_id"] == 42

    async def test_create_tba_deterministic(self):
        """Same input produces same TBA address in dry-run."""
        from app.erc8004.tba import create_tba

        r1 = await create_tba(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=42,
        )
        r2 = await create_tba(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=42,
        )

        assert r1["tba_address"] == r2["tba_address"]

    async def test_create_tba_different_tokens(self):
        """Different token IDs produce different TBA addresses."""
        from app.erc8004.tba import create_tba

        r1 = await create_tba(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=1,
        )
        r2 = await create_tba(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=2,
        )

        assert r1["tba_address"] != r2["tba_address"]

    async def test_ensure_agent_tba_with_identity(self):
        """ensure_agent_tba creates TBA for agent with on-chain ID."""
        from app.erc8004.tba import ensure_agent_tba

        agent = {
            "name": "tba-agent",
            "erc8004_agent_id": 42,
        }

        result = await ensure_agent_tba(
            agent,
            identity_registry="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
        )

        assert result["status"] == "dry_run"
        assert result["tba_address"].startswith("0x")

    async def test_ensure_agent_tba_without_identity(self):
        """ensure_agent_tba skips agent without on-chain ID."""
        from app.erc8004.tba import ensure_agent_tba

        agent = {"name": "no-chain-agent"}

        result = await ensure_agent_tba(
            agent,
            identity_registry="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
        )

        assert result["status"] == "skip"

    async def test_compute_tba_address_no_rpc(self):
        """compute_tba_address returns None without RPC."""
        from app.erc8004.tba import compute_tba_address

        addr = compute_tba_address(
            token_contract="0xD66A1e880AA3939CA066a9EA1dD37ad3d01D977c",
            token_id=42,
        )

        assert addr is None
