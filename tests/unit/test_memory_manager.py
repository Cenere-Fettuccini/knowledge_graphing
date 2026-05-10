from src.memory.manager import MemoryManager


def test_coerce_text_extracts_text_from_content_blocks():
    manager = MemoryManager.__new__(MemoryManager)

    value = [
        {"type": "text", "text": "Your name is Kevin.", "extras": {"signature": "abc"}},
        {"type": "text", "text": "You like tea."},
    ]

    assert manager._coerce_text(value) == "Your name is Kevin.\nYou like tea."


def test_coerce_text_handles_plain_string():
    manager = MemoryManager.__new__(MemoryManager)

    assert manager._coerce_text("hello") == "hello"


def test_delete_session_removes_from_chroma_and_neo4j():
    manager = MemoryManager.__new__(MemoryManager)

    deleted = {}

    class FakeChroma:
        def delete_memories(self, where):
            deleted["where"] = where

    class FakeNeo4j:
        driver = object()

        def verify_connection(self):
            return True

        def delete_session_graph(self, session_id):
            deleted["session_id"] = session_id
            return True

    manager.chroma = FakeChroma()
    manager.neo4j = FakeNeo4j()
    manager._is_chroma_available = lambda: True

    assert manager.delete_session("test_session_123") is True
    assert deleted["where"] == {"session_id": "test_session_123"}
    assert deleted["session_id"] == "test_session_123"


def test_bootstrap_user_root_delegates_to_neo4j():
    manager = MemoryManager.__new__(MemoryManager)
    captured = {}

    class FakeNeo4j:
        def bootstrap_user_root(self, name):
            captured["name"] = name
            return {"id": "user:kevin", "label": "User", "labels": ["Person", "User"], "name": name}

    manager.neo4j = FakeNeo4j()

    result = manager.bootstrap_user_root("Kevin")
    assert captured["name"] == "Kevin"
    assert result["id"] == "user:kevin"
    assert "User" in result["labels"]
    assert "Person" in result["labels"]


def test_user_root_exists_delegates_to_neo4j():
    manager = MemoryManager.__new__(MemoryManager)

    class FakeNeo4j:
        def user_root_exists(self):
            return True

    manager.neo4j = FakeNeo4j()
    assert manager.user_root_exists() is True


def test_mark_failed_stamps_failure_metadata():
    """Failed rows must leave the live queue but carry a reason for inspection."""
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.mark_failed(["c1", "c2"], reason="invalid_json_response", run_id="r-123")
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]
    assert captured["patch"]["analyzed"] is True
    assert captured["patch"]["analyzer_status"] == "failed"
    assert captured["patch"]["analyzer_failure_reason"] == "invalid_json_response"
    assert captured["patch"]["analysis_run_id"] == "r-123"
    assert "analyzer_failed_at" in captured["patch"]


def test_list_failed_filters_on_analyzer_status():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            captured["where"] = where
            captured["limit"] = limit
            return [
                {"id": "c1", "text": "x", "metadata": {"analyzer_status": "failed"}},
            ]

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    rows = manager.list_failed(limit=25)
    assert len(rows) == 1
    assert captured["where"] == {"analyzer_status": "failed"}
    assert captured["limit"] == 25


def test_count_failed_uses_chroma_filter():
    manager = MemoryManager.__new__(MemoryManager)

    class FakeChroma:
        def count_where(self, where=None):
            assert where == {"analyzer_status": "failed"}
            return 7

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    assert manager.count_failed() == 7


def test_retry_failed_resets_status_so_queue_picks_them_up():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.retry_failed(["c1", "c2"])
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]
    assert captured["patch"]["analyzed"] is False
    assert captured["patch"]["analyzer_status"] == "pending"
    assert captured["patch"]["analyzer_failure_reason"] == ""


def test_retry_failed_with_no_ids_drains_entire_dlq():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            return [
                {"id": "c1", "metadata": {"analyzer_status": "failed"}},
                {"id": "c2", "metadata": {"analyzer_status": "failed"}},
            ]

        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.retry_failed()  # no ids → drain everything
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]


def test_retry_failed_returns_zero_when_dlq_is_empty():
    manager = MemoryManager.__new__(MemoryManager)

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            return []

        def update_metadata(self, ids, patch):
            raise AssertionError("update_metadata must not be called when DLQ is empty")

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    assert manager.retry_failed() == 0


def test_mark_analyzed_records_success_status():
    """The success path should also stamp analyzer_status so old/new rows have a uniform shape."""
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    manager.mark_analyzed(["c1"], run_id="r")
    assert captured["patch"]["analyzed"] is True
    assert captured["patch"]["analyzer_status"] == "success"


def test_store_writes_to_chroma_only_with_unanalyzed_flag():
    """Stage-1 cutover: store() writes to Chroma with analyzed=False and never to Neo4j."""
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def add_memory(self, text, metadata):
            captured["text"] = text
            captured["metadata"] = metadata
            return "chroma-id-1"

    class FakeNeo4j:
        def __getattr__(self, name):
            raise AssertionError(f"Neo4j must not be touched on store(); attempted to access {name!r}")

    manager.chroma = FakeChroma()
    manager.neo4j = FakeNeo4j()
    manager._is_chroma_available = lambda: True
    manager._health_cache_time = 0

    memory_id = manager.store(
        "I prefer exploring beliefs instead of raw chat logs.",
        role="user",
        session_id="session-1",
    )

    assert memory_id == "chroma-id-1"
    assert captured["metadata"]["role"] == "user"
    assert captured["metadata"]["session_id"] == "session-1"
    assert captured["metadata"]["analyzed"] is False
    assert captured["metadata"]["is_ephemeral"] is False
