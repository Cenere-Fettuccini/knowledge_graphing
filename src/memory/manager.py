"""Unified facade over all memory stores — the only import other modules need."""

import json
import logging
import time
from src.memory.stores.chroma_store import ChromaStore
from src.memory.stores.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Single entry-point for all memory operations.
    Hides backend details (Chroma, Neo4j) behind a clean API.
    """

    def __init__(self, persist_path=None):
        self.chroma = ChromaStore(persist_path=persist_path)
        self.neo4j = Neo4jStore()
        
        # Cached health status to avoid pinging backends on every call
        self._health_cache = {}
        self._health_cache_time = 0
        self._health_ttl = 60  # seconds

    def status(self) -> dict:
        """Probe all memory backends and return live health info. Cached for 60s."""
        now = time.time()
        if self._health_cache and (now - self._health_cache_time) < self._health_ttl:
            return self._health_cache
        
        info = {
            "status": "online",
            "chroma": "offline",
            "neo4j": "offline"
        }
        
        # ChromaDB check
        try:
            count = self.chroma.count()
            info["chroma"] = f"online ({count} memories)"
        except Exception as e:
            info["chroma"] = f"error ({type(e).__name__})"
            info["status"] = "degraded"
            
        # Neo4j check
        try:
            count = self.neo4j.count_nodes()
            info["neo4j"] = f"online ({count} nodes)"
        except Exception as e:
            info["neo4j"] = f"error ({type(e).__name__})"
            if info["status"] == "online": # only degrade if not already degraded/offline
                 info["status"] = "degraded"
            
        if "online" not in info["chroma"] and "online" not in info["neo4j"]:
            info["status"] = "offline"
        
        self._health_cache = info
        self._health_cache_time = now
        return info

    def _is_chroma_available(self) -> bool:
        """Lightweight check using cached health status."""
        health = self.status()
        return "online" in health.get("chroma", "")

    def _coerce_text(self, value) -> str:
        """Normalize LangChain-style structured content into plain text."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, list):
            parts = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str) and text.strip():
                        parts.append(text)
                        continue
                coerced = self._coerce_text(item)
                if coerced.strip():
                    parts.append(coerced)
            return "\n".join(parts).strip()
        if isinstance(value, dict):
            text = value.get("text")
            if isinstance(text, str):
                return text
            return json.dumps(value, ensure_ascii=True, sort_keys=True)
        return str(value)

    def _prepare_chroma_metadata(self, metadata: dict) -> dict:
        """Flatten metadata into Chroma-compatible scalar/list values."""
        safe_metadata = {}
        for key, value in metadata.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe_metadata[key] = value
            elif isinstance(value, list):
                safe_metadata[key] = [
                    item if isinstance(item, (str, int, float, bool)) or item is None
                    else self._coerce_text(item)
                    for item in value
                ]
            else:
                safe_metadata[key] = self._coerce_text(value)
        return safe_metadata

    def store(self, text, role: str, session_id: str,
              is_ephemeral: bool = False, **extra):
        """Store a conversation turn in Chroma. Knowledge extraction is handled
        asynchronously by the analyzer pipeline — rows land here with
        ``analyzed: False`` and the scheduler picks them up on its next tick."""
        metadata = {
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            "analyzed": False,
            **extra,
        }
        normalized_text = self._coerce_text(text)
        if not normalized_text.strip():
            logger.warning("Skipping empty memory write for session %s", session_id)
            return None
        chroma_metadata = self._prepare_chroma_metadata(metadata)

        memory_id = None
        if self._is_chroma_available():
            try:
                memory_id = self.chroma.add_memory(normalized_text, chroma_metadata)
            except Exception as e:
                logger.error("Failed to store memory in Chroma: %s", e)
                self._health_cache_time = 0
        else:
            logger.error("ChromaDB is offline, cannot store memory.")

        return memory_id

    def search(self, query: str, k: int = 5, session_id: str | None = None,
                include_ephemeral: bool = True):
        """Semantic search across memories with optional filters."""
        if not self._is_chroma_available():
            logger.warning("ChromaDB is offline, skipping semantic search.")
            return []

        filters = []
        if session_id:
            filters.append({"session_id": session_id})
        if not include_ephemeral:
            filters.append({"is_ephemeral": False})

        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}
        else:
            where = None

        try:
            return self.chroma.query_memory(query, k=k, where=where)
        except Exception as e:
            logger.error("Chroma search failed: %s", e)
            self._health_cache_time = 0
            return []

    def get_history(self, session_id: str, limit: int = 20):
        """Most recent turns for a session, newest-first."""
        if not self._is_chroma_available():
            logger.warning("ChromaDB is offline, cannot retrieve history.")
            return []
            
        try:
            return self.chroma.get_recent(n=limit, session_id=session_id)
        except Exception as e:
            logger.error("Failed to retrieve history from Chroma: %s", e)
            self._health_cache_time = 0
            return []

    def clear_ephemeral(self, session_id: str | None = None):
        """Wipe all ephemeral memories, optionally scoped to one session."""
        if session_id:
            where = {"$and": [
                {"is_ephemeral": True},
                {"session_id": session_id},
            ]}
        else:
            where = {"is_ephemeral": True}
        self.chroma.delete_memories(where=where)

    def delete_session(self, session_id: str):
        """Wipe an entire session from Chroma and Neo4j."""
        chroma_ok = True
        graph_ok = True

        if self._is_chroma_available():
            try:
                self.chroma.delete_memories(where={"session_id": session_id})
            except Exception as e:
                logger.error("Failed to delete Chroma session %s: %s", session_id, e)
                chroma_ok = False
        else:
            logger.error("ChromaDB is offline, cannot delete session.")
            chroma_ok = False

        if self.neo4j.driver or self.neo4j.verify_connection():
            graph_ok = self.neo4j.delete_session_graph(session_id)

        return chroma_ok and graph_ok

    # ── Chroma session listing ────────────────────────────────────────────────

    def list_sessions(self, limit: int = 500) -> dict:
        """Return raw Chroma records for all sessions up to *limit*.

        Returns a dict with keys ``documents`` (list[str]) and ``metadatas``
        (list[dict]) — safe to iterate even when Chroma is offline.
        """
        empty: dict = {"documents": [], "metadatas": []}
        if not self._is_chroma_available():
            return empty
        try:
            result = self.chroma.collection.get(limit=limit)
            return {
                "documents": result.get("documents") or [],
                "metadatas": result.get("metadatas") or [],
            }
        except Exception as e:
            logger.error("Failed to list sessions from Chroma: %s", e)
            self._health_cache_time = 0
            return empty

    # ── Health cache control ──────────────────────────────────────────────────

    def invalidate_health_cache(self) -> None:
        """Force the next ``status()`` call to re-probe backends."""
        self._health_cache_time = 0

    # ── Knowledge graph public queries ────────────────────────────────────────

    def graph_overview(self, limit: int = 100) -> dict:
        """Return node/relationship counts and top labels from Neo4j."""
        return self.neo4j.get_explorer_graph_overview(limit=limit)

    def graph_node_detail(self, node_id: str) -> dict:
        """Return a node's properties and its connections by ID."""
        return self.neo4j.get_node_detail(node_id)

    def graph_node_provenance(self, node_id: str) -> dict:
        """Return the provenance / source chain for a node."""
        return self.neo4j.get_node_provenance(node_id)

    def graph_active_tasks(self) -> list:
        """Return active task nodes from the knowledge graph."""
        return self.neo4j.list_active_tasks()

    def graph_belief_trail(self, belief_id: str) -> dict:
        """Return the belief chain and supporting evidence for a belief node."""
        chain = self.neo4j.get_belief_chain(belief_id)
        evidence = self.neo4j.get_belief_evidence(belief_id)
        return {"chain": chain, "evidence": evidence}

    # ── Bootstrap ────────────────────────────────────────────────────────────

    def user_root_exists(self) -> bool:
        """True if the explorer has been bootstrapped with a `:User` root."""
        return self.neo4j.user_root_exists()

    def get_user_root(self) -> dict | None:
        """Return the seeded `:User` root node, or None if not yet bootstrapped."""
        return self.neo4j.get_user_root()

    def bootstrap_user_root(self, name: str) -> dict:
        """Hard-wipe the graph and seed a `:Person:User` root.

        Chroma is not touched — historical conversations remain queued for the
        analyzer to re-process against the freshly-seeded graph.
        """
        return self.neo4j.bootstrap_user_root(name)


_instance: MemoryManager | None = None


def get_memory_manager() -> MemoryManager:
    """Return the shared MemoryManager, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = MemoryManager()
    return _instance
