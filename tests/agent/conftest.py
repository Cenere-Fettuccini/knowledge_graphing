"""Shared fixtures for agent-module tests.

Every test gets:
- A fresh ``_AgentService`` singleton.
- A fresh ``_MemoryManager`` singleton plus a tmp ``CONVERSATION_LOG_DIR``
  (the memory tool talks through the real public surface; tests use
  real on-disk storage so the tool round-trip is exercised).
- A ``FakeLLM`` adapter installed in place of the LM Studio client, with
  a tight default ``AGENT_MAX_ITERATIONS`` cap (overridable per-test).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from src.agent import _models as agent_models
from src.agent._service import _AgentService
from src.memory._manager import _MemoryManager


class FakeLLM:
    """A scripted LLM adapter. ``responses`` are popped in order.

    Each entry is either:
    - a dict shaped like ``{"content": str | None, "tool_calls": list | None}``
      (returned wrapped as ``{"message": ...}``); or
    - a callable taking ``(messages, tools)`` and returning that shape; or
    - an exception instance to raise.
    """

    def __init__(self) -> None:
        self.responses: list[Any] = []
        self.calls: list[tuple[list[dict], list[dict]]] = []

    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        self.calls.append((list(messages), list(tools)))
        if not self.responses:
            raise AssertionError("FakeLLM ran out of scripted responses")
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            item = item(messages, tools)
        return {"message": item}


@pytest.fixture(autouse=True)
def _reset_singletons() -> Iterator[None]:
    _AgentService.reset_for_tests()
    _MemoryManager.reset_for_tests()
    agent_models.reset_for_tests()
    yield
    _AgentService.reset_for_tests()
    _MemoryManager.reset_for_tests()
    agent_models.reset_for_tests()


@pytest.fixture(autouse=True)
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "conversations"
    monkeypatch.setenv("CONVERSATION_LOG_DIR", str(d))
    return d


@pytest.fixture(autouse=True)
def _tight_iteration_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests fast — most flows need at most a couple of iterations."""
    monkeypatch.setenv("AGENT_MAX_ITERATIONS", "4")


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLM:
    """Install a FakeLLM in place of the LM Studio adapter and return it."""
    llm = FakeLLM()
    monkeypatch.setattr(agent_models, "_adapter", llm)
    return llm


@pytest.fixture
def text_response() -> Callable[[str], dict]:
    """Helper to build a plain-text LLM response."""
    return lambda content: {"content": content, "tool_calls": None}


@pytest.fixture
def tool_call_response() -> Callable[..., dict]:
    """Helper to build a tool-call LLM response."""
    def _build(name: str, arguments: str, call_id: str = "call_1") -> dict:
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": name, "arguments": arguments},
                }
            ],
        }

    return _build
