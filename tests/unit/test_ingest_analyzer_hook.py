"""Bulk-ingest must drain the analyzer queue once chunks land in Chroma."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent_platform.analyzers.knowledge import AnalysisResult
from src.tools import ingest as ingest_module


class _FakeMemory:
    def __init__(self):
        self.stored: list[dict] = []

    def store(self, *, text, role, session_id, **extra):
        self.stored.append({"text": text, "role": role, "session_id": session_id, **extra})
        return f"chroma-{len(self.stored)}"


class _FakeAnalyzer:
    """Returns each scripted result in order, then a queue-empty result forever."""
    def __init__(self, scripted):
        self._scripted = list(scripted)
        self.calls: list[int] = []

    def analyze_pending(self, *, batch_size, model=None):
        self.calls.append(batch_size)
        if self._scripted:
            return self._scripted.pop(0)
        return AnalysisResult(
            run_id="empty", processed_messages=0, entities_written=0, relationships_written=0,
            skipped=True, reason="queue_empty",
        )


@pytest.fixture
def two_text_files(tmp_path: Path) -> Path:
    (tmp_path / "a.md").write_text("# Hello\nKevin works at Acme.\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("Alice is Kevin's friend.\nShe likes jazz.\n", encoding="utf-8")
    return tmp_path


def _make_ingestor(monkeypatch, memory, analyzer):
    ingestor = ingest_module.KnowledgeIngestor.__new__(ingest_module.KnowledgeIngestor)
    ingestor.memory = memory
    monkeypatch.setattr(ingest_module, "KnowledgeAnalyzer", lambda memory: analyzer)
    return ingestor


def test_ingest_directory_drains_analyzer_when_analyze_true(monkeypatch, two_text_files):
    memory = _FakeMemory()
    analyzer = _FakeAnalyzer([
        AnalysisResult(
            run_id="r1", processed_messages=2, entities_written=3, relationships_written=2,
        ),
        AnalysisResult(
            run_id="r2", processed_messages=0, entities_written=0, relationships_written=0,
            skipped=True, reason="queue_empty",
        ),
    ])
    ingestor = _make_ingestor(monkeypatch, memory, analyzer)

    summary = ingestor.ingest_directory(str(two_text_files), analyze=True)

    assert summary["files"] == 2
    assert summary["chunks"] >= 2
    # First batch ran, second one bailed with queue_empty — exactly two analyzer calls.
    assert len(analyzer.calls) == 2
    assert summary["analyzer"]["batches"] == 2
    assert summary["analyzer"]["total_processed"] == 2
    assert summary["analyzer"]["total_entities"] == 3
    assert summary["analyzer"]["stopped_reason"] == "queue_empty"


def test_ingest_directory_skips_analyzer_when_analyze_false(monkeypatch, two_text_files):
    memory = _FakeMemory()
    analyzer = _FakeAnalyzer([])
    ingestor = _make_ingestor(monkeypatch, memory, analyzer)

    summary = ingestor.ingest_directory(str(two_text_files), analyze=False)

    assert summary["chunks"] >= 2
    assert summary["analyzer"] is None
    assert analyzer.calls == []


def test_ingest_directory_stops_draining_when_llm_unavailable(monkeypatch, two_text_files):
    """If the LLM is offline, analyzer says skipped and we bail — leaving the
    queue for the next scheduler tick instead of busy-looping."""
    memory = _FakeMemory()
    analyzer = _FakeAnalyzer([
        AnalysisResult(
            run_id="r1", processed_messages=0, entities_written=0, relationships_written=0,
            skipped=True, reason="llm_unavailable: connection refused",
        ),
    ])
    ingestor = _make_ingestor(monkeypatch, memory, analyzer)

    summary = ingestor.ingest_directory(str(two_text_files), analyze=True)

    assert len(analyzer.calls) == 1   # bailed after the first attempt
    assert summary["analyzer"]["batches"] == 1
    assert summary["analyzer"]["total_processed"] == 0
    assert summary["analyzer"]["stopped_reason"].startswith("llm_unavailable")


def test_ingest_directory_skips_analyzer_when_zero_chunks(monkeypatch, tmp_path):
    """An empty directory means no chunks to analyze — don't even instantiate the analyzer."""
    memory = _FakeMemory()
    analyzer = _FakeAnalyzer([])
    ingestor = _make_ingestor(monkeypatch, memory, analyzer)

    summary = ingestor.ingest_directory(str(tmp_path), analyze=True)

    assert summary["chunks"] == 0
    assert summary["analyzer"] is None
    assert analyzer.calls == []


def test_ingest_directory_returns_zeros_when_path_missing(monkeypatch):
    memory = _FakeMemory()
    analyzer = _FakeAnalyzer([])
    ingestor = _make_ingestor(monkeypatch, memory, analyzer)

    summary = ingestor.ingest_directory("/no/such/path", analyze=True)

    assert summary == {"files": 0, "chunks": 0, "analyzer": None}
    assert analyzer.calls == []
