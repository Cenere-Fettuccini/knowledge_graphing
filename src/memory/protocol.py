from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryProtocol(Protocol):
    """Structural interface for the memory layer. Swap in any conforming implementation."""

    # ── Health ────────────────────────────────────────────────────────────────

    def status(self) -> dict: ...

    def invalidate_health_cache(self) -> None: ...

    # ── Conversation memory (ChromaDB) ────────────────────────────────────────

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

    def list_sessions(self, limit: int = 500) -> dict: ...

    def clear_ephemeral(self, session_id: str | None = None) -> None: ...

    def delete_session(self, session_id: str) -> bool: ...

    # ── Knowledge graph (Neo4j) ───────────────────────────────────────────────

    def graph_overview(self, limit: int = 100) -> dict: ...

    def graph_node_detail(self, node_id: str) -> dict: ...

    def graph_node_provenance(self, node_id: str) -> dict: ...

    def graph_active_tasks(self) -> list: ...

    def graph_belief_trail(self, belief_id: str) -> dict: ...

    # ── Analyzer queue (Chroma) ──────────────────────────────────────────────

    def list_unanalyzed(self, limit: int = 50) -> list: ...

    def count_unanalyzed(self) -> int: ...

    def mark_analyzed(self, memory_ids: list, run_id: str | None = None) -> int: ...

    # ── Analyzer graph writes (Neo4j) ────────────────────────────────────────

    def graph_schema_snapshot(self) -> dict: ...

    def upsert_node(
        self,
        *,
        node_id: str,
        labels: list,
        name: str,
        properties: dict | None = None,
    ) -> str: ...

    def upsert_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict | None = None,
    ) -> bool: ...

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def user_root_exists(self) -> bool: ...

    def get_user_root(self) -> dict | None: ...

    def bootstrap_user_root(self, name: str) -> dict: ...
