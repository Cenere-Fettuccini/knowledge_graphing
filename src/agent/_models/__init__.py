"""Active LLM adapter for the agent loop.

A single adapter is built on first call to ``get_llm`` and reused.
Adapters are private to the agent package; the public Protocol is just
the structural ``LLMAdapter`` shape used inside this module.
"""

from __future__ import annotations

from typing import Protocol

from src.agent._models.lmstudio import LMStudioAdapter


class LLMAdapter(Protocol):
    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Send one chat completion request.

        Returns a dict shaped as ``{"message": {"content": str | None,
        "tool_calls": list[dict] | None}}``. Adapters must raise
        ``AgentRunError`` on transport/protocol failure rather than
        propagating provider-specific exceptions.
        """


_adapter: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    global _adapter
    if _adapter is None:
        _adapter = LMStudioAdapter()
    return _adapter


def reset_for_tests() -> None:
    """Drop the cached adapter. Test seam."""
    global _adapter
    _adapter = None


__all__ = ["LLMAdapter", "get_llm", "reset_for_tests"]
