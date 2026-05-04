"""Unified facade over all memory stores — the only import other modules need."""

from src.memory.stores.chroma_store import ChromaStore
from src.memory.stores.neo4j_store import Neo4jStore


class MemoryManager:
    """
    Single entry-point for all memory operations.
    Hides backend details (Chroma, Neo4j) behind a clean API.
    """

    def __init__(self, persist_path=None):
        self.chroma = ChromaStore(persist_path=persist_path)
        self.neo4j = Neo4jStore()

    def status(self) -> dict:
        """Probe all memory backends and return live health info."""
        info = {"chroma": "offline", "neo4j": "offline"}
        
        # ChromaDB check
        try:
            count = self.chroma.count()
            info["chroma"] = f"online ({count} memories)"
        except Exception as e:
            info["chroma"] = f"error ({type(e).__name__})"
            
        # Neo4j check
        try:
            count = self.neo4j.count_nodes()
            info["neo4j"] = f"online ({count} nodes)"
        except Exception as e:
            info["neo4j"] = f"error ({type(e).__name__})"
            
        return info

    def store(self, text: str, role: str, session_id: str,
              is_ephemeral: bool = False, **extra):
        """Store a conversation turn with metadata."""
        metadata = {
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            **extra,
        }
        return self.chroma.add_memory(text, metadata)

    def search(self, query: str, k: int = 5, session_id: str | None = None,
               include_ephemeral: bool = True):
        """Semantic search across memories with optional filters."""
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

        return self.chroma.query_memory(query, k=k, where=where)

    def get_history(self, session_id: str, limit: int = 20):
        """Most recent turns for a session, newest-first."""
        return self.chroma.get_recent(n=limit, session_id=session_id)

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
