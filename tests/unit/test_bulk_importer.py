"""Tests for the bulk importer (S2.1)."""

from __future__ import annotations

import json
from pathlib import Path

from src.ingestion.bulk_importer import BulkImporter, BulkImportResult


class _FakeMemory:
    """Captures everything written via store() so tests can assert metadata."""

    def __init__(self, *, store_fails_for: set[int] | None = None):
        self.calls: list[dict] = []
        self._fail_after = store_fails_for or set()

    def store(self, text, *, role, session_id, is_ephemeral=False, **extra):
        idx = len(self.calls)
        self.calls.append({
            "text": text,
            "role": role,
            "session_id": session_id,
            "is_ephemeral": is_ephemeral,
            "extra": dict(extra),
        })
        if idx in self._fail_after:
            return None
        return f"id-{idx}"


# ── JSONL import ─────────────────────────────────────────────────────────────


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row) + "\n")


def test_import_jsonl_writes_each_row_with_bulk_metadata(tmp_path):
    memory = _FakeMemory()
    src = tmp_path / "journal.jsonl"
    _write_jsonl(src, [
        {"text": "moved to Berlin", "timestamp": "2021-06-01T00:00:00Z"},
        {"text": "started new job", "source": "career-log"},
    ])
    importer = BulkImporter(memory=memory)

    result = importer.import_jsonl(str(src))

    assert isinstance(result, BulkImportResult)
    assert result.imported == 2
    assert result.skipped == 0
    assert result.errors == []
    assert len(memory.calls) == 2
    first = memory.calls[0]
    assert first["text"] == "moved to Berlin"
    assert first["role"] == "document"
    assert first["session_id"].startswith("bulk_journal")
    assert first["is_ephemeral"] is False
    assert first["extra"]["bulk_imported"] is True
    assert "imported_at" in first["extra"]
    assert first["extra"]["timestamp"] == "2021-06-01T00:00:00Z"
    # second row's source overrides the default
    assert memory.calls[1]["extra"]["source"] == "career-log"


def test_import_jsonl_skips_empty_and_malformed_rows(tmp_path):
    memory = _FakeMemory()
    src = tmp_path / "messy.jsonl"
    src.write_text(
        "\n".join([
            '{"text": "valid row"}',
            '',                                # blank line
            'not even json',                   # malformed
            '{"role": "user"}',                # missing text
            '"just a string, not an object"',  # wrong shape
        ]),
        encoding="utf-8",
    )
    importer = BulkImporter(memory=memory)

    result = importer.import_jsonl(str(src))

    assert result.imported == 1
    assert result.skipped == 4
    # Two structural errors get reported; blank + missing-text are silent skips.
    assert len(result.errors) == 2
    assert any("invalid JSON" in err for err in result.errors)
    assert any("not an object" in err for err in result.errors)


def test_import_jsonl_returns_error_when_file_missing(tmp_path):
    memory = _FakeMemory()
    importer = BulkImporter(memory=memory)
    result = importer.import_jsonl(str(tmp_path / "nope.jsonl"))
    assert result.imported == 0
    assert any("file not found" in err for err in result.errors)
    assert memory.calls == []


def test_import_jsonl_default_source_applies_when_row_omits_it(tmp_path):
    memory = _FakeMemory()
    src = tmp_path / "rows.jsonl"
    _write_jsonl(src, [{"text": "alpha"}, {"text": "beta", "source": "explicit-source"}])
    importer = BulkImporter(memory=memory)

    importer.import_jsonl(str(src), source="journal-2024")

    assert memory.calls[0]["extra"]["source"] == "journal-2024"
    assert memory.calls[1]["extra"]["source"] == "explicit-source"


def test_import_jsonl_counts_failed_chroma_writes_as_skipped(tmp_path):
    memory = _FakeMemory(store_fails_for={1})  # 2nd row's store() returns None
    src = tmp_path / "rows.jsonl"
    _write_jsonl(src, [
        {"text": "one"},
        {"text": "two"},
        {"text": "three"},
    ])

    result = BulkImporter(memory=memory).import_jsonl(str(src))

    assert result.imported == 2
    assert result.skipped == 1


def test_import_jsonl_preserves_explicit_session_id(tmp_path):
    memory = _FakeMemory()
    src = tmp_path / "rows.jsonl"
    _write_jsonl(src, [
        {"text": "alpha", "session_id": "custom-session"},
        {"text": "beta"},  # falls back to derived session id
    ])

    BulkImporter(memory=memory).import_jsonl(str(src))

    assert memory.calls[0]["session_id"] == "custom-session"
    assert memory.calls[1]["session_id"].startswith("bulk_rows")


# ── Directory import ────────────────────────────────────────────────────────


def test_import_directory_chunks_each_file_and_records_origin(tmp_path):
    (tmp_path / "a.txt").write_text("paragraph one\n\nparagraph two", encoding="utf-8")
    (tmp_path / "b.md").write_text("only one paragraph here", encoding="utf-8")
    (tmp_path / "ignore.bin").write_text("binary blob — should be skipped", encoding="utf-8")
    memory = _FakeMemory()

    result = BulkImporter(memory=memory).import_directory(
        str(tmp_path), chunk_size=2000, chunk_overlap=0,
    )

    assert result.imported == len(memory.calls)
    assert result.imported >= 2  # at least one chunk per supported file
    sources = {call["extra"].get("source") for call in memory.calls}
    # Each call carries the originating file path as `source`.
    assert any(src and src.endswith("a.txt") for src in sources)
    assert any(src and src.endswith("b.md") for src in sources)
    assert all("ignore.bin" not in (src or "") for src in sources)


def test_import_directory_groups_chunks_under_one_session_per_file(tmp_path):
    file_path = tmp_path / "long.md"
    file_path.write_text(
        "block 1\n\n" + "x" * 3000 + "\n\nblock 2", encoding="utf-8",
    )
    memory = _FakeMemory()

    BulkImporter(memory=memory).import_directory(
        str(tmp_path), chunk_size=500, chunk_overlap=0,
    )

    sessions = {call["session_id"] for call in memory.calls}
    assert len(sessions) == 1
    only_session = sessions.pop()
    assert only_session.startswith("bulk_long")
    # Chunk indices are stamped for round-trip debugging.
    indices = [call["extra"]["chunk_index"] for call in memory.calls]
    assert indices == sorted(indices)
    assert all(call["extra"]["chunk_count"] == len(memory.calls) for call in memory.calls)


def test_import_directory_returns_error_when_path_missing():
    importer = BulkImporter(memory=_FakeMemory())
    result = importer.import_directory("/path/that/does/not/exist")
    assert result.imported == 0
    assert any("directory not found" in err for err in result.errors)


def test_import_directory_skips_unreadable_files(tmp_path):
    """If read_text raises (permission, binary garbage), the file is reported but doesn't crash the run."""
    good = tmp_path / "good.txt"
    good.write_text("good content", encoding="utf-8")
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe\x00\x00invalid utf8 sequence")

    memory = _FakeMemory()
    result = BulkImporter(memory=memory).import_directory(str(tmp_path))

    # `good.txt` imported, `bad.txt` skipped with an error message.
    sources = {call["extra"].get("source") for call in memory.calls}
    assert any(src and src.endswith("good.txt") for src in sources)
    assert result.skipped >= 1
    assert any("read failed" in err for err in result.errors)


def test_result_as_dict_shape_is_stable_for_the_api_response():
    result = BulkImportResult(imported=5, skipped=2, errors=["x"], source_path="/tmp/journal.jsonl")
    payload = result.as_dict()
    assert payload == {
        "imported": 5,
        "skipped": 2,
        "errors": ["x"],
        "source_path": "/tmp/journal.jsonl",
    }
