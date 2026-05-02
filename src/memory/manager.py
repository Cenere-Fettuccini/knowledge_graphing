from src.memory.stores.chroma_store import ChromaStore

class MemoryManager:
    """
    Unified facade for all memory operations.
    Hides the complexity of multiple storage backends (Chroma, Neo4j).
    """
    
    def __init__(self, persist_path=None):
        self.chroma = ChromaStore(persist_path=persist_path)
        # Neo4j store will be added in Step 5
    
    def store(self, text, role, session_id, is_ephemeral=False, **kwargs):
        """
        Stores a conversation turn.
        
        Args:
            text: The message content.
            role: 'user' or 'assistant'.
            session_id: Unique ID for the conversation session.
            is_ephemeral: If True, this memory can be easily wiped later.
            **kwargs: Additional metadata.
        """
        metadata = {
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            **kwargs
        }
        return self.chroma.add_memory(text, metadata)
    
    def search(self, query, k=5, session_id=None, include_ephemeral=True):
        """
        Semantic search across memories.
        
        Args:
            query: The search string.
            k: Number of results to return.
            session_id: Optional filter for a specific session.
            include_ephemeral: Whether to include temporary memories.
        """
        filters = []
        if session_id:
            filters.append({"session_id": session_id})
        
        if not include_ephemeral:
            filters.append({"is_ephemeral": False})
            
        where = None
        if len(filters) == 1:
            where = filters[0]
        elif len(filters) > 1:
            where = {"$and": filters}
            
        return self.chroma.query_memory(query, k=k, where=where)
    
    def get_history(self, session_id, limit=20):
        """Returns the most recent turns for a session."""
        return self.chroma.get_recent(n=limit, session_id=session_id)
    
    def clear_ephemeral(self, session_id=None):
        """
        Deletes all ephemeral memories.
        If session_id is provided, only clears for that session.
        """
        if session_id:
            where = {"$and": [
                {"is_ephemeral": True},
                {"session_id": session_id}
            ]}
        else:
            where = {"is_ephemeral": True}
            
        self.chroma.delete_memories(where=where)

# Singleton instance
memory_manager = MemoryManager()
