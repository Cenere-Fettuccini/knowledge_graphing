"""Forking via explicit ``parent_id``; switching branches via ``set_active``."""

from __future__ import annotations

import pytest

from src.memory import get_memory_manager


def test_fork_creates_sibling_branch_and_becomes_active():
    """Appending with an explicit parent_id forks the conversation."""
    memory = get_memory_manager()
    root = memory.append("s1", "user", "hello")
    a1 = memory.append("s1", "assistant", "original reply")

    # Fork: sibling of a1 sharing root as parent.
    a2 = memory.append("s1", "assistant", "alt reply", parent_id=root)

    assert memory.active_leaf("s1") == a2
    turns = memory.recent_turns("s1")
    assert [t["id"] for t in turns] == [a2, root]
    assert a1 not in {t["id"] for t in turns}


def test_set_active_switches_branch():
    """set_active flips which leaf subsequent recent_turns walks from."""
    memory = get_memory_manager()
    root = memory.append("s1", "user", "hello")
    a1 = memory.append("s1", "assistant", "original")
    a2 = memory.append("s1", "assistant", "alt", parent_id=root)

    memory.set_active("s1", a1)
    assert memory.active_leaf("s1") == a1
    assert [t["id"] for t in memory.recent_turns("s1")] == [a1, root]

    memory.set_active("s1", a2)
    assert [t["id"] for t in memory.recent_turns("s1")] == [a2, root]


def test_list_branches_reports_each_leaf():
    """Every leaf shows up exactly once with the expected metadata."""
    memory = get_memory_manager()
    root = memory.append("s1", "user", "hello")
    a1 = memory.append("s1", "assistant", "original reply text")
    a2 = memory.append(
        "s1", "assistant", "alt reply text",
        parent_id=root, metadata={"branch_label": "alt"},
    )

    branches = memory.list_branches("s1")
    by_id = {b["leaf_id"]: b for b in branches}

    assert set(by_id) == {a1, a2}
    assert by_id[a1]["turn_count"] == 2
    assert by_id[a2]["turn_count"] == 2
    assert by_id[a2]["label"] == "alt"
    assert by_id[a1]["label"] is None
    assert by_id[a2]["is_active"] is True
    assert by_id[a1]["is_active"] is False
    assert "original" in by_id[a1]["head_text_preview"]


def test_set_active_unknown_leaf_raises():
    """An unknown leaf id raises ValueError without touching the head."""
    memory = get_memory_manager()
    root = memory.append("s1", "user", "hello")
    with pytest.raises(ValueError):
        memory.set_active("s1", "t-doesnotexist")
    assert memory.active_leaf("s1") == root


def test_recent_turns_named_leaf_walks_that_branch():
    """Passing ``leaf_id`` explicitly walks that branch even if not active."""
    memory = get_memory_manager()
    root = memory.append("s1", "user", "hello")
    a1 = memory.append("s1", "assistant", "original")
    memory.append("s1", "assistant", "alt", parent_id=root)  # makes a2 active

    walked = memory.recent_turns("s1", leaf_id=a1)
    assert [t["id"] for t in walked] == [a1, root]
