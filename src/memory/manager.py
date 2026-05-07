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

    def store(self, text, role: str, session_id: str,
              is_ephemeral: bool = False, **extra):
        """Store a conversation turn with metadata."""
        if not self._is_chroma_available():
            logger.error("ChromaDB is offline, cannot store memory.")
            return None

        metadata = {
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            **extra,
        }
        normalized_text = self._coerce_text(text)
        if not normalized_text.strip():
            logger.warning("Skipping empty memory write for session %s", session_id)
            return None
        try:
            return self.chroma.add_memory(normalized_text, metadata)
        except Exception as e:
            logger.error("Failed to store memory in Chroma: %s", e)
            # Invalidate cache on failure so next call re-checks
            self._health_cache_time = 0
            return None

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
        """Wipe an entire session from Chroma."""
        if not self._is_chroma_available():
            logger.error("ChromaDB is offline, cannot delete session.")
            return False
        try:
            self.chroma.delete_memories(where={"session_id": session_id})
            return True
        except Exception as e:
            logger.error("Failed to delete session %s: %s", session_id, e)
            return False


# ── Singleton instance ────────────────────────────────────────────────────────
# This is used by the API and other non-Agent modules that need direct access
# to the storage layer (like the Explorer).
memory_manager = MemoryManager()
