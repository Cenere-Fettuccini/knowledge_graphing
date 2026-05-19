"""Append a few turns; recent_turns returns them newest-first."""

from __future__ import annotations

from src.memory import get_memory_manager


def test_append_and_recent_turns_returns_newest_first():
    """Linear conversation: each append becomes the active leaf; recent_turns walks back."""
    memory = get_memory_manager()
    t1 = memory.append("s1", "user", "hello")
    t2 = memory.append("s1", "assistant", "hi there")
    t3 = memory.append("s1", "user", "weather?")
    t4 = memory.append("s1", "assistant", "sunny")

    turns = memory.recent_turns("s1", limit=20)

    assert [t["id"] for t in turns] == [t4, t3, t2, t1]
    assert turns[-1]["parent_id"] is None
    assert all(t["role"] in {"user", "assistant"} for t in turns)
    assert memory.active_leaf("s1") == t4


def test_recent_turns_respects_limit():
    """``limit`` caps the number of turns returned."""
    memory = get_memory_manager()
    ids = [memory.append("s1", "user", f"msg-{i}") for i in range(5)]

    turns = memory.recent_turns("s1", limit=3)
    assert [t["id"] for t in turns] == list(reversed(ids))[:3]


def test_recent_turns_empty_session_returns_empty_list():
    """A session with no appends yields ``[]`` and no active leaf."""
    memory = get_memory_manager()
    assert memory.recent_turns("ghost") == []
    assert memory.active_leaf("ghost") is None


def test_singleton_returns_same_instance():
    """Calling ``get_memory_manager`` twice returns the same object."""
    from src.memory._manager import _MemoryManager

    a = get_memory_manager()
    b = get_memory_manager()
    assert a is b
    assert _MemoryManager.get() is a
