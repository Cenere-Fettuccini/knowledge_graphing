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
