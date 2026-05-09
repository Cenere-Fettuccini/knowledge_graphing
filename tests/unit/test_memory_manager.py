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
