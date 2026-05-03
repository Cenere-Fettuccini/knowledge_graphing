"""Unified facade over all memory stores — the only import other modules need."""

from src.memory.stores.chroma_store import ChromaStore


class MemoryManager:
    """
    Single entry-point for all memory operations.
    Hides backend details (Chroma, Neo4j) behind a clean API.
    """

    def __init__(self, persist_path=None):
        self.chroma = ChromaStore(persist_path=persist_path)
        # Neo4j store will be added in Step 5

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
