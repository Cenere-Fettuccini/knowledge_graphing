import json

import pytest

from src.agent_platform.analyzers.knowledge import (
    AnalysisResult,
    KnowledgeAnalyzer,
    SYSTEM_PROMPT,
)
from src.agent_platform.analyzers.local_llm import LocalLLMUnavailable


class _FakeMemory:
    def __init__(self, *, user_root, batch, schema=None):
        self._user_root = user_root
        self._batch = batch
        self._schema = schema or {"labels": [], "relationship_types": [], "entities": []}
        self.upserted_nodes: list[dict] = []
        self.upserted_relationships: list[dict] = []
        self.marked_analyzed: list[tuple[list, str | None]] = []

    def get_user_root(self):
        return self._user_root

    def list_unanalyzed(self, limit=20):
        return self._batch[:limit]

    def graph_schema_snapshot(self):
        return self._schema

    def count_unanalyzed(self):
        return len(self._batch)

    def upsert_node(self, *, node_id, labels, name, properties=None):
        self.upserted_nodes.append(
            {"id": node_id, "labels": list(labels), "name": name, "props": dict(properties or {})}
        )
        return node_id

    def upsert_relationship(self, *, source_id, target_id, rel_type, properties=None):
        self.upserted_relationships.append(
            {"src": source_id, "tgt": target_id, "type": rel_type, "props": dict(properties or {})}
        )
        return True

    def mark_analyzed(self, ids, run_id=None):
        self.marked_analyzed.append((list(ids), run_id))
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


def test_analyze_pending_bails_on_invalid_json():
    memory = _FakeMemory(
        user_root=_user_root(),
        batch=[{"id": "c1", "text": "x", "metadata": {"role": "user"}}],
    )
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(response="not json at all"))
    result = analyzer.analyze_pending(batch_size=10)
    assert result.skipped is True
    assert result.reason == "invalid_json_response"
    # Queue NOT marked — we want to retry once we have a working JSON-mode model.
    assert memory.marked_analyzed == []


def test_queue_status_includes_local_llm_health():
    memory = _FakeMemory(user_root=_user_root(), batch=[{"id": "a"}, {"id": "b"}])
    analyzer = KnowledgeAnalyzer(memory=memory, llm=_FakeLLM(available=True))
    status = analyzer.queue_status()
    assert status["unanalyzed_count"] == 2
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
