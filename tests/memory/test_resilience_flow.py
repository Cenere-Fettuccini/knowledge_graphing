"""Failure-mode behaviour: truncated lines, missing head, bad dir, crash-recovery."""

from __future__ import annotations

import json
import sys

import pytest

from src.memory import get_memory_manager
from src.memory import _conversation as conv


def test_truncated_jsonl_line_is_skipped(log_dir):
    """A torn trailing JSON line is skipped on read; clean turns still load."""
    memory = get_memory_manager()
    memory.append("s1", "user", "hello")
    memory.append("s1", "assistant", "hi")

    # Simulate a torn write: append a half-written JSON line.
    jsonl = conv.jsonl_path("s1")
    with jsonl.open("a", encoding="utf-8") as f:
        f.write('{"id": "t-broken", "parent_id":')  # no newline, no closing brace

    turns = memory.recent_turns("s1")
    assert len(turns) == 2
    assert all(t["id"] != "t-broken" for t in turns)


def test_missing_head_treated_as_empty_session(log_dir):
    """If the .head file is gone but the .jsonl exists, recent_turns returns []."""
    memory = get_memory_manager()
    memory.append("s1", "user", "hello")

    conv.head_path("s1").unlink()

    assert memory.active_leaf("s1") is None
    assert memory.recent_turns("s1") == []


def test_status_reports_writable_dir(log_dir):
    """status() returns an 'online' shape when the directory is writable."""
    memory = get_memory_manager()
    snap = memory.status()
    assert snap["conversation_log"] == "online"
    assert snap["writable"] is True


@pytest.mark.skipif(sys.platform == "win32", reason="chmod read-only is unreliable on Windows")
def test_status_reports_unwritable_dir(log_dir, monkeypatch):
    """status() reports degraded when the dir is not writable."""
    conv.ensure_dir()
    log_dir.chmod(0o500)
    try:
        memory = get_memory_manager()
        snap = memory.status()
        assert snap["conversation_log"] == "degraded"
        assert snap["writable"] is False
    finally:
        log_dir.chmod(0o700)


def test_append_survives_simulated_crash_between_jsonl_and_head(log_dir, monkeypatch):
    """If a crash occurs after JSONL append but before head update, next read still works.

    The JSONL is the source of truth; the head is a cached pointer. With
    a stale head, recent_turns from the prior head still returns valid
    history; the next clean append rewrites the head atomically.
    """
    memory = get_memory_manager()
    t1 = memory.append("s1", "user", "first")

    # Simulate crash: write a new turn to the JSONL but skip the head update.
    crashed_turn = {
        "id": "t-crashed",
        "parent_id": t1,
        "role": "assistant",
        "text": "never acked",
        "timestamp": conv.now_iso(),
        "metadata": {},
    }
    conv.append_turn("s1", crashed_turn)

    # Active head still points at t1 — recent_turns from there is consistent.
    assert memory.active_leaf("s1") == t1
    turns = memory.recent_turns("s1")
    assert [t["id"] for t in turns] == [t1]

    # A subsequent clean append parents off the active head (t1) and recovers.
    t2 = memory.append("s1", "assistant", "real reply")
    assert memory.active_leaf("s1") == t2
    walked = memory.recent_turns("s1")
    assert [t["id"] for t in walked] == [t2, t1]


def test_corrupt_head_treated_as_empty(log_dir):
    """A garbled .head file does not crash reads; session reads as empty until repaired."""
    memory = get_memory_manager()
    memory.append("s1", "user", "hello")

    conv.head_path("s1").write_text("{not valid json", encoding="utf-8")

    assert memory.active_leaf("s1") is None
    assert memory.recent_turns("s1") == []

    # Next clean append rewrites the head atomically and recovers.
    t2 = memory.append("s1", "assistant", "ok")
    assert memory.active_leaf("s1") == t2
