"""
Tests for the control-plane connections API.
"""

from __future__ import annotations


class TestConnectionsCRUD:
    """Test connection create, read operations."""

    def test_store_credential(self, test_client):
        """Store a credential and get a reference."""
        response = test_client.post(
            "/connections/store-credential",
            json={
                "tenant_id": "dev-tenant",
                "provider": "openai",
                "credential_value": "sk-test-secret-key",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["tenant_id"] == "dev-tenant"
        assert data["provider"] == "openai"
        assert "credential_reference" in data
        # Credential value should NOT be in response
        assert "sk-test" not in str(data)

    def test_create_connection(self, test_client):
        """Create a connection with a credential reference."""
        # First store a credential
        cred_resp = test_client.post(
            "/connections/store-credential",
            json={
                "tenant_id": "dev-tenant",
                "provider": "anthropic",
                "credential_value": "sk-ant-secret",
            },
        )
        cred_ref = cred_resp.json()["credential_reference"]

        # Create connection
        conn_resp = test_client.post(
            "/connections",
            json={
                "tenant_id": "dev-tenant",
                "provider": "anthropic",
                "credential_reference": cred_ref,
                "display_name": "My Anthropic Key",
            },
        )

        assert conn_resp.status_code == 201
        data = conn_resp.json()
        assert data["tenant_id"] == "dev-tenant"
        assert data["provider"] == "anthropic"
        assert data["display_name"] == "My Anthropic Key"
        assert "connection_id" in data

    def test_get_connection(self, test_client):
        """Get a connection by ID."""
        # Create one first
        cred_resp = test_client.post(
            "/connections/store-credential",
            json={
                "tenant_id": "dev-tenant",
                "provider": "slack",
                "credential_value": "xoxb-token",
            },
        )
        conn_resp = test_client.post(
            "/connections",
            json={
                "tenant_id": "dev-tenant",
                "provider": "slack",
                "credential_reference": cred_resp.json()["credential_reference"],
            },
        )
        conn_id = conn_resp.json()["connection_id"]

        # Get it
        get_resp = test_client.get(f"/connections/{conn_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["connection_id"] == conn_id

    def test_get_connection_not_found(self, test_client):
        """404 when connection doesn't exist."""
        response = test_client.get("/connections/nonexistent")
        assert response.status_code == 404

    def test_list_connections(self, test_client):
        """List all connections."""
        response = test_client.get("/connections")
        assert response.status_code == 200
        assert "items" in response.json()
        assert "total" in response.json()

    def test_list_connections_filter_by_tenant(self, test_client):
        """Filter connections by tenant_id (uses X-Tenant-ID with auth disabled)."""
        # Create connections for different tenants
        for tenant in ["tenant-a", "tenant-b"]:
            cred_resp = test_client.post(
                "/connections/store-credential",
                headers={"X-Tenant-ID": tenant},
                json={
                    "tenant_id": tenant,
                    "provider": "test",
                    "credential_value": "secret",
                },
            )
            test_client.post(
                "/connections",
                headers={"X-Tenant-ID": tenant},
                json={
                    "tenant_id": tenant,
                    "provider": "test",
                    "credential_reference": cred_resp.json()["credential_reference"],
                },
            )

        response = test_client.get(
            "/connections?tenant_id=tenant-a",
            headers={"X-Tenant-ID": "tenant-a"},
        )
        assert response.status_code == 200
        for item in response.json()["items"]:
            assert item["tenant_id"] == "tenant-a"


class TestConnectionsValidation:
    """Test input validation for connections API."""

    def test_create_connection_missing_fields(self, test_client):
        """422 when required fields are missing."""
        response = test_client.post(
            "/connections",
            json={"tenant_id": "dev-tenant"},
        )
        assert response.status_code == 422
