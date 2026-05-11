from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryProtocol(Protocol):
    """Structural interface for the memory layer. Swap in any conforming implementation."""

    # ── Health ────────────────────────────────────────────────────────────────

    def status(self) -> dict: ...

    def invalidate_health_cache(self) -> None: ...

    def snapshot_health(self) -> dict: ...

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

    # ── Canonicalization (entity dedup) ──────────────────────────────────────

    def list_distinct_graph_labels(self, *, exclude: set | None = None) -> list: ...

    def list_named_nodes_by_label(
        self,
        label: str,
        *,
        exclude_roots: bool = True,
    ) -> list: ...

    def count_node_connections(self, node_ids: list) -> dict: ...

    def list_active_beliefs(self, limit: int = 1000) -> list: ...

    def create_merge_proposal(
        self,
        *,
        proposal_id: str,
        label: str,
        primary_id: str,
        duplicate_ids: list,
        scores: list,
        canonical_name: str,
    ) -> str: ...

    def list_merge_proposals(
        self,
        *,
        status: str = "pending",
        limit: int = 200,
    ) -> list: ...

    def get_merge_proposal(self, proposal_id: str) -> dict | None: ...

    def apply_merge_proposal(self, proposal_id: str) -> dict: ...

    def dismiss_merge_proposal(self, proposal_id: str) -> bool: ...

    # ── Analyzer queue (Chroma) ──────────────────────────────────────────────

    def list_unanalyzed(self, limit: int = 50) -> list: ...

    def count_unanalyzed(self) -> int: ...

    def mark_analyzed(self, memory_ids: list, run_id: str | None = None) -> int: ...

    def mark_failed(
        self,
        memory_ids: list,
        reason: str,
        run_id: str | None = None,
    ) -> int: ...

    def list_failed(self, limit: int = 50) -> list: ...

    def count_failed(self) -> int: ...

    def retry_failed(self, memory_ids: list | None = None) -> int: ...

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

    def batch_graph_writes(self): ...

    # ── Bootstrap ─────────────────────────────────────────────────────────────

    def user_root_exists(self) -> bool: ...

    def get_user_root(self) -> dict | None: ...

    def bootstrap_user_root(self, name: str) -> dict: ...

    # ── Rumination support ────────────────────────────────────────────────────

    def get_recent_memories(self, n: int = 100) -> list: ...

    def get_unanalyzed_beliefs(self, limit: int = 10) -> list: ...

    def mark_belief_deep_analyzed(self, belief_id: str) -> None: ...

    def upsert_belief(
        self,
        content: str,
        confidence: float = 0.8,
        *,
        about_entity_id: str | None = None,
        source_text: str | None = None,
    ) -> str: ...

    def is_graph_online(self) -> bool: ...

    def find_entity(self, name: str) -> str | None: ...

    def find_belief(self, keyword: str, *, active_only: bool = False) -> dict | None: ...

    def evolve_belief(self, old_id: str, new_content: str, reason: str = "") -> str: ...

    def search_nodes(self, query: str, limit: int = 10) -> list: ...

    def update_task(self, title_fragment: str, new_status: str = "", notes: str = "") -> str: ...
