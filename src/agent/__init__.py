"""Public surface for the chat agent.

External callers see exactly six names: the ``AgentService`` Protocol,
the request/result dataclasses, the ``AgentRunError`` typed exception,
the ``RegistryLookupError`` family base, and the
``get_agent_service(name)`` factory. The concrete service class, the
loop, the agent / model / tool registries, and the individual agent /
model / tool definitions all live in underscore-prefixed submodules and
are not part of the contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from src.agent._errors import (
    AgentRunError,
    RegistryLookupError,
    UnknownAgentError,
    UnknownModelError,
    UnknownToolError,
)


@dataclass(frozen=True)
class AgentRunRequest:
    """One invocation of an agent.

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
    """Structural type of an agent singleton.

    Not a class to instantiate — call ``get_agent_service(name)``.
    """

    async def arun(self, request: AgentRunRequest) -> AgentRunResult: ...


DEFAULT_AGENT = "chat"


def get_agent_service(name: str = DEFAULT_AGENT) -> AgentService:
    """Return the shared service for ``name``.

    Each registered agent has its own singleton; the first call for a
    given name resolves the agent's declared model + tools through their
    registries and caches the resulting service. Raises
    ``UnknownAgentError`` / ``UnknownModelError`` / ``UnknownToolError``
    when a referenced name isn't registered.
    """
    from src.agent._service import _AgentService

    return _AgentService.get(name)


__all__ = [
    "AgentRunError",
    "AgentRunRequest",
    "AgentRunResult",
    "AgentService",
    "DEFAULT_AGENT",
    "RegistryLookupError",
    "UnknownAgentError",
    "UnknownModelError",
    "UnknownToolError",
    "get_agent_service",
]
