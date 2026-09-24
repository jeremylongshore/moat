"""The stdio server registers its tools through the MCP SDK 2.x constructor API.

Until 2026-09 it used the 1.x decorators, which 2.x removed; the server then
crashed at import on any fresh install while this suite stayed green because
nothing imported it. These tests import it and exercise both handlers.
"""

from __future__ import annotations

import json

import pytest
from mcp.types import CallToolRequestParams

from app import stdio_server as srv
from app.tool_definitions import TOOL_SCHEMAS

pytestmark = pytest.mark.anyio


async def test_list_tools_returns_every_defined_tool():
    result = await srv._on_list_tools(None, None)
    assert [t.name for t in result.tools] == [s["name"] for s in TOOL_SCHEMAS]
    assert len(result.tools) == len(TOOL_SCHEMAS) > 0


async def test_unknown_tool_is_a_normal_error_payload():
    result = await srv._on_call_tool(None, CallToolRequestParams(name="nope", arguments={}))
    assert not result.is_error
    assert json.loads(result.content[0].text) == {"error": "Unknown tool: nope"}


async def test_a_raising_tool_becomes_is_error_not_a_protocol_failure(monkeypatch):
    async def boom(*_a, **_k):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(srv, "tp_get_stats", boom)
    result = await srv._on_call_tool(
        None, CallToolRequestParams(name="capabilities.stats", arguments={"capability_id": "x"})
    )
    assert result.is_error
    assert "upstream down" in result.content[0].text


def test_server_is_constructed_with_handlers():
    assert srv.server.get_request_handler("tools/list") is not None
    assert srv.server.get_request_handler("tools/call") is not None
