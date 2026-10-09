"""Tests for the MCP server itself - what a client sees.

The tool logic is tested in test_mcp_tools.py; these check the contract: the
tools an assistant is offered, that every one of them is declared read-only,
that errors arrive as readable tool errors, and that the server really speaks
MCP over stdio when launched the way Claude launches it - including that
nothing else is written to the wire.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp.client import Client  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

EXPECTED = {"portfolio", "book_summary", "look_through", "dividend_income",
            "retirement_projection", "quebec_tax", "etf_screener", "journal_summary"}


def _run(coro):
    return asyncio.run(coro)


def _server():
    from tradelab.mcp_server.server import server
    return server


def test_the_assistant_is_offered_exactly_these_tools():
    async def go():
        async with Client(_server()) as client:
            return {t.name for t in (await client.list_tools()).tools}
    assert _run(go()) == EXPECTED


def test_every_tool_is_declared_read_only_and_harmless():
    async def go():
        async with Client(_server()) as client:
            return (await client.list_tools()).tools
    for tool in _run(go()):
        a = tool.annotations
        assert a is not None, tool.name
        assert a.read_only_hint is True, tool.name
        assert a.destructive_hint is False, tool.name


def test_only_the_tools_that_download_say_they_reach_outside():
    async def go():
        async with Client(_server()) as client:
            return {t.name: t.annotations.open_world_hint
                    for t in (await client.list_tools()).tools}
    online = {name for name, hint in _run(go()).items() if hint}
    assert online == {"book_summary", "look_through", "dividend_income"}


def test_every_tool_explains_itself():
    async def go():
        async with Client(_server()) as client:
            return (await client.list_tools()).tools
    for tool in _run(go()):
        assert tool.description and len(tool.description) > 80, tool.name


def test_the_server_tells_the_assistant_the_ground_rules():
    from tradelab.mcp_server.server import INSTRUCTIONS
    assert "read-only" in INSTRUCTIONS
    assert "not financial advice" in INSTRUCTIONS
    assert "probability" in INSTRUCTIONS


def test_a_tool_call_returns_structured_numbers():
    async def go():
        async with Client(_server()) as client:
            return await client.call_tool("quebec_tax", {"income": 60_000, "age": 66})
    result = _run(go())
    assert not result.is_error
    data = result.structured_content
    assert data["total"] > 0 and data["tax_year"] == 2026


def test_a_problem_arrives_as_a_readable_tool_error(tmp_path, monkeypatch):
    from tradelab.core import config
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "absent.db")

    async def go():
        async with Client(_server()) as client:
            return await client.call_tool("portfolio", {})
    result = _run(go())
    assert result.is_error
    text = " ".join(getattr(c, "text", "") for c in result.content)
    assert "open the app once" in text


# -- launched the way Claude launches it --------------------------------------------

def test_it_speaks_mcp_over_stdio_from_the_launcher():
    """A real subprocess, real stdin/stdout. Any stray print at import time
    would corrupt the stream and this would fail to initialise."""
    from mcp.client.stdio import StdioServerParameters, get_default_environment
    env = get_default_environment()
    env.update({k: v for k, v in os.environ.items() if k.startswith("TRADELAB_")})
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(ROOT / "tradelab_mcp.py")], env=env)

    async def go():
        async with Client(params) as client:
            names = {t.name for t in (await client.list_tools()).tools}
            tax = await client.call_tool("quebec_tax", {"income": 45_000, "age": 70})
            return names, tax
    names, tax = _run(go())
    assert names == EXPECTED
    assert not tax.is_error and tax.structured_content["total"] > 0
