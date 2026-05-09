from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryProtocol(Protocol):
    """Structural interface for the memory layer. Swap in any conforming implementation."""

    def store(
        self,
        text,
        role: str,
        session_id: str,
        is_ephemeral: bool = False,
        **extra,
    ) -> str | None: ...

    def search(
        self,
        query: str,
        k: int = 5,
        session_id: str | None = None,
        include_ephemeral: bool = True,
    ) -> list: ...

    def get_history(self, session_id: str, limit: int = 20) -> list: ...

    def clear_ephemeral(self, session_id: str | None = None) -> None: ...

    def delete_session(self, session_id: str) -> bool: ...

    def status(self) -> dict: ...
