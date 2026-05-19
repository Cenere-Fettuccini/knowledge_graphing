"""Agent registry.

Importing this package imports every concrete agent module, which
fires ``__init_subclass__`` and populates ``BaseAgent._registry``.
External callers use ``get_agent_def(name)`` / ``all_agents()``.

Agents are pure data — the runtime wiring (model + tool instances,
loop driver) lives in ``_service`` / ``_loop``.
"""

from __future__ import annotations

from src.agent._agents import chat as _chat  # noqa: F401 — side-effect: registers
from src.agent._agents._base import BaseAgent


def get_agent_def(name: str) -> type[BaseAgent]:
    """Return the registered agent class, or raise ``UnknownAgentError``."""
    return BaseAgent.get(name)


def all_agents() -> list[type[BaseAgent]]:
    """Return every registered agent class, sorted by name."""
    return [BaseAgent.get(n) for n in BaseAgent.all_names()]


__all__ = ["BaseAgent", "all_agents", "get_agent_def"]
