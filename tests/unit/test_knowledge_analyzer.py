import json
from contextlib import contextmanager

import pytest

from src.agent_platform.analyzers.knowledge import (
    AnalysisResult,
    KnowledgeAnalyzer,
    SYSTEM_PROMPT,
)
from src.agent_platform.analyzers.local_llm import LocalLLMUnavailable


class _FakeBatch:
    """Test double for ``MemoryManager.batch_graph_writes``'s yielded batch.

    Records ops as they're queued and lets the surrounding fake memory commit
    them in one shot — mirrors the real semantics where writes are atomic.
    """

    def __init__(self):
        self.ops: list[tuple[str, dict]] = []
        self.committed = False

    def upsert_node(self, *, node_id, labels, name, properties=None):
        self.ops.append((
            "node",
            {"id": node_id, "labels": list(labels), "name": name, "props": dict(properties or {})},
        ))
        return node_id

    def upsert_relationship(self, *, source_id, target_id, rel_type, properties=None):
        self.ops.append((
            "edge",
            {"src": source_id, "tgt": target_id, "type": rel_type, "props": dict(properties or {})},
        ))
        return True


class _FakeMemory:
    def __init__(self, *, user_root, batch, schema=None, fail_batch_commit=False):
        self._user_root = user_root
        self._batch = batch
        self._schema = schema or {"labels": [], "relationship_types": [], "entities": []}
        self._fail_batch_commit = fail_batch_commit
        self.upserted_nodes: list[dict] = []
        self.upserted_relationships: list[dict] = []
        self.batches_committed = 0
        self.batches_spilled = 0
        self.marked_analyzed: list[tuple[list, str | None]] = []
        self.marked_failed: list[tuple[list, str, str | None]] = []
        self.failed_count_value = 0

    def get_user_root(self):
        return self._user_root

    def list_unanalyzed(self, limit=20):
        return self._batch[:limit]

    def graph_schema_snapshot(self):
        return self._schema

    def count_unanalyzed(self):
        return len(self._batch)

    def count_failed(self):
        return self.failed_count_value

    @contextmanager
    def batch_graph_writes(self):
        batch = _FakeBatch()
        yield batch
        if self._fail_batch_commit:
            self.batches_spilled += 1
            return
        for op_type, payload in batch.ops:
            if op_type == "node":
                self.upserted_nodes.append(payload)
            elif op_type == "edge":
                self.upserted_relationships.append(payload)
        batch.committed = True
        self.batches_committed += 1

    def mark_analyzed(self, ids, run_id=None):
        self.marked_analyzed.append((list(ids), run_id))
        return len(ids)

    def mark_failed(self, ids, reason, run_id=None):
        self.marked_failed.append((list(ids), reason, run_id))
        return len(ids)


class _FakeLLM:
    def __init__(self, *, response="{}", available=True, models=None):
        self._response = response
        self._available = available
        self._models = models or [{"id": "qwen2.5-3b-instruct"}]
        self.calls: list[dict] = []
        self.default_model = "qwen2.5-3b-instruct"

    def is_available(self):
        return self._available

    def list_models(self):
        if not self._available:
            raise LocalLLMUnavailable("offline")
        return self._models

    def chat_completion(self, messages, *, model=None, json_mode=True, temperature=0.2):
        self.calls.append({"messages": messages, "model": model, "json_mode": json_mode})
        if not self._available:
            raise LocalLLMUnavailable("offline")
        return self._response


def _user_root():
    return {"id": "user:kevin", "name": "Kevin", "labels": ["Person", "User"], "label": "User"}


def test_analyze_pending_skips_when_no_user_root():
    memory = _FakeMemory(user_root=None, batch=[{"id": "a", "text": "hi"}])
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM())
    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is True
    assert result.reason == "no_user_root"
    assert memory.upserted_nodes == []
    assert memory.marked_analyzed == []


def test_analyze_pending_skips_when_queue_empty():
    memory = _FakeMemory(user_root=_user_root(), batch=[])
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM())
    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is True
    assert result.reason == "queue_empty"


def test_analyze_pending_skips_when_local_llm_unreachable():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "a", "text": "I work at Acme.", "metadata": {"role": "user"}}],
    )
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(available=False))
    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is True
    assert result.reason.startswith("llm_unavailable")
    # Crucially: queue is NOT marked analyzed when the LLM call fails — so the
    # next scheduler tick will retry the same batch.
    assert memory.marked_analyzed == []


def test_analyze_pending_writes_entities_and_relationships():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[
            {"id": "c1", "text": "I work at Acme Corp.", "metadata": {"role": "user"}},
            {"id": "c2", "text": "My friend Alice loves jazz.", "metadata": {"role": "user"}},
        ],
        schema={"labels": ["Person", "User"], "relationship_types": ["KNOWS"], "entities": []},
    )
    payload = {
        "entities": [
            {"id": "org:acme-corp", "labels": ["Organisation"], "name": "Acme Corp", "props": {}},
            {"id": "person:alice", "labels": ["Person"], "name": "Alice", "props": {"likes": "jazz"}},
        ],
        "relationships": [
            {"from": "user:kevin", "to": "org:acme-corp", "type": "WORKS_AT"},
            {"from": "user:kevin", "to": "person:alice", "type": "KNOWS"},
        ],
        "evidence_chroma_ids": ["c1", "c2"],
    }
    llm = _FakeLLM(response=json.dumps(payload))
    analyzer = KnowledgeAnalyzer(memory=memory, llm=llm)

    result = analyzer.analyze_pending(batch_size=10, model="custom-model")

    assert result.skipped is False
    assert result.entities_written == 2
    assert result.relationships_written == 2
    assert result.processed_messages == 2

    # Entities upserted with the proposed multi-label list.
    names = sorted(e["name"] for e in memory.upserted_nodes)
    assert names == ["Acme Corp", "Alice"]
    assert all("provenance_run_ids" in e["props"] for e in memory.upserted_nodes)

    # Relationships anchored to the user root.
    rel_types = sorted(r["type"] for r in memory.upserted_relationships)
    assert rel_types == ["KNOWS", "WORKS_AT"]
    assert all(r["src"] == "user:kevin" for r in memory.upserted_relationships)

    # Chroma rows marked analyzed with the run id.
    marked_ids, run_id = memory.marked_analyzed[0]
    assert sorted(marked_ids) == ["c1", "c2"]
    assert run_id == result.run_id

    # Custom model honoured.
    assert llm.calls[0]["model"] == "custom-model"
    # Prompt included the system prompt.
    assert llm.calls[0]["messages"][0]["content"] == SYSTEM_PROMPT


def test_analyze_pending_marks_batch_even_with_empty_extraction():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "c1", "text": "hello", "metadata": {"role": "user"}}],
    )
    llm = _FakeLLM(response='{"entities": [], "relationships": [], "evidence_chroma_ids": []}')
    analyzer = KnowledgeAnalyzer(memory=memory, llm=llm)

    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is False
    assert result.entities_written == 0
    assert result.relationships_written == 0
    assert memory.marked_analyzed[0][0] == ["c1"]


def test_analyze_pending_handles_fenced_json():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "c1", "text": "I like tea", "metadata": {"role": "user"}}],
    )
    response = "```json\n" + json.dumps(
        {
            "entities": [{"id": "topic:tea", "labels": ["Topic"], "name": "Tea", "props": {}}],
            "relationships": [{"from": "user:kevin", "to": "topic:tea", "type": "LIKES"}],
        }
    ) + "\n```"
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(response=response))
    result = analyzer.analyze_pending(batch_size=10)
    assert result.entities_written == 1
    assert result.relationships_written == 1


def test_analyze_pending_runs_one_atomic_batch_per_call():
    """The whole extraction must go through batch_graph_writes once, not as
    independent upsert_node/upsert_relationship calls — so a mid-batch failure
    can roll the graph back cleanly."""
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "c1", "text": "I work at Acme.", "metadata": {"role": "user"}}],
    )
    payload = {
        "entities": [
            {"id": "org:acme-corp", "labels": ["Organisation"], "name": "Acme", "props": {}},
        ],
        "relationships": [
            {"from": "user:kevin", "to": "org:acme-corp", "type": "WORKS_AT"},
        ],
    }
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(response=json.dumps(payload)))
    analyzer.analyze_pending(batch_size=10)

    assert memory.batches_committed == 1
    assert memory.batches_spilled == 0


def test_analyze_pending_handles_failed_batch_commit_without_blocking_queue_drain():
    """When the graph commit fails, the analyzer must still mark Chroma rows
    analyzed so the same batch doesn't loop forever — the spilled ops will
    replay later via the spillover machinery."""
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "c1", "text": "x", "metadata": {"role": "user"}}],
        fail_batch_commit=True,
    )
    payload = {
        "entities": [{"id": "person:alice", "labels": ["Person"], "name": "Alice", "props": {}}],
        "relationships": [],
    }
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(response=json.dumps(payload)))
    result = analyzer.analyze_pending(batch_size=10)

    # Chroma row was marked analyzed (queue drains)
    assert memory.marked_analyzed == [(["c1"], result.run_id)]
    # but the graph batch was NOT committed — spill counter went up.
    assert memory.batches_committed == 0
    assert memory.batches_spilled == 1
    # The result still reports what was queued (spillover replay will land it).
    assert result.entities_written == 1


def test_analyze_pending_routes_invalid_json_to_dead_letter_queue():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[
            {"id": "c1", "text": "x", "metadata": {"role": "user"}},
            {"id": "c2", "text": "y", "metadata": {"role": "user"}},
        ],
    )
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(response="not json at all"))
    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is True
    assert result.reason == "invalid_json_response"
    # Queue is NOT in the live queue (mark_analyzed was not called)…
    assert memory.marked_analyzed == []
    # …but the rows are routed to the dead-letter queue so they can be
    # inspected and retried instead of looping the analyzer forever.
    assert len(memory.marked_failed) == 1
    failed_ids, reason, run_id = memory.marked_failed[0]
    assert sorted(failed_ids) == ["c1", "c2"]
    assert reason == "invalid_json_response"
    assert run_id == result.run_id


def test_queue_status_includes_local_llm_health_and_dlq_count():
    memory = _FakeMemory(user_root=_user_root(), batch=[{"id": "a"}, {"id": "b"}])
    memory.failed_count_value = 3
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(available=True))
    status = analyzer.queue_status()
    assert status["unanalyzed_count"] == 2
    assert status["failed_count"] == 3
    assert status["local_llm_available"] is True
    assert status["default_model"] == "qwen2.5-3b-instruct"


def test_list_available_models_returns_empty_when_offline():
    memory = _FakeMemory(user_root=_user_root(), batch=[])
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(available=False))
    assert analyzer.list_available_models() == []


def test_analysis_result_serialises():
    result = AnalysisResult(
        run_id="abc",
        processed_messages=3,
        entities_written=2,
        relationships_written=1,
    )
    payload = result.as_dict()
    assert payload["run_id"] == "abc"
    assert payload["processed_messages"] == 3
    assert payload["entities_written"] == 2
    assert payload["relationships_written"] == 1
