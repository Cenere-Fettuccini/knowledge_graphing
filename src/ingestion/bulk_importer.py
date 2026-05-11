"""Bulk ingestion of historical documents into the memory pipeline.

The importer writes raw text into Chroma with ``analyzed: false`` so the
existing knowledge analyzer picks the rows up on a later tick. No graph
writes happen here — the analyzer owns extraction.

Two entry points cover the common shapes a user is likely to have on hand:

* :meth:`BulkImporter.import_jsonl` — newline-delimited JSON rows where
  each line is one memory. Required key is ``text``; optional keys are
  ``timestamp``, ``source``, ``role``, ``session_id``, and any extra
  scalars (recorded as metadata).
* :meth:`BulkImporter.import_directory` — recursively walks a directory
  of plain-text files (``*.txt``, ``*.md`` by default), chunking each
  file via :func:`src.ingestion.chunker.chunk_text` and storing one row
  per chunk.

Each row's metadata carries ``source: "bulk"``, ``bulk_imported: True``,
and an ``imported_at`` timestamp. The ``bulk_imported`` flag is what
:meth:`MemoryManager.list_unanalyzed` uses to keep bulk rows behind
live conversation turns in the analyzer queue — the live pool is always
drained first, then bulk rows surface oldest-first by their source
``timestamp``.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from src.ingestion.chunker import chunk_text
from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)


DEFAULT_DIRECTORY_GLOB = ("*.txt", "*.md")
DEFAULT_BATCH_ROLE = "document"


@dataclass
class BulkImportResult:
    """Stats from a single import run — surfaced to the explorer panel."""

    imported: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    source_path: str = ""

    def as_dict(self) -> dict:
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "errors": self.errors,
            "source_path": self.source_path,
        }


class BulkImporter:
    """Writes historical text into Chroma so the analyzer can backfill the graph."""

    def __init__(self, memory: MemoryManager) -> None:
        self._memory = memory

    # ── JSONL ────────────────────────────────────────────────────────────────

    def import_jsonl(
        self,
        path: str,
        *,
        source: str | None = None,
    ) -> BulkImportResult:
        """Import a JSONL file. Each line must be a JSON object with a ``text`` key.

        Optional per-row keys: ``timestamp`` (ISO 8601), ``source``, ``role``,
        ``session_id``. Everything else is stored verbatim as metadata.

        ``source`` overrides the per-row source for rows that don't carry one
        — useful when importing a whole file you want to tag uniformly (e.g.
        ``source="journal-2024"``).
        """
        result = BulkImportResult(source_path=path)
        if not os.path.isfile(path):
            result.errors.append(f"file not found: {path}")
            return result

        default_session = _session_id_from_path(path, prefix="bulk")
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line_num, raw in enumerate(fh, start=1):
                    stripped = raw.strip()
                    if not stripped:
                        result.skipped += 1
                        continue
                    try:
                        row = json.loads(stripped)
                    except json.JSONDecodeError as exc:
                        result.skipped += 1
                        result.errors.append(
                            f"line {line_num}: invalid JSON ({exc.msg})"
                        )
                        continue
                    if not isinstance(row, dict):
                        result.skipped += 1
                        result.errors.append(f"line {line_num}: row is not an object")
                        continue
                    if self._store_row(
                        row,
                        default_session=default_session,
                        default_source=source,
                    ):
                        result.imported += 1
                    else:
                        result.skipped += 1
        except OSError as exc:
            result.errors.append(f"failed to read {path}: {exc}")
        return result

    # ── Directory walk ───────────────────────────────────────────────────────

    def import_directory(
        self,
        path: str,
        *,
        patterns: Iterable[str] = DEFAULT_DIRECTORY_GLOB,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
    ) -> BulkImportResult:
        """Recursively import text files from a directory, chunked into rows.

        Each chunk becomes one Chroma row. The originating file path is
        recorded as ``source`` metadata so the user can later trace a
        graph fact back to its origin file.
        """
        result = BulkImportResult(source_path=path)
        if not os.path.isdir(path):
            result.errors.append(f"directory not found: {path}")
            return result

        for file_path in _walk_files(Path(path), patterns):
            session_id = _session_id_from_path(str(file_path), prefix="bulk")
            try:
                text = file_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                result.skipped += 1
                result.errors.append(f"{file_path}: read failed ({exc})")
                continue
            chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
            if not chunks:
                result.skipped += 1
                continue
            for index, chunk in enumerate(chunks):
                row = {
                    "text": chunk,
                    "source": str(file_path),
                    "session_id": session_id,
                    "chunk_index": index,
                    "chunk_count": len(chunks),
                }
                if self._store_row(row, default_session=session_id):
                    result.imported += 1
                else:
                    result.skipped += 1
        return result

    # ── Internals ────────────────────────────────────────────────────────────

    def _store_row(
        self,
        row: dict,
        *,
        default_session: str,
        default_source: str | None = None,
    ) -> bool:
        """Persist one row to Chroma. Returns True if the write succeeded."""
        text = (row.get("text") or "").strip() if isinstance(row.get("text"), str) else ""
        if not text:
            return False
        session_id = row.get("session_id") or default_session
        role = row.get("role") or DEFAULT_BATCH_ROLE
        source = row.get("source") or default_source or "bulk"
        extra = {
            k: v
            for k, v in row.items()
            if k not in {"text", "session_id", "role"}
        }
        extra.setdefault("source", source)
        extra["bulk_imported"] = True
        extra.setdefault("imported_at", datetime.now(timezone.utc).isoformat())
        memory_id = self._memory.store(
            text,
            role=role,
            session_id=session_id,
            is_ephemeral=False,
            **extra,
        )
        # store() returns None when Chroma was offline AND the spillover writer
        # was not able to record the op. With S1.1 in place a None return is
        # rare; treat it as a soft skip rather than crashing the whole import.
        return memory_id is not None


def _session_id_from_path(path: str, *, prefix: str = "bulk") -> str:
    """Stable session id derived from a file path — keeps imports groupable."""
    base = os.path.basename(path) or "import"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", base).strip("-").lower() or "import"
    return f"{prefix}_{slug}"


def _walk_files(root: Path, patterns: Iterable[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for pattern in patterns:
        for match in root.rglob(pattern):
            if not match.is_file():
                continue
            resolved = match.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            yield match
