"""ChromaDB episodic memory — raw conversation storage and semantic retrieval."""

import uuid
from datetime import datetime, timezone

import chromadb

from src.core.config import settings
from src.memory.embeddings.google import get_embedding_model


class GoogleChromaEmbedder(chromadb.EmbeddingFunction):
    """Adapter: LangChain Google embeddings → ChromaDB embedding interface."""

    def __init__(self):
        self._model = get_embedding_model()

    def __call__(self, input):
        return self._model.embed_documents(input)


class ChromaStore:
    """Persistent episodic memory store backed by ChromaDB."""

    def __init__(self, persist_path=None):
        path = persist_path or settings.chroma_persist_dir
        self.client = chromadb.PersistentClient(path=path)
        self._embedder = GoogleChromaEmbedder()
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_memory(self, text: str, metadata: dict) -> str:
        """Embed and store a single document. Returns the generated ID."""
        doc_id = str(uuid.uuid4())
        metadata.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        self.collection.add(
            documents=[text],
            metadatas=[metadata],
            ids=[doc_id],
        )
        return doc_id

    # ── Read ──────────────────────────────────────────────────────────────────

    def query_memory(self, query: str, k: int = 5, where: dict | None = None):
        """Semantic search. Returns list of {id, text, metadata, distance}."""
        results = self.collection.query(
            query_texts=[query],
            n_results=k,
            where=where,
        )
        if not results["documents"] or not results["documents"][0]:
            return []
        return [
            {
                "id": results["ids"][0][i],
                "text": results["documents"][0][i],
                "metadata": results["metadatas"][0][i],
                "distance": results["distances"][0][i],
            }
            for i in range(len(results["documents"][0]))
        ]

    def get_recent(self, n: int = 20, session_id: str | None = None):
        """Latest *n* turns, sorted newest-first. Optionally scoped to a session."""
        where = {"session_id": session_id} if session_id else None
        # Fetch enough headroom so the timestamp sort is meaningful.
        results = self.collection.get(
            where=where,
            limit=max(n, 100),
        )
        if not results["documents"]:
            return []
        memories = [
            {
                "id": results["ids"][i],
                "text": results["documents"][i],
                "metadata": results["metadatas"][i],
            }
            for i in range(len(results["documents"]))
        ]
        memories.sort(
            key=lambda m: m["metadata"].get("timestamp", ""), reverse=True
        )
        return memories[:n]

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_memories(self, where: dict):
        """Delete all documents matching *where*. Raises on empty filter."""
        if not where:
            raise ValueError("A filter is required to prevent accidental full wipe.")
        self.collection.delete(where=where)

    # ── Utils ─────────────────────────────────────────────────────────────────

    def count(self) -> int:
        """Total documents in the collection."""
        return self.collection.count()
