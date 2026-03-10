"""Tests for MCP server tool registration."""
import asyncio
import pytest
from cdawebmcp.server import create_server


def test_server_has_five_tools():
    """Verify all 5 MCP tools are registered."""
    server = create_server()
    tools = asyncio.run(server.list_tools())
    tool_names = [t.name for t in tools]
    assert "browse_missions" in tool_names
    assert "load_mission" in tool_names
    assert "browse_parameters" in tool_names
    assert "fetch_data" in tool_names
    assert "manage_cache" in tool_names
    assert len(tool_names) == 5
