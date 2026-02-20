"""
Tests for the control-plane capabilities API.
"""

from __future__ import annotations


class TestCapabilitiesCRUD:
    """Test capability create, read, update operations."""

    def test_create_capability(self, test_client):
        """Create a new capability."""
        response = test_client.post(
            "/capabilities",
            json={
                "name": "Test Capability",
                "description": "A test capability for unit tests",
                "provider": "test-provider",
                "version": "1.0.0",
                "input_schema": {"type": "object"},
                "output_schema": {"type": "object"},
                "tags": ["test", "unit"],
                "status": "active",
            },
        )

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Capability"
        assert data["provider"] == "test-provider"
        assert data["version"] == "1.0.0"
        assert data["status"] == "active"
        assert "capability_id" in data
        assert "created_at" in data

    def test_get_capability(self, test_client):
        """Get a capability by ID."""
        # First create one
        create_resp = test_client.post(
            "/capabilities",
            json={
                "name": "Get Test",
                "description": "Test for GET",
                "provider": "test",
                "version": "1.0.0",
            },
        )
        cap_id = create_resp.json()["capability_id"]

        # Then get it
        get_resp = test_client.get(f"/capabilities/{cap_id}")
        assert get_resp.status_code == 200
        assert get_resp.json()["capability_id"] == cap_id
        assert get_resp.json()["name"] == "Get Test"

    def test_get_capability_not_found(self, test_client):
        """404 when capability doesn't exist."""
        response = test_client.get("/capabilities/nonexistent-id")
        assert response.status_code == 404

    def test_list_capabilities(self, test_client):
        """List all capabilities."""
        # Create a few
        for i in range(3):
            test_client.post(
                "/capabilities",
                json={
                    "name": f"List Test {i}",
                    "description": "For listing",
                    "provider": "list-provider",
                    "version": "1.0.0",
                },
            )

        response = test_client.get("/capabilities")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "total" in data
        assert data["total"] >= 3

    def test_list_capabilities_filter_by_provider(self, test_client):
        """Filter capabilities by provider."""
        # Create capabilities with different providers
        test_client.post(
            "/capabilities",
            json={
                "name": "Provider A",
                "description": "Test",
                "provider": "provider-a",
                "version": "1.0.0",
            },
        )
        test_client.post(
            "/capabilities",
            json={
                "name": "Provider B",
                "description": "Test",
                "provider": "provider-b",
                "version": "1.0.0",
            },
        )

        response = test_client.get("/capabilities?provider=provider-a")
        assert response.status_code == 200
        for item in response.json()["items"]:
            assert item["provider"] == "provider-a"

    def test_update_capability_status(self, test_client):
        """Update capability status."""
        # Create
        create_resp = test_client.post(
            "/capabilities",
            json={
                "name": "Status Test",
                "description": "Test",
                "provider": "test",
                "version": "1.0.0",
                "status": "active",
            },
        )
        cap_id = create_resp.json()["capability_id"]

        # Update status
        update_resp = test_client.patch(
            f"/capabilities/{cap_id}/status?new_status=deprecated"
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["status"] == "deprecated"

        # Verify change persisted
        get_resp = test_client.get(f"/capabilities/{cap_id}")
        assert get_resp.json()["status"] == "deprecated"


class TestCapabilitiesValidation:
    """Test input validation for capabilities API."""

    def test_create_missing_required_fields(self, test_client):
        """422 when required fields are missing."""
        response = test_client.post(
            "/capabilities",
            json={"name": "Incomplete"},
        )
        assert response.status_code == 422

    def test_create_invalid_version(self, test_client):
        """422 when version is not semver."""
        response = test_client.post(
            "/capabilities",
            json={
                "name": "Bad Version",
                "description": "Test",
                "provider": "test",
                "version": "not-semver",
            },
        )
        assert response.status_code == 422

    def test_create_invalid_status(self, test_client):
        """422 when status is not a valid value."""
        response = test_client.post(
            "/capabilities",
            json={
                "name": "Bad Status",
                "description": "Test",
                "provider": "test",
                "version": "1.0.0",
                "status": "invalid-status",
            },
        )
        assert response.status_code == 422


class TestHealthCheck:
    """Test control-plane health endpoint."""

    def test_healthz(self, test_client):
        """Health check returns ok."""
        response = test_client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
