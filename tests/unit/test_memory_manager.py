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


def test_mark_failed_stamps_failure_metadata():
    """Failed rows must leave the live queue but carry a reason for inspection."""
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.mark_failed(["c1", "c2"], reason="invalid_json_response", run_id="r-123")
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]
    assert captured["patch"]["analyzed"] is True
    assert captured["patch"]["analyzer_status"] == "failed"
    assert captured["patch"]["analyzer_failure_reason"] == "invalid_json_response"
    assert captured["patch"]["analysis_run_id"] == "r-123"
    assert "analyzer_failed_at" in captured["patch"]


def test_list_failed_filters_on_analyzer_status():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            captured["where"] = where
            captured["limit"] = limit
            return [
                {"id": "c1", "text": "x", "metadata": {"analyzer_status": "failed"}},
            ]

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    rows = manager.list_failed(limit=25)
    assert len(rows) == 1
    assert captured["where"] == {"analyzer_status": "failed"}
    assert captured["limit"] == 25


def test_count_failed_uses_chroma_filter():
    manager = MemoryManager.__new__(MemoryManager)

    class FakeChroma:
        def count_where(self, where=None):
            assert where == {"analyzer_status": "failed"}
            return 7

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    assert manager.count_failed() == 7


def test_retry_failed_resets_status_so_queue_picks_them_up():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.retry_failed(["c1", "c2"])
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]
    assert captured["patch"]["analyzed"] is False
    assert captured["patch"]["analyzer_status"] == "pending"
    assert captured["patch"]["analyzer_failure_reason"] == ""


def test_retry_failed_with_no_ids_drains_entire_dlq():
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            return [
                {"id": "c1", "metadata": {"analyzer_status": "failed"}},
                {"id": "c2", "metadata": {"analyzer_status": "failed"}},
            ]

        def update_metadata(self, ids, patch):
            captured["ids"] = list(ids)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    n = manager.retry_failed()  # no ids → drain everything
    assert n == 2
    assert captured["ids"] == ["c1", "c2"]


def test_retry_failed_returns_zero_when_dlq_is_empty():
    manager = MemoryManager.__new__(MemoryManager)

    class FakeChroma:
        def list_where(self, where, limit=50, offset=0):
            return []

        def update_metadata(self, ids, patch):
            raise AssertionError("update_metadata must not be called when DLQ is empty")

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    assert manager.retry_failed() == 0


def test_mark_analyzed_records_success_status():
    """The success path should also stamp analyzer_status so old/new rows have a uniform shape."""
    manager = MemoryManager.__new__(MemoryManager)

    captured = {}

    class FakeChroma:
        def update_metadata(self, ids, patch):
            captured["patch"] = dict(patch)
            return len(ids)

    manager.chroma = FakeChroma()
    manager._is_chroma_available = lambda: True

    manager.mark_analyzed(["c1"], run_id="r")
    assert captured["patch"]["analyzed"] is True
    assert captured["patch"]["analyzer_status"] == "success"


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
    # Live writes must be tagged so the analyzer queue can serve them ahead
    # of any bulk-imported backlog (S2.3).
    assert captured["metadata"]["bulk_imported"] is False


class _FakeChromaQueue:
    """Captures list_where queries and returns whatever the test seeded."""

    def __init__(self, *, live=None, bulk=None):
        self._live = list(live or [])
        self._bulk = list(bulk or [])
        self.update_calls: list[tuple[list, dict]] = []
        self.list_where_calls: list[dict] = []

    def list_where(self, where, limit=50, offset=0):
        self.list_where_calls.append(where)
        clauses = where.get("$and") if isinstance(where, dict) else None
        flag = None
        if clauses:
            for clause in clauses:
                if isinstance(clause, dict) and "bulk_imported" in clause:
                    flag = clause["bulk_imported"]
        if flag is False:
            return self._live[:limit]
        if flag is True:
            return self._bulk[:limit]
        # No flag → "all unanalyzed" path used by the legacy backfill.
        return (self._live + self._bulk)[:limit]

    def update_metadata(self, ids, patch):
        self.update_calls.append((list(ids), dict(patch)))
        return len(ids)


def _make_manager_with_chroma(chroma) -> MemoryManager:
    manager = MemoryManager.__new__(MemoryManager)
    manager.chroma = chroma
    manager._is_chroma_available = lambda: True
    manager._bulk_flag_backfilled = True  # skip legacy backfill in tests that don't exercise it
    return manager


def test_list_unanalyzed_serves_live_items_before_bulk_backlog():
    """A bulk backfill of historical rows must not block live conversation analysis."""
    live = [
        {"id": "live-1", "text": "hi", "metadata": {"bulk_imported": False, "timestamp": "2026-05-11T10:00:00Z"}},
    ]
    bulk = [
        {"id": "bulk-2019", "text": "journal 2019", "metadata": {"bulk_imported": True, "timestamp": "2019-04-12T00:00:00Z"}},
        {"id": "bulk-2020", "text": "journal 2020", "metadata": {"bulk_imported": True, "timestamp": "2020-04-12T00:00:00Z"}},
    ]
    manager = _make_manager_with_chroma(_FakeChromaQueue(live=live, bulk=bulk))

    rows = manager.list_unanalyzed(limit=10)

    assert [r["id"] for r in rows] == ["live-1", "bulk-2019", "bulk-2020"]


def test_list_unanalyzed_skips_bulk_query_when_live_fills_the_batch():
    """No need to scan the bulk pool if the live pool already saturated the batch."""
    live = [
        {"id": f"live-{i}", "text": "...", "metadata": {"bulk_imported": False, "timestamp": f"2026-05-11T10:{i:02d}:00Z"}}
        for i in range(5)
    ]
    bulk = [{"id": "bulk-1", "text": "...", "metadata": {"bulk_imported": True, "timestamp": "2019-01-01T00:00:00Z"}}]
    chroma = _FakeChromaQueue(live=live, bulk=bulk)
    manager = _make_manager_with_chroma(chroma)

    rows = manager.list_unanalyzed(limit=5)

    assert [r["id"] for r in rows] == [f"live-{i}" for i in range(5)]
    # Only the live query should have been issued — bulk pool stays untouched.
    assert len(chroma.list_where_calls) == 1


def test_list_unanalyzed_returns_bulk_when_live_pool_empty():
    """With no live work, the bulk backlog drains oldest-first."""
    bulk = [
        {"id": "bulk-2019", "text": "...", "metadata": {"bulk_imported": True, "timestamp": "2019-04-12T00:00:00Z"}},
        {"id": "bulk-2024", "text": "...", "metadata": {"bulk_imported": True, "timestamp": "2024-04-12T00:00:00Z"}},
    ]
    manager = _make_manager_with_chroma(_FakeChromaQueue(live=[], bulk=bulk))

    rows = manager.list_unanalyzed(limit=10)

    assert [r["id"] for r in rows] == ["bulk-2019", "bulk-2024"]


def test_canonicalization_methods_delegate_to_neo4j_store():
    """The MemoryManager surface for S2.4 must pass through cleanly so apps
    never need to reach into ``memory.neo4j`` directly."""
    manager = MemoryManager.__new__(MemoryManager)
    calls = {}

    class FakeNeo4j:
        def list_distinct_labels(self):
            calls["list_distinct_labels"] = True
            return ["Person", "Belief"]

        def list_named_nodes_by_label(self, label, *, exclude_roots=True):
            calls["list_named_nodes_by_label"] = (label, exclude_roots)
            return [{"id": "p1", "name": "Alice"}]

        def count_node_connections(self, ids):
            calls["count_node_connections"] = list(ids)
            return {nid: 0 for nid in ids}

        def create_merge_proposal(self, **kwargs):
            calls["create_merge_proposal"] = kwargs
            return kwargs["proposal_id"]

        def list_merge_proposals(self, *, status, limit):
            calls["list_merge_proposals"] = (status, limit)
            return [{"id": "merge:person:abc"}]

        def get_merge_proposal(self, proposal_id):
            calls["get_merge_proposal"] = proposal_id
            return {"id": proposal_id, "status": "pending"}

        def apply_merge_proposal(self, proposal_id):
            calls["apply_merge_proposal"] = proposal_id
            return {"merged": 1, "skipped": 0, "rels_rewired": 3}

        def dismiss_merge_proposal(self, proposal_id):
            calls["dismiss_merge_proposal"] = proposal_id
            return True

    manager.neo4j = FakeNeo4j()

    assert manager.list_distinct_graph_labels(exclude={"Belief"}) == ["Person"]
    assert manager.list_named_nodes_by_label("Person") == [{"id": "p1", "name": "Alice"}]
    assert calls["list_named_nodes_by_label"] == ("Person", True)

    assert manager.count_node_connections(["p1"]) == {"p1": 0}

    pid = manager.create_merge_proposal(
        proposal_id="merge:person:abc",
        label="Person",
        primary_id="p1",
        duplicate_ids=["p2"],
        scores=[0.95],
        canonical_name="Alice",
    )
    assert pid == "merge:person:abc"
    assert calls["create_merge_proposal"]["primary_id"] == "p1"

    assert manager.list_merge_proposals(status="pending", limit=50)[0]["id"] == "merge:person:abc"
    assert calls["list_merge_proposals"] == ("pending", 50)

    assert manager.get_merge_proposal("merge:person:abc")["status"] == "pending"
    assert manager.apply_merge_proposal("merge:person:abc")["merged"] == 1
    assert manager.dismiss_merge_proposal("merge:person:abc") is True


def test_backfill_bulk_imported_flag_patches_legacy_rows_once():
    """Legacy rows missing bulk_imported get tagged on the first analyzer pass."""
    legacy = [
        {"id": "legacy-1", "text": "old", "metadata": {"analyzed": False, "is_ephemeral": False}},
        # Already-tagged row should not be re-patched.
        {"id": "live-1", "text": "new", "metadata": {"analyzed": False, "is_ephemeral": False, "bulk_imported": False}},
    ]

    class FakeChroma:
        def __init__(self):
            self.list_where_calls = []
            self.updates: list[tuple[list, dict]] = []

        def list_where(self, where, limit=50, offset=0):
            self.list_where_calls.append(where)
            clauses = where.get("$and") if isinstance(where, dict) else []
            has_flag = any(isinstance(c, dict) and "bulk_imported" in c for c in clauses)
            if has_flag:
                return []  # don't care for this test; we're focused on the backfill
            return legacy

        def update_metadata(self, ids, patch):
            self.updates.append((list(ids), dict(patch)))
            return len(ids)

    chroma = FakeChroma()
    manager = MemoryManager.__new__(MemoryManager)
    manager.chroma = chroma
    manager._is_chroma_available = lambda: True
    manager._bulk_flag_backfilled = False

    manager.list_unanalyzed(limit=10)

    assert chroma.updates == [(["legacy-1"], {"bulk_imported": False})]

    # Second call must not re-patch — the flag short-circuits.
    chroma.updates.clear()
    manager.list_unanalyzed(limit=10)
    assert chroma.updates == []
