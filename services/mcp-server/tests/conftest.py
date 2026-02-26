"""
Pytest fixtures for mcp-server service tests.

Provides a TestClient with auth disabled.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

# Ensure mcp-server service root is on sys.path so 'from app.xxx'
# resolves to this service's app package.
_service_root = str(Path(__file__).resolve().parent.parent)
if _service_root not in sys.path:
    sys.path.insert(0, _service_root)

# Disable auth for tests
os.environ["MOAT_AUTH_DISABLED"] = "true"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def test_client() -> Iterator[Any]:
    """Create a TestClient for the MCP server."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        yield client
