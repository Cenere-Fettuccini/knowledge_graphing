from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRunRequest:
    app_id: str
    user_id: str
    session_id: str
    message: str
    message_timestamp: str | None = None
    prompt_text: str | None = None
    store_text: str | None = None
    store_metadata: dict[str, Any] = field(default_factory=dict)
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    app_id: str
    session_id: str
    reply: str
    reply_timestamp: str | None = None


@dataclass(frozen=True)
class AgentStatus:
    status: str
    llm: str
    memory: dict[str, Any]


@dataclass(frozen=True)
class MemorySearchRequest:
    """Typed contract for semantic memory searches.

    Use instead of calling ``memory_manager.search()`` with raw kwargs so that
    callers have a documented, stable interface to program against.
    """

    query: str
    session_id: str | None = None
    k: int = 5
    include_ephemeral: bool = True
