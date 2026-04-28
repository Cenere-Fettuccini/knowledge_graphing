"""src/memory/memory_manager.py

Unified facade over all memory stores.

Phase 1 (this step): wraps ChromaDB only.
Phase 2 (Step 5):    also wraps Neo4jStore; this file grows but callers don't change.

The agent and the Rumination Engine import MemoryManager, never the individual
store classes directly. This keeps the rest of the codebase decoupled from the
underlying storage technology.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from src.memory.chroma_store import ChromaStore
from src.core.config import settings

logger = logging.getLogger(__name__)


class MemoryManager:
    """
    Central memory interface.

    Usage (in agent):
        mm = MemoryManager()
        await mm.store_turn(user_id, session_id, turn_index, "user", user_text)
        await mm.store_turn(user_id, session_id, turn_index + 1, "assistant", reply)

        history  = await mm.get_recent_turns(user_id)
        relevant = await mm.search_relevant(user_id, user_text)
    """

    def __init__(self) -> None:
        self._chroma = ChromaStore()
        # self._neo4j = Neo4jStore()   ← wired in Step 5
        logger.info("MemoryManager ready")

    # ── Session helpers ───────────────────────────────────────────────────────

    @staticmethod
    def new_session_id() -> str:
        """Generate a fresh session ID (UUID4)."""
        return str(uuid.uuid4())

    # ── Write ─────────────────────────────────────────────────────────────────

    async def store_turn(
        self,
        user_id: str,
        session_id: str,
        turn_index: int,
        role: str,
        text: str,
    ) -> str:
        """
        Persist a single conversation turn (user or assistant message).

        Returns the ChromaDB document ID.
        """
        ts = datetime.now(timezone.utc).isoformat()
        doc_id = await self._chroma.add_memory(
            text=text,
            user_id=user_id,
            role=role,
            session_id=session_id,
            turn_index=turn_index,
            timestamp=ts,
        )
        return doc_id

    # ── Read ──────────────────────────────────────────────────────────────────

    async def get_recent_turns(
        self,
        user_id: str,
        n: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Return the last *n* conversation turns for *user_id*, oldest-first.

        Each item: {"text": str, "metadata": {...}}
        """
        n = n or settings.context_window_turns
        return await self._chroma.get_recent(n=n, user_id=user_id)

    async def search_relevant(
        self,
        user_id: str,
        query: str,
        k: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Semantic search over past conversations for *user_id*.

        Returns top-*k* hits sorted by relevance (highest first).
        Each item: {"text": str, "metadata": {...}, "similarity": float}
        """
        k = k or settings.rag_top_k
        return await self._chroma.query_memory(query=query, k=k, user_id=user_id)

    # ── Rumination helpers ────────────────────────────────────────────────────

    async def get_unsummarized(
        self,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return un-processed entries for the Rumination Engine."""
        return await self._chroma.get_unsummarized(user_id=user_id)

    async def mark_summarized(self, ids: list[str]) -> None:
        """Flag a batch of document IDs as processed by Rumination."""
        await self._chroma.mark_summarized(ids)

    # ── Diagnostics ───────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        return {
            "chroma_total_docs": self._chroma.count(),
        }