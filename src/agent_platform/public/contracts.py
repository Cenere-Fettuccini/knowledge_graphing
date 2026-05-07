from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentRunRequest:
    app_id: str
    user_id: str
    session_id: str
    message: str
    prompt_text: str | None = None
    store_text: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    app_id: str
    session_id: str
    reply: str


@dataclass(frozen=True)
class AgentStatus:
    status: str
    llm: str
    memory: dict[str, Any]
