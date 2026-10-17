"""The MCP server, spoken to over stdio like an agent would: tools only, no database credentials."""

from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest

from codebook.board import BoardView
from codebook.harness import board_for_seed

pytestmark = pytest.mark.contract


async def _session_calls(env: dict) -> tuple[list[str], list[dict]]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=sys.executable, args=["-m", "codebook.cli", "mcp"], env=env)
    words, key = board_for_seed(8001)
    board = BoardView.from_harness(words, key)
    args = {"partner": "mcp-test", "team": list(board.team), "opponent": list(board.with_role("opponent")),
            "neutral": list(board.with_role("neutral")), "assassin": board.assassin, "memory_of": "everyone",
            "limit": 3}
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = sorted(t.name for t in (await session.list_tools()).tools)
            result = await session.call_tool("suggest_clues", args)
            options = [json.loads(c.text) for c in result.content]
    return tools, options


def test_agent_gets_tools_and_suggestions_without_credentials(population, test_settings):
    env = dict(os.environ)
    env["CODEBOOK_DB_INDEX"] = str(test_settings.db_index)
    env["CODEBOOK_DB_PORT"] = str(test_settings.db_port)
    tools, options = asyncio.run(_session_calls(env))
    assert tools == ["check_clue", "end_game", "list_partners", "partner_memory", "record_turn", "suggest_clues"]
    assert options and all({"clue", "count", "targets", "p_assassin"} <= set(o) for o in options)
