"""Session creation on first append → list_sessions → delete_session."""

from __future__ import annotations

from src.memory import get_memory_manager


def test_session_lifecycle_create_list_delete():
    """The full lifecycle: empty → append creates one → list shows it → delete removes."""
    memory = get_memory_manager()

    assert memory.list_sessions() == []

    memory.append("s1", "user", "hello")
    memory.append("s1", "assistant", "hi")

    sessions = memory.list_sessions()
    assert len(sessions) == 1
    entry = sessions[0]
    assert entry["session_id"] == "s1"
    assert entry["turn_count"] == 2
    assert entry["last_active"] is not None

    memory.delete_session("s1")
    assert memory.list_sessions() == []
    assert memory.active_leaf("s1") is None


def test_delete_unknown_session_is_noop():
    """Deleting a session that never existed must not raise."""
    memory = get_memory_manager()
    memory.delete_session("never-existed")  # no exception


def test_multiple_sessions_listed_independently():
    """Sessions are independent files; list_sessions reports each."""
    memory = get_memory_manager()
    memory.append("alpha", "user", "a")
    memory.append("beta", "user", "b")
    memory.append("beta", "assistant", "bb")

    by_id = {s["session_id"]: s for s in memory.list_sessions()}
    assert set(by_id) == {"alpha", "beta"}
    assert by_id["alpha"]["turn_count"] == 1
    assert by_id["beta"]["turn_count"] == 2
