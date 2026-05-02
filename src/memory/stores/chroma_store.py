import uuid
from datetime import datetime
import chromadb
from src.core.config import settings
from src.memory.embeddings.google import get_embedding_model


class GoogleChromaEmbedder(chromadb.EmbeddingFunction):
    """Wrapper to make LangChain's Google embeddings compatible with ChromaDB."""
    def __init__(self):
        self.model = get_embedding_model()
    
    def __call__(self, input):
        # input is Documents, return Embeddings
        return self.model.embed_documents(input)

class ChromaStore:
    """Persistent episodic memory store using ChromaDB."""
    
    def __init__(self, persist_path=None):
        path = persist_path or settings.chroma_persist_dir
        self.client = chromadb.PersistentClient(path=path)
        self.embedder = GoogleChromaEmbedder()
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self.embedder,
            metadata={"hnsw:space": "cosine"}
        )

    def add_memory(self, text, metadata):
        """Stores a new conversation turn or thought."""
        doc_id = str(uuid.uuid4())
        
        # Ensure timestamp exists
        if 'timestamp' not in metadata:
            from datetime import timezone
            metadata['timestamp'] = datetime.now(timezone.utc).isoformat()
        
        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id]
        )
        return doc_id

    def query_memory(self, query, k=5, where=None):
        """Searches for relevant memories using semantic similarity."""
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
            where=where
        )
        
        # Flatten results into a list of dicts
        memories = []
        if results['documents']:
            for i in range(len(results['documents'][0])):
                memories.append({
                    'id': results['ids'][0][i],
                    'text': results['documents'][0][i],
                    'metadata': results['metadatas'][0][i],
                    'distance': results['distances'][0][i]
                })
        return memories

    def get_recent(self, n=20, session_id=None):
        """Retrieves the last N memories, optionally filtered by session."""
        where = {"session_id": session_id} if session_id else None
        
        # Chroma's 'get' doesn't support sorting directly by metadata effectively in all versions,
        # but we can fetch and sort in memory for the 'recent' window.
        results = self.collection.get(
            where=where,
            limit=100 # Fetch more and trim to be safe on order
        )
        
        memories = []
        if results['documents']:
            for i in range(len(results['documents'])):
                memories.append({
                    'id': results['ids'][i],
                    'text': results['documents'][i],
                    'metadata': results['metadatas'][i]
                })
        
        # Sort by timestamp (ISO 8601 strings sort correctly)
        memories.sort(key=lambda x: x['metadata'].get('timestamp', ''), reverse=True)
        return memories[:n]

    def delete_memories(self, where):
        """Deletes memories matching the filter (e.g. session_id or ephemeral)."""
        if not where:
            raise ValueError("Must provide a filter for deletion to avoid wiping the entire DB.")
        self.collection.delete(where=where)

    def count(self):
        """Returns the total number of documents in the collection."""
        return self.collection.count()
