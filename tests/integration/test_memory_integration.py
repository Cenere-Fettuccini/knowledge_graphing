import pytest
import uuid
from src.memory.manager import MemoryManager

@pytest.fixture
def mem():
    """Provides a MemoryManager instance using an isolated in-memory database."""
    return MemoryManager(persist_path=":memory:")

def test_persistence_and_retrieval(mem):
    """Verifies that messages are stored and can be retrieved by session ID."""
    session_id = f"test_session_{uuid.uuid4().hex[:8]}"
    text = "Hello, this is a persistent memory test."
    
    # Store
    mem.store(text, role="user", session_id=session_id)
    
    # Retrieve
    history = mem.get_history(session_id)
    assert len(history) == 1
    assert history[0]['text'] == text
    assert history[0]['metadata']['role'] == "user"

def test_semantic_search(mem):
    """Verifies that semantic search correctly identifies relevant memories."""
    session_id = f"test_search_{uuid.uuid4().hex[:8]}"
    mem.store("My favorite color is neon purple.", role="user", session_id=session_id)
    mem.store("I have a pet dinosaur named Rex.", role="user", session_id=session_id)
    
    # Search for color
    results = mem.search("What is your favorite color?", k=1, session_id=session_id)
    assert len(results) == 1
    assert "purple" in results[0]['text']
    
    # Search for pet
    results = mem.search("Do you have any animals?", k=1, session_id=session_id)
    assert len(results) == 1
    assert "Rex" in results[0]['text']

def test_ephemeral_memory(mem):
    """Verifies that ephemeral (temporary) memories can be wiped selectively."""
    session_id = f"test_temp_{uuid.uuid4().hex[:8]}"
    
    # Store one ephemeral and one persistent
    mem.store("This is a secret that should disappear.", role="user", session_id=session_id, is_ephemeral=True)
    mem.store("This is a fact that should stay.", role="user", session_id=session_id, is_ephemeral=False)
    
    # Verify both exist in history
    history = mem.get_history(session_id)
    assert len(history) == 2
    
    # Clear ephemeral memories for this session
    mem.clear_ephemeral(session_id=session_id)
    
    # Verify only the persistent one remains
    history = mem.get_history(session_id)
    assert len(history) == 1
    assert "stay" in history[0]['text']
    assert "secret" not in history[0]['text']

def test_session_isolation(mem):
    """Verifies that search can be isolated to a specific session."""
    session_1 = f"test_iso_1_{uuid.uuid4().hex[:8]}"
    session_2 = f"test_iso_2_{uuid.uuid4().hex[:8]}"
    
    mem.store("The secret password for Alice is 'apple'.", role="user", session_id=session_1)
    mem.store("The secret password for Bob is 'banana'.", role="user", session_id=session_2)
    
    # Search session 1
    results = mem.search("secret password", k=1, session_id=session_1)
    assert "Alice" in results[0]['text']
    assert "apple" in results[0]['text']
    assert "banana" not in results[0]['text']
    
    # Search session 2
    results = mem.search("secret password", k=1, session_id=session_2)
    assert "Bob" in results[0]['text']
    assert "banana" in results[0]['text']
    assert "apple" not in results[0]['text']


def test_nested_metadata_is_sanitized_for_chroma(mem):
    """Structured graph context should not break Chroma metadata writes."""
    session_id = f"test_nested_{uuid.uuid4().hex[:8]}"

    mem.store(
        "Anchor this message to a graph node.",
        role="user",
        session_id=session_id,
        chat_context={
            "source_section": "explorer",
            "context_type": "graph_node",
            "context_id": "belief-1",
            "context_summary": "Belief node",
            "context_payload": {"relation_summary": "SUPPORTED_BY -> Memory"},
        },
    )

    history = mem.get_history(session_id)
    assert len(history) == 1
    assert history[0]["metadata"]["chat_context"]
    assert isinstance(history[0]["metadata"]["chat_context"], str)


def test_same_timestamp_messages_keep_turn_order(mem):
    """User/assistant pairs with matching timestamps should remain ordered."""
    session_id = f"test_order_{uuid.uuid4().hex[:8]}"
    ts = "2026-05-09T01:02:14.683000+00:00"

    mem.store("user message", role="user", session_id=session_id, timestamp=ts, turn_order=0)
    mem.store("assistant reply", role="assistant", session_id=session_id, timestamp=ts, turn_order=1)

    history = mem.get_history(session_id)
    ordered = list(reversed(history))

    assert [item["text"] for item in ordered] == ["user message", "assistant reply"]


def test_explicit_user_timestamp_is_preserved(mem):
    """A caller-provided message timestamp should survive persistence."""
    session_id = f"test_explicit_ts_{uuid.uuid4().hex[:8]}"
    user_ts = "2026-05-09T01:02:14.123000+00:00"

    mem.store("sent now", role="user", session_id=session_id, timestamp=user_ts, turn_order=0)

    history = mem.get_history(session_id)
    assert history[0]["metadata"]["timestamp"] == user_ts
