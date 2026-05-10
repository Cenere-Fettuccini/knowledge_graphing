"""Unit tests for the on-disk spillover writer and its MemoryManager wiring."""

from __future__ import annotations

import json
import os

from src.memory.manager import MemoryManager
from src.memory.spillover import SpilloverWriter


# ── SpilloverWriter ──────────────────────────────────────────────────────────


def _read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_spillover_writer_creates_dir(tmp_path):
    target = tmp_path / "spill"
    writer = SpilloverWriter(str(target))
    assert target.exists()
    assert writer.pending_counts() == {"chroma": 0, "neo4j": 0}


def test_record_chroma_store_appends_jsonl(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="hello", metadata={"role": "user"})
    writer.record_chroma_store(text="world", metadata={"role": "assistant"})

    records = _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))
    assert len(records) == 2
    assert records[0]["op"] == "chroma.store"
    assert records[0]["payload"]["text"] == "hello"
    assert records[1]["payload"]["metadata"]["role"] == "assistant"
    assert "attempted_at" in records[0]


def test_record_neo4j_node_and_relationship(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_neo4j_node(
        node_id="person:alice", labels=["Person"], name="Alice", properties={"age": 30}
    )
    writer.record_neo4j_relationship(
        source_id="person:alice",
        target_id="project:foo",
        rel_type="WORKS_ON",
        properties={"since": "2024"},
    )
    records = _read_jsonl(os.path.join(str(tmp_path), "neo4j.jsonl"))
    assert len(records) == 2
    assert records[0]["op"] == "neo4j.upsert_node"
    assert records[1]["op"] == "neo4j.upsert_relationship"


def test_replay_drains_successful_records(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="a", metadata={})
    writer.record_chroma_store(text="b", metadata={})

    seen = []

    def apply(record):
        seen.append(record["payload"]["text"])
        return True

    stats = writer.replay(chroma_apply=apply)
    assert stats["chroma_replayed"] == 2
    assert stats["chroma_remaining"] == 0
    assert seen == ["a", "b"]
    assert _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl")) == []


def test_replay_keeps_failed_records(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="ok", metadata={})
    writer.record_chroma_store(text="fail", metadata={})

    def apply(record):
        return record["payload"]["text"] == "ok"

    stats = writer.replay(chroma_apply=apply)
    assert stats["chroma_replayed"] == 1
    assert stats["chroma_remaining"] == 1

    leftover = _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))
    assert len(leftover) == 1
    assert leftover[0]["payload"]["text"] == "fail"


def test_replay_keeps_records_when_apply_raises(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="boom", metadata={})

    def apply(record):
        raise RuntimeError("backend down")

    stats = writer.replay(chroma_apply=apply)
    assert stats["chroma_replayed"] == 0
    assert stats["chroma_remaining"] == 1
    assert _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))[0]["payload"]["text"] == "boom"


def test_replay_no_op_when_callback_missing(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="a", metadata={})
    stats = writer.replay()
    assert stats == {
        "chroma_replayed": 0,
        "chroma_remaining": 0,
        "neo4j_replayed": 0,
        "neo4j_remaining": 0,
    }
    # The original file is untouched.
    assert len(_read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))) == 1


def test_concurrent_appends_during_replay_survive(tmp_path):
    """Records appended while replay is mid-flight must end up in the live file."""
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="initial", metadata={})

    def apply(record):
        # Simulate a write that arrives during replay processing.
        if record["payload"]["text"] == "initial":
            writer.record_chroma_store(text="arrived-mid-replay", metadata={})
        return True

    stats = writer.replay(chroma_apply=apply)
    assert stats["chroma_replayed"] == 1
    leftover = _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))
    assert len(leftover) == 1
    assert leftover[0]["payload"]["text"] == "arrived-mid-replay"


def test_pending_counts_reflects_unreplayed_records(tmp_path):
    writer = SpilloverWriter(str(tmp_path))
    writer.record_chroma_store(text="a", metadata={})
    writer.record_neo4j_node(node_id="n:1", labels=["X"], name="x", properties=None)
    writer.record_neo4j_node(node_id="n:2", labels=["X"], name="y", properties=None)
    assert writer.pending_counts() == {"chroma": 1, "neo4j": 2}


# ── MemoryManager wiring ─────────────────────────────────────────────────────


class _FakeChroma:
    def __init__(self, *, raise_on_add: bool = False):
        self._raise = raise_on_add
        self.added: list[tuple[str, dict]] = []

    def add_memory(self, text, metadata):
        if self._raise:
            raise RuntimeError("chroma offline")
        self.added.append((text, dict(metadata)))
        return f"id-{len(self.added)}"


class _FakeNeo4j:
    """Minimal Neo4j stand-in. Behaviour is controlled by the *available* flag."""

    def __init__(self, *, available: bool = True):
        self.available = available
        self.driver = object() if available else None
        self.nodes: list[dict] = []
        self.edges: list[dict] = []

    def verify_connection(self):
        return self.available

    def upsert_node_with_labels(self, *, node_id, labels, name, properties):
        if not self.available:
            return ""
        self.nodes.append({
            "node_id": node_id, "labels": list(labels),
            "name": name, "properties": dict(properties or {}),
        })
        return node_id

    def upsert_relationship(self, *, source_id, target_id, rel_type, properties):
        if not self.available:
            return False
        self.edges.append({
            "source_id": source_id, "target_id": target_id,
            "rel_type": rel_type, "properties": dict(properties or {}),
        })
        return True


def _build_manager(tmp_path, *, chroma=None, neo4j=None, chroma_available=True):
    manager = MemoryManager.__new__(MemoryManager)
    manager.chroma = chroma or _FakeChroma()
    manager.neo4j = neo4j or _FakeNeo4j()
    manager.spillover = SpilloverWriter(str(tmp_path))
    manager._health_cache = {}
    manager._health_cache_time = 0
    manager._health_ttl = 60
    manager._is_chroma_available = lambda: chroma_available
    return manager


def test_store_spills_when_chroma_unavailable(tmp_path):
    manager = _build_manager(tmp_path, chroma_available=False)
    manager.store("hello", role="user", session_id="s1")

    records = _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))
    assert len(records) == 1
    assert records[0]["payload"]["text"] == "hello"
    assert records[0]["payload"]["metadata"]["role"] == "user"
    assert records[0]["payload"]["metadata"]["session_id"] == "s1"


def test_store_spills_when_chroma_raises(tmp_path):
    chroma = _FakeChroma(raise_on_add=True)
    manager = _build_manager(tmp_path, chroma=chroma, chroma_available=True)

    memory_id = manager.store("oops", role="user", session_id="s1")
    assert memory_id is None

    records = _read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))
    assert len(records) == 1
    assert records[0]["payload"]["text"] == "oops"


def test_upsert_node_spills_when_neo4j_offline(tmp_path):
    neo4j = _FakeNeo4j(available=False)
    manager = _build_manager(tmp_path, neo4j=neo4j)

    result = manager.upsert_node(
        node_id="person:alice", labels=["Person"], name="Alice", properties={"role": "engineer"}
    )
    assert result == "person:alice"  # synthetic return so callers don't crash

    records = _read_jsonl(os.path.join(str(tmp_path), "neo4j.jsonl"))
    assert len(records) == 1
    assert records[0]["op"] == "neo4j.upsert_node"
    assert records[0]["payload"]["node_id"] == "person:alice"


def test_upsert_relationship_spills_when_neo4j_offline(tmp_path):
    neo4j = _FakeNeo4j(available=False)
    manager = _build_manager(tmp_path, neo4j=neo4j)

    ok = manager.upsert_relationship(
        source_id="person:alice",
        target_id="project:foo",
        rel_type="WORKS_ON",
        properties={"since": "2024"},
    )
    assert ok is False

    records = _read_jsonl(os.path.join(str(tmp_path), "neo4j.jsonl"))
    assert len(records) == 1
    assert records[0]["op"] == "neo4j.upsert_relationship"
    assert records[0]["payload"]["rel_type"] == "WORKS_ON"


def test_replay_spillover_drains_chroma_and_neo4j(tmp_path):
    chroma = _FakeChroma()
    neo4j = _FakeNeo4j(available=True)
    manager = _build_manager(tmp_path, chroma=chroma, neo4j=neo4j)
    manager.is_graph_online = lambda: True

    # Pre-seed spillover with both kinds of records (as if they failed previously).
    manager.spillover.record_chroma_store(
        text="recovered", metadata={"role": "user", "session_id": "s1"}
    )
    manager.spillover.record_neo4j_node(
        node_id="person:bob", labels=["Person"], name="Bob", properties={}
    )
    manager.spillover.record_neo4j_relationship(
        source_id="person:bob", target_id="project:bar", rel_type="LIKES", properties={}
    )

    stats = manager.replay_spillover()
    assert stats["chroma_replayed"] == 1
    assert stats["neo4j_replayed"] == 2
    assert stats["chroma_remaining"] == 0
    assert stats["neo4j_remaining"] == 0
    assert chroma.added[0][0] == "recovered"
    assert any(n["node_id"] == "person:bob" for n in neo4j.nodes)
    assert any(e["rel_type"] == "LIKES" for e in neo4j.edges)


def test_replay_spillover_skips_offline_backends(tmp_path):
    """If a backend is still offline, its records stay on disk for the next attempt."""
    manager = _build_manager(tmp_path, chroma_available=False)
    manager.is_graph_online = lambda: False

    manager.spillover.record_chroma_store(text="still-down", metadata={})
    manager.spillover.record_neo4j_node(
        node_id="x:1", labels=["X"], name="x", properties={}
    )

    stats = manager.replay_spillover()
    assert stats == {
        "chroma_replayed": 0,
        "chroma_remaining": 0,
        "neo4j_replayed": 0,
        "neo4j_remaining": 0,
    }
    # Records were not touched (drain was skipped because callbacks were None).
    assert len(_read_jsonl(os.path.join(str(tmp_path), "chroma.jsonl"))) == 1
    assert len(_read_jsonl(os.path.join(str(tmp_path), "neo4j.jsonl"))) == 1


def test_scheduler_tick_invokes_replay(tmp_path):
    """The scheduler tick must call replay_spillover before the analyzer pass."""
    from src.agent_platform.analyzers.knowledge import AnalysisResult
    from src.agent_platform.analyzers.scheduler import AnalyzerScheduler

    call_order: list[str] = []

    class _MemoryWithReplay:
        def replay_spillover(self):
            call_order.append("replay")
            return {"chroma_replayed": 0, "neo4j_replayed": 0}

    class _Analyzer:
        def analyze_pending(self, *, batch_size, model=None):
            call_order.append("analyze")
            return AnalysisResult(
                run_id="r",
                processed_messages=0,
                entities_written=0,
                relationships_written=0,
            )

    class _FakeAPScheduler:
        def add_job(self, *args, **kwargs): pass
        def start(self): pass
        def shutdown(self, wait=False): pass

    scheduler = AnalyzerScheduler(
        memory=_MemoryWithReplay(),
        tick_seconds=300,
        batch_size=10,
        analyzer_factory=lambda mem: _Analyzer(),
        scheduler_factory=lambda: _FakeAPScheduler(),
    )
    scheduler.tick()
    assert call_order == ["replay", "analyze"]
