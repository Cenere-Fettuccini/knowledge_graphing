"""Base class + registry for agent definitions.

An "agent" here is a triple — *prompt*, *model name*, *tool names* —
plus a stable identifier and a one-line description. Each concrete
agent lives in its own file and is auto-registered on class creation;
looking up an unregistered name raises ``UnknownAgentError``.

Agents are pure data (class attributes). The runtime wiring — turning
``model: "lmstudio"`` and ``tools: ["recall_recent"]`` into actual
instances and driving the loop — happens in ``_service`` / ``_loop``.
"""

from __future__ import annotations

from typing import ClassVar

from src.agent._errors import UnknownAgentError


class BaseAgent:
    """Abstract agent definition. Subclasses set class-level metadata."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    prompt: ClassVar[str] = ""
    model: ClassVar[str] = ""
    tools: ClassVar[list[str]] = []

    _registry: ClassVar[dict[str, type["BaseAgent"]]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            return
        if cls.name in BaseAgent._registry:
            raise ValueError(f"duplicate agent name: {cls.name!r}")
        if not cls.prompt:
            raise ValueError(f"agent {cls.name!r} must define a non-empty prompt")
        if not cls.model:
            raise ValueError(f"agent {cls.name!r} must declare a model name")
        BaseAgent._registry[cls.name] = cls

    @classmethod
    def identify(cls) -> dict:
        """Return a dictionary of metadata describing the agent."""
        return {
            "kind": "agent",
            "name": cls.name,
            "description": cls.description,
            "model": cls.model,
            "tools": list(cls.tools),
            "prompt_chars": len(cls.prompt),
        }

    @classmethod
    def get(cls, name: str) -> type["BaseAgent"]:
        """Retrieve a registered agent class by name, or raise UnknownAgentError."""
        try:
            return BaseAgent._registry[name]
        except KeyError:
            raise UnknownAgentError(
                f"no agent registered as {name!r}; available: {sorted(BaseAgent._registry)}"
            ) from None

    @classmethod
    def all_names(cls) -> list[str]:
        """Return a sorted list of all registered agent names."""
        return sorted(BaseAgent._registry)
