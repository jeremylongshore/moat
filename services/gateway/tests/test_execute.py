"""
Tests for the gateway execute endpoint.

Tests the full 10-step pipeline:
1. Fetch capability from control plane
2. Validate capability is active
3. Evaluate policy
4. Check idempotency
5. Resolve credential
6. Execute via adapter
7. Build receipt
8. Emit outcome event
9. Store in idempotency cache
10. Return receipt
"""

from __future__ import annotations


class TestExecuteHappyPath:
    """Test successful execution through the full pipeline."""

    def test_execute_with_stub_adapter(self, test_client):
        """Execute a capability with the stub adapter - full pipeline."""
        response = test_client.post(
            "/execute/test-cap-123",
            json={
                "tenant_id": "dev-tenant",
                "params": {"foo": "bar"},
                "scope": "execute",
            },
        )

        assert response.status_code == 200
        data = response.json()

        # Verify receipt structure
        assert data["capability_id"] == "test-cap-123"
        assert data["tenant_id"] == "dev-tenant"
        assert data["status"] == "success"
        assert "receipt_id" in data
        assert "executed_at" in data
        assert "latency_ms" in data
        assert data["cached"] is False

        # Verify stub adapter was called (echo_params in result)
        assert "result" in data
        assert data["result"].get("stub") is True
        assert data["result"].get("echo_params") == {"foo": "bar"}

    def test_execute_with_idempotency_key(self, test_client):
        """Idempotency key prevents duplicate execution."""
        request_body = {
            "tenant_id": "dev-tenant",
            "params": {"key": "value"},
            "scope": "execute",
            "idempotency_key": "unique-key-123",
        }

        # First request - executes normally
        resp1 = test_client.post("/execute/test-cap-123", json=request_body)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["cached"] is False
        receipt_id_1 = data1["receipt_id"]

        # Second request with same idempotency key - returns cached
        resp2 = test_client.post("/execute/test-cap-123", json=request_body)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["cached"] is True
        assert data2["receipt_id"] == receipt_id_1


class TestExecuteErrors:
    """Test error handling in the execute pipeline."""

    def test_capability_not_found(self, test_client):
        """404 when capability doesn't exist."""
        response = test_client.post(
            "/execute/nonexistent",
            json={"tenant_id": "dev-tenant", "params": {}},
        )

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()

    def test_capability_inactive(self, test_client):
        """403 when capability is not active."""
        response = test_client.post(
            "/execute/inactive-cap",
            json={"tenant_id": "dev-tenant", "params": {}},
        )

        assert response.status_code == 403
        assert "not active" in response.json()["detail"].lower()

    def test_missing_tenant_id(self, test_client):
        """422 when tenant_id is missing."""
        response = test_client.post(
            "/execute/test-cap-123",
            json={"params": {}},
        )

        assert response.status_code == 422


class TestHealthCheck:
    """Test gateway health endpoint."""

    def test_healthz(self, test_client):
        """Health check returns ok."""
        response = test_client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
        assert "moat-gateway" in response.json()["service"]
