"""
Pytest fixtures for gateway service tests.

Provides a TestClient with mocked upstream services (control-plane, trust-plane)
and a temporary SQLite database for the idempotency store.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure gateway service root is on sys.path so 'from app.xxx' resolves
# to this service's app package (not another service's).
_service_root = str(Path(__file__).resolve().parent.parent)
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)
import tempfile
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

# Set test environment before importing app
_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
os.close(_test_db_fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"
os.environ["MOAT_AUTH_DISABLED"] = "true"  # Disable auth for tests


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def _mock_capability(
    capability_id: str, status: str = "active", provider: str = "stub"
) -> dict:
    """Generate a mock capability response."""
    return {
        "capability_id": capability_id,
        "name": f"Test {capability_id}",
        "description": "A test capability",
        "provider": provider,
        "version": "1.0.0",
        "input_schema": {},
        "output_schema": {},
        "status": status,
        "tags": [],
        "created_at": "2024-01-01T00:00:00Z",
    }


@pytest.fixture
def mock_get_capability() -> Iterator[AsyncMock]:
    """Mock the capability cache's get_capability function."""

    async def _get_capability(capability_id: str) -> dict | None:
        if capability_id == "test-cap-123":
            return _mock_capability("test-cap-123")
        if capability_id == "slack-cap-123":
            return _mock_capability("slack-cap-123", provider="slack")
        if capability_id == "inactive-cap":
            return _mock_capability("inactive-cap", status="inactive")
        return None

    with patch(
        "app.routers.execute.get_capability", side_effect=_get_capability
    ) as mock:
        yield mock


@pytest.fixture
def mock_emit_outcome() -> Iterator[AsyncMock]:
    """Mock the outcome event emission to trust plane."""
    with patch(
        "app.routers.execute._emit_outcome_event", new_callable=AsyncMock
    ) as mock:
        yield mock


@pytest.fixture
def test_client(
    mock_get_capability: AsyncMock,
    mock_emit_outcome: AsyncMock,
) -> Iterator[Any]:
    """Create a TestClient with mocked upstream services."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
