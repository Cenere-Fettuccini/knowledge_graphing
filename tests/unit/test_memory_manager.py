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


def test_store_knowledge_signals_creates_entity_belief_and_turn_link():
    manager = MemoryManager.__new__(MemoryManager)
    created = []

    class FakeNeo4j:
        def upsert_entity(self, name, entity_type="Topic", description=None, properties=None):
            created.append(("entity", name, entity_type))
            return "entity-1"

        def record_belief_signal(self, **kwargs):
            created.append(("belief", kwargs["content"], kwargs["belief_key"], kwargs["about_entity_id"]))
            return "belief-1"

        def add_edge(self, source_id, target_id, rel_type, properties=None):
            created.append(("edge", source_id, target_id, rel_type))

    manager.neo4j = FakeNeo4j()

    manager._store_knowledge_signals(
        text="I prefer exploring beliefs instead of raw chat logs.",
        role="user",
        session_id="session-1",
        context=None,
        turn_id="turn-1",
    )

    assert created[0][0] == "entity"
    assert created[1][0] == "belief"
    assert created[2] == ("edge", "belief-1", "turn-1", "DERIVED_FROM")
