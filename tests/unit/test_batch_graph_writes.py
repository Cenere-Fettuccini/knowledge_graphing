"""Tests for the transactional graph batch context manager and execute_batch."""

from __future__ import annotations

from src.memory.manager import GraphWriteBatch, MemoryManager
from src.memory.spillover import SpilloverWriter
from src.memory.stores.neo4j_store import Neo4jStore


# ── Neo4jStore.execute_batch ─────────────────────────────────────────────────


class _FakeTx:
    """Captures every ``run`` call inside one transaction."""

    def __init__(self, *, raise_on=None):
        self.runs: list[tuple[str, dict]] = []
        self.committed = False
        self.rolled_back = False
        self._raise_on = raise_on  # index of run() call that should raise

    def run(self, cypher, **params):
        idx = len(self.runs)
        self.runs.append((cypher, params))
        if self._raise_on is not None and idx == self._raise_on:
            raise RuntimeError("cypher blew up")

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


class _FakeSession:
    def __init__(self, tx):
        self._tx = tx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def begin_transaction(self):
        outer = self

        class _TxCtx:
            def __enter__(self_inner):
                return outer._tx

            def __exit__(self_inner, exc_type, exc, tb):
                if exc_type is not None:
                    outer._tx.rolled_back = True
                return False

        return _TxCtx()


class _FakeDriver:
    def __init__(self, tx):
        self._tx = tx

    def session(self):
        return _FakeSession(self._tx)


def _store_with_tx(tx):
    store = Neo4jStore.__new__(Neo4jStore)
    store.driver = _FakeDriver(tx)
    return store


def test_execute_batch_runs_all_ops_in_one_transaction():
    tx = _FakeTx()
    store = _store_with_tx(tx)

    store.execute_batch([
        ("node", {
            "node_id": "person:alice", "labels": ["Person"],
            "name": "Alice", "properties": {"role": "engineer"},
        }),
        ("edge", {
            "source_id": "person:alice", "target_id": "project:foo",
            "rel_type": "WORKS_ON", "properties": {"since": "2024"},
        }),
    ])

    assert len(tx.runs) == 2
    assert tx.committed is True
    assert tx.rolled_back is False
    # Node cypher carries the labels clause and props.
    node_cypher, node_params = tx.runs[0]
    assert ":Person" in node_cypher
    assert node_params["node_id"] == "person:alice"
    assert node_params["props"]["name"] == "Alice"
    # Edge cypher uses the SCREAMING_SNAKE_CASE rel type.
    edge_cypher, edge_params = tx.runs[1]
    assert "WORKS_ON" in edge_cypher
    assert edge_params["source_id"] == "person:alice"


def test_execute_batch_propagates_failures_so_caller_can_rollback():
    tx = _FakeTx(raise_on=1)
    store = _store_with_tx(tx)

    try:
        store.execute_batch([
            ("node", {"node_id": "n1", "labels": ["X"], "name": "x", "properties": {}}),
            ("node", {"node_id": "n2", "labels": ["X"], "name": "y", "properties": {}}),
            ("node", {"node_id": "n3", "labels": ["X"], "name": "z", "properties": {}}),
        ])
        raise AssertionError("execute_batch must not swallow cypher errors")
    except RuntimeError:
        pass

    # First op ran, second op blew up, third never ran.
    assert len(tx.runs) == 2
    assert tx.committed is False
    assert tx.rolled_back is True


def test_execute_batch_no_op_for_empty_input():
    tx = _FakeTx()
    store = _store_with_tx(tx)
    store.execute_batch([])
    assert tx.runs == []
    assert tx.committed is False  # nothing to commit


def test_execute_batch_raises_when_driver_unavailable():
    store = Neo4jStore.__new__(Neo4jStore)
    store.driver = None
    store.verify_connection = lambda: False  # type: ignore[assignment]

    raised = False
    try:
        store.execute_batch([("node", {"node_id": "n", "labels": ["X"], "name": "x", "properties": {}})])
    except RuntimeError:
        raised = True
    assert raised is True


def test_execute_batch_rejects_unknown_op_type():
    tx = _FakeTx()
    store = _store_with_tx(tx)
    raised = False
    try:
        store.execute_batch([("nonsense", {})])
    except ValueError:
        raised = True
    assert raised is True
    # The bad op was raised inside the tx, so the tx rolled back.
    assert tx.rolled_back is True
    assert tx.committed is False


# ── MemoryManager.batch_graph_writes ─────────────────────────────────────────


class _FakeNeo4j:
    def __init__(self, *, raise_on_batch: bool = False):
        self._raise = raise_on_batch
        self.batches: list[list[tuple[str, dict]]] = []

    def execute_batch(self, ops):
        if self._raise:
            raise RuntimeError("neo4j down")
        self.batches.append(list(ops))


def _build_manager(tmp_path, *, neo4j=None):
    manager = MemoryManager.__new__(MemoryManager)
    manager.neo4j = neo4j or _FakeNeo4j()
    manager.spillover = SpilloverWriter(str(tmp_path))
    manager._health_cache = {}
    manager._health_cache_time = 0
    manager._health_ttl = 60
    return manager


def _read_jsonl(path):
    import json
    import os

    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def test_batch_commits_when_neo4j_is_healthy(tmp_path):
    neo4j = _FakeNeo4j()
    manager = _build_manager(tmp_path, neo4j=neo4j)

    with manager.batch_graph_writes() as batch:
        batch.upsert_node(node_id="person:alice", labels=["Person"], name="Alice")
        batch.upsert_relationship(
            source_id="person:alice", target_id="project:foo",
            rel_type="WORKS_ON", properties={"since": 2024},
        )

    assert batch.committed is True
    assert batch.spilled is False
    assert len(neo4j.batches) == 1
    assert len(neo4j.batches[0]) == 2  # both ops in one transaction
    # Spillover untouched.
    assert _read_jsonl(str(tmp_path / "neo4j.jsonl")) == []


def test_batch_spills_every_op_when_transaction_fails(tmp_path):
    """If the commit fails, no node should land in Neo4j and ALL ops spill."""
    neo4j = _FakeNeo4j(raise_on_batch=True)
    manager = _build_manager(tmp_path, neo4j=neo4j)

    with manager.batch_graph_writes() as batch:
        batch.upsert_node(node_id="person:alice", labels=["Person"], name="Alice")
        batch.upsert_node(node_id="person:bob", labels=["Person"], name="Bob")
        batch.upsert_relationship(
            source_id="person:alice", target_id="person:bob",
            rel_type="KNOWS", properties={},
        )

    assert batch.committed is False
    assert batch.spilled is True

    spilled = _read_jsonl(str(tmp_path / "neo4j.jsonl"))
    assert len(spilled) == 3
    ops = [r["op"] for r in spilled]
    assert ops == [
        "neo4j.upsert_node",
        "neo4j.upsert_node",
        "neo4j.upsert_relationship",
    ]


def test_batch_spills_on_caller_exception_and_reraises(tmp_path):
    """If the caller raises mid-block, queued ops must spill and the exception bubble up."""
    neo4j = _FakeNeo4j()
    manager = _build_manager(tmp_path, neo4j=neo4j)

    raised = False
    try:
        with manager.batch_graph_writes() as batch:
            batch.upsert_node(node_id="n1", labels=["X"], name="x")
            raise RuntimeError("interrupted mid-batch")
    except RuntimeError:
        raised = True
    assert raised is True

    # Nothing committed to Neo4j.
    assert neo4j.batches == []
    # The single queued op was spilled.
    spilled = _read_jsonl(str(tmp_path / "neo4j.jsonl"))
    assert len(spilled) == 1
    assert spilled[0]["op"] == "neo4j.upsert_node"
    assert spilled[0]["payload"]["node_id"] == "n1"


def test_empty_batch_is_a_noop(tmp_path):
    neo4j = _FakeNeo4j()
    manager = _build_manager(tmp_path, neo4j=neo4j)

    with manager.batch_graph_writes() as batch:
        pass

    assert neo4j.batches == []
    assert batch.committed is False
    assert batch.spilled is False
    assert _read_jsonl(str(tmp_path / "neo4j.jsonl")) == []


def test_batch_returns_synthetic_ids_so_caller_logic_keeps_working(tmp_path):
    """The yielded batch object mirrors MemoryManager's signatures."""
    manager = _build_manager(tmp_path)
    with manager.batch_graph_writes() as batch:
        result = batch.upsert_node(node_id="person:alice", labels=["Person"], name="Alice")
        assert result == "person:alice"
        ok = batch.upsert_relationship(
            source_id="a", target_id="b", rel_type="KNOWS", properties={},
        )
        assert ok is True


def test_graph_write_batch_records_ops_in_order():
    batch = GraphWriteBatch()
    batch.upsert_node(node_id="n1", labels=["X"], name="x")
    batch.upsert_relationship(source_id="n1", target_id="n2", rel_type="KNOWS")
    batch.upsert_node(node_id="n2", labels=["X"], name="y")

    assert [op for op, _ in batch.ops] == ["node", "edge", "node"]
    assert batch.ops[0][1]["node_id"] == "n1"
    assert batch.ops[1][1]["rel_type"] == "KNOWS"
