"""src/memory/chroma_store.py

ChromaDB wrapper for episodic (conversational) memory.

Responsibilities:
  - Embed text using Google's text-embedding-004 model.
  - Persist every conversation turn (user + assistant) with rich metadata.
  - Expose semantic search (RAG) and recency fetch (sliding window).
  - Flag entries as summarized once the Rumination Engine has processed them.

Collection schema
-----------------
  document  : raw message text
  embedding : float vector (text-embedding-004, 768-dim)
  metadata  : {
      user_id    : str,   # Telegram user ID
      role       : str,   # "user" | "assistant"
      timestamp  : str,   # ISO 8601 UTC
      session_id : str,   # groups a conversation session
      summarized : bool,  # has Rumination processed this entry?
      turn_index : int,   # ordinal position within the session
  }
"""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from src.core.config import settings

logger = logging.getLogger(__name__)


class ChromaStore:
    """Async-friendly wrapper around a single ChromaDB collection."""

    def __init__(self) -> None:
        # LangChain embeddings client — same SDK the agent uses
        self._embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,
            task_type="retrieval_document",
        )

        # Persistent local client
        self._client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )

        # Get-or-create the conversations collection.
        # ChromaDB will embed lazily; we supply our own vectors so we use
        # the default (no-op) embedding function and pass embeddings manually.
        self._col = self._client.get_or_create_collection(
            name=settings.chroma_collection,
            metadata={"hnsw:space": "cosine"},
        )

        logger.info(
            "ChromaStore ready — collection=%r, count=%d",
            settings.chroma_collection,
            self._col.count(),
        )

    # ── Embedding ─────────────────────────────────────────────────────────────

    async def _embed(self, text: str) -> list[float]:
        """Embed a document string (async-safe, uses retrieval_document task)."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._embeddings.embed_query(text)
        )

    async def _embed_query(self, text: str) -> list[float]:
        """Embed a search query string (retrieval_query task for better recall)."""
        loop = asyncio.get_event_loop()
        # Swap task_type for query-side embedding
        query_client = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.google_api_key,
            task_type="retrieval_query",
        )
        return await loop.run_in_executor(
            None, lambda: query_client.embed_query(text)
        )

    # ── Write ─────────────────────────────────────────────────────────────────

    async def add_memory(
        self,
        text: str,
        user_id: str,
        role: str,
        session_id: str,
        turn_index: int,
        timestamp: str | None = None,
    ) -> str:
        """
        Embed *text* and persist it to the collection.

        Returns the auto-generated document ID.
        """
        if role not in ("user", "assistant"):
            raise ValueError(f"role must be 'user' or 'assistant', got {role!r}")

        doc_id = str(uuid.uuid4())
        ts = timestamp or datetime.now(timezone.utc).isoformat()
        embedding = await self._embed(text)

        metadata: dict[str, Any] = {
            "user_id":    user_id,
            "role":       role,
            "timestamp":  ts,
            "session_id": session_id,
            "summarized": False,
            "turn_index": turn_index,
        }

        self._col.add(
            ids=[doc_id],
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata],
        )

        logger.debug("add_memory id=%s role=%s user=%s", doc_id, role, user_id)
        return doc_id

    # ── Read ──────────────────────────────────────────────────────────────────

    async def query_memory(
        self,
        query: str,
        k: int = 5,
        user_id: str | None = None,
        role: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search: return the top-*k* most relevant memories.

        Optional metadata filters:
          user_id — restrict to a specific user
          role    — restrict to "user" or "assistant" turns
        """
        query_embedding = await self._embed_query(query)

        where: dict[str, Any] | None = None
        conditions: list[dict] = []
        if user_id:
            conditions.append({"user_id": {"$eq": user_id}})
        if role:
            conditions.append({"role": {"$eq": role}})

        if len(conditions) == 1:
            where = conditions[0]
        elif len(conditions) > 1:
            where = {"$and": conditions}

        results = self._col.query(
            query_embeddings=[query_embedding],
            n_results=min(k, max(self._col.count(), 1)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        hits = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            hits.append({
                "text":       doc,
                "metadata":   meta,
                "similarity": round(1 - dist, 4),  # cosine distance → similarity
            })

        return hits

    async def get_recent(
        self,
        n: int = 20,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Fetch the *n* most recent conversation turns, sorted oldest-first.

        Used for the sliding-window conversation history injected into the
        agent's prompt.
        """
        where: dict[str, Any] | None = (
            {"user_id": {"$eq": user_id}} if user_id else None
        )

        total = self._col.count()
        if total == 0:
            return []

        fetch_n = min(max(n * 4, 40), total)  # over-fetch then trim by timestamp

        results = self._col.get(
            where=where,
            limit=fetch_n,
            include=["documents", "metadatas"],
        )

        turns = [
            {"text": doc, "metadata": meta}
            for doc, meta in zip(results["documents"], results["metadatas"])
        ]

        # Sort by timestamp descending, take n, then reverse to chronological
        turns.sort(key=lambda t: t["metadata"].get("timestamp", ""), reverse=True)
        turns = turns[:n]
        turns.reverse()

        return turns

    # ── Maintenance ───────────────────────────────────────────────────────────

    async def get_unsummarized(
        self,
        batch_size: int | None = None,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return entries not yet processed by the Rumination Engine.

        Used by RuminationEngine.run_cycle() in Step 7.
        """
        batch_size = batch_size or settings.rumination_batch_size
        total = self._col.count()
        if total == 0:
            return []

        conditions: list[dict] = [{"summarized": {"$eq": False}}]
        if user_id:
            conditions.append({"user_id": {"$eq": user_id}})

        where = conditions[0] if len(conditions) == 1 else {"$and": conditions}

        results = self._col.get(
            where=where,
            limit=batch_size,
            include=["documents", "metadatas"],
        )

        return [
            {"id": doc_id, "text": doc, "metadata": meta}
            for doc_id, doc, meta in zip(
                results["ids"], results["documents"], results["metadatas"]
            )
        ]

    async def mark_summarized(self, ids: list[str]) -> None:
        """
        Mark a batch of document IDs as summarized=True.

        Called by the Rumination Engine after it has extracted facts from them.
        """
        if not ids:
            return
        self._col.update(
            ids=ids,
            metadatas=[{"summarized": True}] * len(ids),
        )
        logger.debug("mark_summarized count=%d", len(ids))

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def count(self) -> int:
        """Total number of stored documents."""
        return self._col.count()

    def close(self) -> None:
        """Release Chroma resources (required on Windows)."""
        try:
            system = getattr(self._client, "_system", None)
            if system is not None:
                system.stop()
        except Exception:
            pass

    # ── Context manager support ───────────────────────────────────────────────

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
