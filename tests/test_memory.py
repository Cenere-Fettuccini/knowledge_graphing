"""tests/test_memory.py

Integration tests for the ChromaDB memory layer.

These tests spin up a real ChromaDB instance in a temporary directory and make
real calls to the Google embedding API, so they require:
  - A valid GOOGLE_API_KEY in the environment / .env file.
  - The chromadb and google-genai packages installed.

Run with:
    pytest tests/test_memory.py -v

Skip embedding-heavy tests in CI by setting NO_EMBED=1:
    NO_EMBED=1 pytest tests/test_memory.py -v
"""

import asyncio
import os
import tempfile
import uuid

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def tmp_chroma_dir():
    """Temporary directory for ChromaDB persistence — deleted after the module."""
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture(scope="module")
def patched_settings(tmp_chroma_dir):
    """
    Override chroma_persist_dir for the duration of the test module so tests
    don't pollute the real ./data/chroma directory.
    """
    from src.core import config as cfg
    original = cfg.settings.chroma_persist_dir
    cfg.settings.__dict__["chroma_persist_dir"] = tmp_chroma_dir
    yield cfg.settings
    cfg.settings.__dict__["chroma_persist_dir"] = original


@pytest.fixture(scope="module")
def chroma_store(patched_settings):
    from src.memory.chroma_store import ChromaStore
    store = ChromaStore()
    yield store
    store.close()

@pytest.fixture(scope="module")
def memory_manager(patched_settings):
    from src.memory.memory_manager import MemoryManager
    mm = MemoryManager()
    yield mm
    mm._chroma.close()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SKIP_EMBED = os.getenv("NO_EMBED", "0") == "1"
skip_if_no_embed = pytest.mark.skipif(SKIP_EMBED, reason="NO_EMBED=1 — skipping embedding calls")

USER_ID    = "test_user_42"
SESSION_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# ChromaStore tests
# ---------------------------------------------------------------------------

class TestChromaStore:

    @skip_if_no_embed
    def test_add_and_count(self, chroma_store):
        """Storing a document increases the collection count by 1."""
        before = chroma_store.count()

        asyncio.get_event_loop().run_until_complete(
            chroma_store.add_memory(
                text="Alice mentioned she prefers morning standups.",
                user_id=USER_ID,
                role="user",
                session_id=SESSION_ID,
                turn_index=0,
            )
        )

        assert chroma_store.count() == before + 1

    @skip_if_no_embed
    def test_add_returns_uuid(self, chroma_store):
        doc_id = asyncio.get_event_loop().run_until_complete(
            chroma_store.add_memory(
                text="Bob is learning Rust in his spare time.",
                user_id=USER_ID,
                role="user",
                session_id=SESSION_ID,
                turn_index=1,
            )
        )
        assert isinstance(doc_id, str)
        assert len(doc_id) == 36  # UUID4 length

    @skip_if_no_embed
    def test_query_returns_results(self, chroma_store):
        """Semantic search should surface the Alice standup memory."""
        results = asyncio.get_event_loop().run_until_complete(
            chroma_store.query_memory(
                query="What does Alice prefer?",
                k=3,
                user_id=USER_ID,
            )
        )
        assert len(results) > 0
        texts = [r["text"] for r in results]
        assert any("Alice" in t for t in texts)

    @skip_if_no_embed
    def test_query_similarity_range(self, chroma_store):
        """Similarity scores should be in [0, 1]."""
        results = asyncio.get_event_loop().run_until_complete(
            chroma_store.query_memory(query="standup preferences", k=5, user_id=USER_ID)
        )
        for r in results:
            assert 0.0 <= r["similarity"] <= 1.0

    @skip_if_no_embed
    def test_get_recent_ordering(self, chroma_store):
        """get_recent should return turns in chronological order."""
        turns = asyncio.get_event_loop().run_until_complete(
            chroma_store.get_recent(n=10, user_id=USER_ID)
        )
        timestamps = [t["metadata"]["timestamp"] for t in turns]
        assert timestamps == sorted(timestamps)

    @skip_if_no_embed
    def test_mark_summarized(self, chroma_store):
        """After mark_summarized, those entries should not appear in get_unsummarized."""
        # Add a fresh entry
        doc_id = asyncio.get_event_loop().run_until_complete(
            chroma_store.add_memory(
                text="Carol joined Acme Corp in Q1.",
                user_id=USER_ID,
                role="user",
                session_id=SESSION_ID,
                turn_index=2,
            )
        )

        # It should appear in unsummarized
        unsummarized_before = asyncio.get_event_loop().run_until_complete(
            chroma_store.get_unsummarized(user_id=USER_ID)
        )
        ids_before = [e["id"] for e in unsummarized_before]
        assert doc_id in ids_before

        # Mark it
        asyncio.get_event_loop().run_until_complete(
            chroma_store.mark_summarized([doc_id])
        )

        # Should no longer appear
        unsummarized_after = asyncio.get_event_loop().run_until_complete(
            chroma_store.get_unsummarized(user_id=USER_ID)
        )
        ids_after = [e["id"] for e in unsummarized_after]
        assert doc_id not in ids_after

    def test_invalid_role_raises(self, chroma_store):
        """add_memory should reject roles other than 'user' / 'assistant'."""
        with pytest.raises(ValueError, match="role must be"):
            asyncio.get_event_loop().run_until_complete(
                chroma_store.add_memory(
                    text="test",
                    user_id=USER_ID,
                    role="system",          # invalid
                    session_id=SESSION_ID,
                    turn_index=99,
                )
            )

    def test_empty_collection_query(self, patched_settings):
        """query_memory on an empty store should return an empty list, not crash."""
        import tempfile
        from src.memory.chroma_store import ChromaStore

        with tempfile.TemporaryDirectory() as empty_dir:
            patched_settings.__dict__["chroma_persist_dir"] = empty_dir
            store = ChromaStore()
            try:
                results = asyncio.get_event_loop().run_until_complete(
                    store.query_memory(query="anything", k=5)
                )
                assert results == []
            finally:
                store.close()
            patched_settings.__dict__["chroma_persist_dir"] = patched_settings.chroma_persist_dir


# ---------------------------------------------------------------------------
# MemoryManager (facade) tests
# ---------------------------------------------------------------------------

class TestMemoryManager:

    @skip_if_no_embed
    def test_store_turn_and_retrieve(self, memory_manager):
        """Full round-trip: store two turns, then retrieve them via get_recent."""
        session = str(uuid.uuid4())

        asyncio.get_event_loop().run_until_complete(
            memory_manager.store_turn(USER_ID, session, 0, "user", "My dog's name is Pepper.")
        )
        asyncio.get_event_loop().run_until_complete(
            memory_manager.store_turn(USER_ID, session, 1, "assistant", "Got it! I'll remember that your dog is called Pepper.")
        )

        turns = asyncio.get_event_loop().run_until_complete(
            memory_manager.get_recent_turns(USER_ID, n=10)
        )

        texts = [t["text"] for t in turns]
        assert any("Pepper" in t for t in texts)

    @skip_if_no_embed
    def test_search_relevant_returns_ranked(self, memory_manager):
        """search_relevant should return results with similarity scores."""
        results = asyncio.get_event_loop().run_until_complete(
            memory_manager.search_relevant(USER_ID, "What is my dog called?", k=3)
        )
        assert len(results) > 0
        for r in results:
            assert "similarity" in r
            assert "text" in r

    def test_stats(self, memory_manager):
        """stats() should return a dict with chroma_total_docs."""
        s = memory_manager.stats()
        assert "chroma_total_docs" in s
        assert isinstance(s["chroma_total_docs"], int)

    def test_new_session_id(self):
        from src.memory.memory_manager import MemoryManager
        a = MemoryManager.new_session_id()
        b = MemoryManager.new_session_id()
        assert a != b
        assert len(a) == 36  # UUID4