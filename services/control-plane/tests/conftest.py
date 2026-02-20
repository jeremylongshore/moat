"""
Pytest fixtures for control-plane service tests.

Provides a TestClient with a temporary SQLite database.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from typing import Any

import pytest

# Set test environment before importing app
_test_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db.name}"
os.environ["MOAT_AUTH_DISABLED"] = "true"  # Disable auth for tests


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def test_client() -> Iterator[Any]:
    """Create a TestClient with a fresh test database."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
