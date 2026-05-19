"""Shared fixtures for agent-module tests.

Every test gets:
- Fresh ``_AgentService`` and ``_MemoryManager`` singletons.
- A tmp ``CONVERSATION_LOG_DIR`` (the memory tool talks through the real
  public surface; tests use real on-disk storage so the tool round-trip
  is exercised).
- A tight ``AGENT_MAX_ITERATIONS`` cap so the iteration test runs fast.
- A ``FakeLLM`` that gets installed in place of the ``"lmstudio"`` entry
  in ``BaseModel._registry`` via ``monkeypatch.setitem`` — opt-in by
  requesting the ``fake_llm`` fixture.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterator

import pytest

from src.agent._models._base import BaseModel
from src.agent._service import _AgentService
from src.memory._manager import _MemoryManager


class FakeLLM:
    """A scripted LLM adapter. ``responses`` are popped in order.

    Each entry is either:
    - a dict shaped like ``{"content": str | None, "tool_calls": list | None}``
      (returned wrapped as ``{"message": ...}``); or
    - a callable taking ``(messages, tools)`` and returning that shape; or
    - an exception instance to raise.

    Deliberately *not* a ``BaseModel`` subclass — keeping ``name = ""``
    avoids auto-registration, so the fake only enters the registry when
    a test explicitly swaps it in. The duck-typed ``chat`` method
    matches the registry's structural contract.
    """

    name = ""
    description = "test double"

    def __init__(self) -> None:
        self.responses: list[Any] = []
        self.calls: list[tuple[list[dict], list[dict]]] = []

    def identify(self) -> dict:
        return {"kind": "model", "name": "fake", "description": self.description}

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
    yield
    _AgentService.reset_for_tests()
    _MemoryManager.reset_for_tests()


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
    """Replace the ``lmstudio`` registry entry with a FakeLLM for one test.

    Importing ``src.agent._models`` ensures the real adapter has
    registered first; ``monkeypatch.setitem`` then swaps in the fake and
    restores the original on teardown.
    """
    import src.agent._models  # noqa: F401 — ensures registry is populated

    llm = FakeLLM()
    monkeypatch.setitem(BaseModel._registry, "lmstudio", llm)
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
