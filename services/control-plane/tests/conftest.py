"""
Pytest fixtures for control-plane service tests.

Provides a TestClient with a temporary SQLite database.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Ensure control-plane service root is on sys.path so 'from app.xxx'
# resolves to this service's app package (not another service's).
_service_root = str(Path(__file__).resolve().parent.parent)
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)

# Set test environment before importing app
_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db")
os.close(_test_db_fd)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_db_path}"
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
