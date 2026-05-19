"""Base class + registry for LLM model adapters.

Each concrete adapter lives in its own file, sets a class-level
``name``, implements ``async def chat(messages, tools) -> dict``, and
is auto-registered as a singleton instance on class creation. Lookups
go through ``BaseModel.get(name)``; an unregistered name raises
``UnknownModelError``.

Adapters must wrap any transport / protocol failure in
``AgentRunError`` so the loop sees a single error type regardless of
which provider is configured.
"""

from __future__ import annotations

from typing import ClassVar

from src.agent._errors import UnknownModelError


class BaseModel:
    """Abstract LLM adapter. Subclasses override ``chat``."""

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""

    _registry: ClassVar[dict[str, "BaseModel"]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            return
        if cls.name in BaseModel._registry:
            raise ValueError(f"duplicate model name: {cls.name!r}")
        BaseModel._registry[cls.name] = cls()

    async def chat(self, messages: list[dict], tools: list[dict]) -> dict:
        """Return ``{"message": {"content": str | None, "tool_calls": list | None}}``."""
        raise NotImplementedError

    @classmethod
    def identify(cls) -> dict:
        """Return a dictionary of metadata describing the model adapter."""
        return {"kind": "model", "name": cls.name, "description": cls.description}

    @classmethod
    def get(cls, name: str) -> "BaseModel":
        """Retrieve a registered model instance by name, or raise UnknownModelError."""
        try:
            return BaseModel._registry[name]
        except KeyError:
            raise UnknownModelError(
                f"no model registered as {name!r}; available: {sorted(BaseModel._registry)}"
            ) from None

    @classmethod
    def all_names(cls) -> list[str]:
        """Return a sorted list of all registered model names."""
        return sorted(BaseModel._registry)
