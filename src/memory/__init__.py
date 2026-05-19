"""Public surface for the conversation memory module.

The two names below are the entire public API. External callers must
not import any underscore-prefixed module from this package.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from src.memory._manager import _MemoryManager

Role = Literal["user", "assistant"]


@runtime_checkable
class MemoryManager(Protocol):
    """Structural type of the conversation memory singleton.

    See ``src/memory/CLAUDE.md`` for the contract. This Protocol is not
    a class to instantiate — call ``get_memory_manager()`` instead.
    """

    def append(
        self,
        session_id: str,
        role: Role,
        text: str,
        *,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> str: ...

    def recent_turns(
        self,
        session_id: str,
        *,
        leaf_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]: ...

    def list_branches(self, session_id: str) -> list[dict]: ...

    def set_active(self, session_id: str, leaf_id: str) -> None: ...

    def active_leaf(self, session_id: str) -> str | None: ...

    def list_sessions(self) -> list[dict]: ...

    def delete_session(self, session_id: str) -> None: ...

    def status(self) -> dict: ...


def get_memory_manager() -> MemoryManager:
    """Return the shared MemoryManager. Constructs it on first call."""
    return _MemoryManager.get()


__all__ = ["MemoryManager", "get_memory_manager"]
