"""Public surface for the chat agent.

External callers see exactly five names: the ``AgentService`` Protocol,
the request/result dataclasses, the ``AgentRunError`` typed exception,
and the ``get_agent_service`` factory. The concrete service class and
the loop / tool / model adapters live in underscore-prefixed modules
and are not part of the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.agent._errors import AgentRunError


@dataclass(frozen=True)
class AgentRunRequest:
    """One invocation of the chat agent.

    ``history`` is oldest-first and includes the latest user message at
    the tip — the orchestrator (``backend.conversation``) is responsible
    for fetching it from memory. The agent does not read its own base
    history; tools it invokes may still query memory for other purposes.
    """

    session_id: str
    text: str
    history: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AgentRunResult:
    reply: str
    session_id: str
    reply_timestamp: str | None = None


@runtime_checkable
class AgentService(Protocol):
    """Structural type of the agent singleton.

    Not a class to instantiate — call ``get_agent_service()`` instead.
    """

    async def arun(self, request: AgentRunRequest) -> AgentRunResult: ...


def get_agent_service() -> AgentService:
    """Return the shared AgentService. Constructs it on first call."""
    from src.agent._service import _AgentService

    return _AgentService.get()


__all__ = [
    "AgentRunError",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentService",
    "get_agent_service",
]
