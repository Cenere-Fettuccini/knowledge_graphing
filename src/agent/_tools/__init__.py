"""Tool registry.

Importing this package imports every concrete tool module, which fires
``__init_subclass__`` and populates ``BaseTool._registry``. External
callers use ``get_tool(name)`` / ``all_tools()``.
"""

from __future__ import annotations

from src.agent._tools import _memory  # noqa: F401 — side-effect: registers
from src.agent._tools._base import BaseTool


def get_tool(name: str) -> BaseTool:
    """Return the registered tool instance, or raise ``UnknownToolError``."""
    return BaseTool.get(name)


def all_tools() -> list[BaseTool]:
    """Return every registered tool, sorted by name."""
    return [BaseTool.get(n) for n in BaseTool.all_names()]


__all__ = ["BaseTool", "all_tools", "get_tool"]
