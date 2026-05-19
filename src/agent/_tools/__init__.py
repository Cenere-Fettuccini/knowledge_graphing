"""Tool registry consumed by the agent loop.

Each tool is a small object with a ``name``, a JSON-schema description
the LLM sees, and an async ``run(**kwargs) -> str`` that the loop calls
when the LLM emits a matching tool call.

Tools must never crash the loop — they return their failure as a string
the LLM can read and react to. The loop additionally guards with a
top-level ``except Exception`` (see ``_loop._run_one_tool_call``).
"""

from __future__ import annotations

from typing import Protocol

from src.agent._tools.memory import RecallRecentTool


class Tool(Protocol):
    name: str
    schema: dict

    async def run(self, **kwargs) -> str: ...


_TOOLS: list[Tool] = [RecallRecentTool()]


def get_tools() -> list[Tool]:
    """Return the active tool list. Currently fixed; rebuilt only via tests."""
    return list(_TOOLS)


__all__ = ["Tool", "get_tools"]
