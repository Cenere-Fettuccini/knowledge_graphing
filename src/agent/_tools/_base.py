"""Base class + registry for agent tools.

Each concrete tool lives in its own file, sets a class-level ``name``,
``description``, and ``parameters`` (a JSON-schema dict for the LLM),
implements ``async def run(**kwargs) -> str``, and is auto-registered
when its module is imported. Looking up an unregistered name raises
``UnknownToolError`` — registration miss fails loudly rather than
silently dropping the tool.
"""

from __future__ import annotations

from typing import ClassVar

from src.agent._errors import UnknownToolError


class BaseTool:
    """Abstract tool. Subclasses set class-level metadata and override ``run``.

    Subclasses with a non-empty ``name`` are instantiated once at class
    creation time and stored in ``BaseTool._registry``.
    """

    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    parameters: ClassVar[dict] = {"type": "object", "properties": {}}

    _registry: ClassVar[dict[str, "BaseTool"]] = {}

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if not cls.name:
            return
        if cls.name in BaseTool._registry:
            raise ValueError(f"duplicate tool name: {cls.name!r}")
        BaseTool._registry[cls.name] = cls()

    @property
    def schema(self) -> dict:
        """OpenAI-style function-schema entry, derived from class metadata."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    async def run(self, **kwargs: object) -> str:
        """Execute the tool's core logic with the provided arguments and return a string result."""
        raise NotImplementedError

    @classmethod
    def identify(cls) -> dict:
        """Self-description usable for diagnostics / a future /flows page."""
        return {
            "kind": "tool",
            "name": cls.name,
            "description": cls.description,
            "parameters": cls.parameters,
        }

    @classmethod
    def get(cls, name: str) -> "BaseTool":
        """Retrieve a registered tool instance by name, or raise UnknownToolError."""
        try:
            return BaseTool._registry[name]
        except KeyError:
            raise UnknownToolError(
                f"no tool registered as {name!r}; available: {sorted(BaseTool._registry)}"
            ) from None

    @classmethod
    def all_names(cls) -> list[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(BaseTool._registry)
