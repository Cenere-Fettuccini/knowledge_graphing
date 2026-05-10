"""ChromaDB episodic memory storage and semantic retrieval."""

import logging
import os
import uuid
from datetime import datetime, timezone

import chromadb

from src.core.config import settings
from src.memory.embeddings.google import get_embedding_model

logger = logging.getLogger(__name__)


# Exceptions that have shown up in the wild during PersistentClient bootstrap.
# These come from a partially-failed init that leaves stale state in
# chromadb's SharedSystemClient cache or a half-loaded Rust binding.
_CHROMA_INIT_TRANSIENTS = (AttributeError, KeyError, ValueError)


def _clear_chroma_shared_cache() -> None:
    """Wipe chromadb's process-wide SharedSystemClient cache.

    Reaches into a private symbol on purpose — this is the documented escape
    hatch when an earlier init failed midway and left a stale identifier
    behind. Safe because we only call it from the retry path.
    """
    try:
        from chromadb.api.shared_system_client import SharedSystemClient

        SharedSystemClient._identifier_to_system.clear()
    except Exception:  # pragma: no cover - best-effort
        logger.debug("Could not clear chromadb SharedSystemClient cache.", exc_info=True)


def _create_persistent_client(path: str) -> chromadb.api.client.Client:
    """Create a PersistentClient, retrying once if the first init blows up.

    Observed failure mode (chromadb >= 0.5):
      1. First call dies with AttributeError on RustBindingsAPI.bindings
         because the Rust binding failed to initialise.
      2. Second call dies with KeyError on the persist path, because step 1
         registered a half-baked entry in SharedSystemClient's cache.

    Pre-creating the directory + clearing the shared cache between attempts
    defuses both. If the second attempt also fails, the caller decides what
    to do (production raises, pytest falls back to EphemeralClient).
    """
    os.makedirs(path, exist_ok=True)
    try:
        return chromadb.PersistentClient(path=path)
    except _CHROMA_INIT_TRANSIENTS as exc:
        logger.warning(
            "ChromaDB PersistentClient init failed (%s: %s) — clearing the "
            "shared-system cache and retrying once.",
            type(exc).__name__,
            exc,
        )
        _clear_chroma_shared_cache()
        return chromadb.PersistentClient(path=path)


class GoogleChromaEmbedder(chromadb.EmbeddingFunction):
    """Adapter from native Google embeddings to ChromaDB's interface."""

    def __init__(self):
        self._model = get_embedding_model()

    @staticmethod
    def name() -> str:
        return "google-genai-embedder"

    def get_config(self) -> dict:
        return {"provider": "google-genai", "model": "gemini-embedding-2"}

    @staticmethod
    def build_from_config(config: dict):
        del config
        return GoogleChromaEmbedder()

    def __call__(self, input):
        return self._model.embed_documents(list(input))


class ChromaStore:
    """Persistent episodic memory store backed by ChromaDB."""

    def __init__(self, persist_path=None):
        path = persist_path or settings.chroma_persist_dir
        if path == ":memory:":
            self.client = chromadb.EphemeralClient()
        else:
            try:
                self.client = _create_persistent_client(path)
            except Exception:
                if persist_path and os.environ.get("PYTEST_CURRENT_TEST"):
                    logger.warning(
                        "ChromaDB persistent init failed under pytest — "
                        "falling back to EphemeralClient."
                    )
                    self.client = chromadb.EphemeralClient()
                else:
                    raise
        self._embedder = GoogleChromaEmbedder()
        self.collection = self.client.get_or_create_collection(
            name=settings.chroma_collection,
            embedding_function=self._embedder,
            metadata={"hnsw:space": "cosine"},
        )

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
        """Latest n turns, sorted newest-first. Optionally scoped to a session."""
        where = {"session_id": session_id} if session_id else None
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

        def sort_key(memory: dict) -> tuple[str, int]:
            metadata = memory.get("metadata", {})
            return (
                metadata.get("timestamp", ""),
                int(metadata.get("turn_order", 0) or 0),
            )

        memories.sort(
            key=sort_key, reverse=True
        )
        return memories[:n]

    def delete_memories(self, where: dict):
        """Delete all documents matching where. Raises on empty filter."""
        if not where:
            raise ValueError("A filter is required to prevent accidental full wipe.")
        self.collection.delete(where=where)

    def count(self) -> int:
        """Total documents in the collection."""
        return self.collection.count()

    def list_where(
        self,
        where: dict | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """Return documents matching ``where`` (no embedding lookup), oldest-first.

        Used by the analyzer pipeline to drain the ``analyzed: false`` queue in
        chronological order so the LLM sees conversation turns in the same
        sequence the user lived them.
        """
        results = self.collection.get(where=where, limit=limit, offset=offset)
        if not results.get("documents"):
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
            key=lambda m: (
                m.get("metadata", {}).get("timestamp", ""),
                int(m.get("metadata", {}).get("turn_order", 0) or 0),
            )
        )
        return memories

    def update_metadata(self, ids: list[str], patch: dict) -> int:
        """Merge ``patch`` into the metadata of every doc in ``ids``. Returns count touched."""
        if not ids:
            return 0
        existing = self.collection.get(ids=ids)
        new_metadatas = []
        for current in existing.get("metadatas", []) or []:
            merged = dict(current or {})
            merged.update(patch)
            new_metadatas.append(merged)
        if not new_metadatas:
            return 0
        self.collection.update(ids=existing["ids"], metadatas=new_metadatas)
        return len(existing["ids"])

    def count_where(self, where: dict | None = None) -> int:
        """Approximate count of documents matching ``where``.

        Chroma has no native count-with-filter, so this fetches just the ids;
        cheap enough for queue-status displays.
        """
        results = self.collection.get(where=where, include=[])
        return len(results.get("ids") or [])
