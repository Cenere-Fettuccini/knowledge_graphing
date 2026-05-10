"""On-disk spillover for memory writes that failed because a backend was offline.

When Chroma or Neo4j is unreachable we don't want to silently drop the
write — we append the operation to a JSONL file so it can be replayed once
the backend recovers. The replay is invoked from the analyzer scheduler
tick, so a healthy system drains the spillover within one tick of the
backend coming back.

File layout::

    <spillover_dir>/
        chroma.jsonl   # pending Chroma writes (memory.store calls)
        neo4j.jsonl    # pending Neo4j writes (upsert_node / upsert_relationship)

Each line is a JSON object::

    {"op": "<op_name>", "payload": {...}, "attempted_at": "<iso8601>"}

Replay strategy: rename the active file to ``<name>.replay`` (atomic on the
same filesystem), iterate through it, attempt each op, and re-append any
that still fail to the live file. Concurrent writes during replay land in
the live file and are picked up on the next tick.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


CHROMA_FILE = "chroma.jsonl"
NEO4J_FILE = "neo4j.jsonl"


class SpilloverWriter:
    """Append-only JSONL log of failed memory writes, with a replay helper."""

    def __init__(self, spillover_dir: str):
        self._dir = spillover_dir
        self._chroma_path = os.path.join(spillover_dir, CHROMA_FILE)
        self._neo4j_path = os.path.join(spillover_dir, NEO4J_FILE)
        self._lock = threading.Lock()
        os.makedirs(spillover_dir, exist_ok=True)

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_chroma_store(self, *, text: str, metadata: dict) -> None:
        """Persist a failed ``MemoryManager.store`` call for later replay."""
        self._append(self._chroma_path, "chroma.store", {
            "text": text,
            "metadata": metadata,
        })

    def record_neo4j_node(
        self,
        *,
        node_id: str,
        labels: list[str],
        name: str,
        properties: dict | None,
    ) -> None:
        """Persist a failed ``upsert_node`` call for later replay."""
        self._append(self._neo4j_path, "neo4j.upsert_node", {
            "node_id": node_id,
            "labels": list(labels),
            "name": name,
            "properties": properties or {},
        })

    def record_neo4j_relationship(
        self,
        *,
        source_id: str,
        target_id: str,
        rel_type: str,
        properties: dict | None,
    ) -> None:
        """Persist a failed ``upsert_relationship`` call for later replay."""
        self._append(self._neo4j_path, "neo4j.upsert_relationship", {
            "source_id": source_id,
            "target_id": target_id,
            "rel_type": rel_type,
            "properties": properties or {},
        })

    # ── Replay ────────────────────────────────────────────────────────────────

    def replay(
        self,
        *,
        chroma_apply: Callable[[dict], bool] | None = None,
        neo4j_apply: Callable[[dict], bool] | None = None,
    ) -> dict[str, int]:
        """Drain spillover files, attempting each op via the supplied callbacks.

        Each callback takes the original record dict (with ``op`` and
        ``payload`` keys) and returns True on success. Any record whose
        callback returns False or raises is re-appended to the live file so
        the next tick will retry it.
        """
        stats = {
            "chroma_replayed": 0,
            "chroma_remaining": 0,
            "neo4j_replayed": 0,
            "neo4j_remaining": 0,
        }
        if chroma_apply is not None:
            replayed, remaining = self._drain(self._chroma_path, chroma_apply)
            stats["chroma_replayed"] = replayed
            stats["chroma_remaining"] = remaining
        if neo4j_apply is not None:
            replayed, remaining = self._drain(self._neo4j_path, neo4j_apply)
            stats["neo4j_replayed"] = replayed
            stats["neo4j_remaining"] = remaining
        return stats

    def pending_counts(self) -> dict[str, int]:
        """Cheap line-count of each spillover file. Used for health/UI."""
        return {
            "chroma": _count_lines(self._chroma_path),
            "neo4j": _count_lines(self._neo4j_path),
        }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _append(self, path: str, op: str, payload: dict[str, Any]) -> None:
        record = {
            "op": op,
            "payload": payload,
            "attempted_at": datetime.now(timezone.utc).isoformat(),
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            try:
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError as exc:
                logger.error("Failed to append spillover record to %s: %s", path, exc)

    def _drain(
        self,
        path: str,
        apply: Callable[[dict], bool],
    ) -> tuple[int, int]:
        """Atomically claim *path*, replay each record, return (replayed, remaining)."""
        claim_path = path + ".replay"
        with self._lock:
            if not os.path.exists(path):
                return (0, 0)
            try:
                os.replace(path, claim_path)
            except OSError as exc:
                logger.error("Could not claim spillover file %s: %s", path, exc)
                return (0, 0)

        replayed = 0
        remaining_records: list[str] = []
        for raw_line in _read_lines(claim_path):
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                record = json.loads(stripped)
            except json.JSONDecodeError:
                logger.warning("Discarding malformed spillover line in %s", claim_path)
                continue
            try:
                ok = bool(apply(record))
            except Exception as exc:
                logger.warning(
                    "Spillover replay raised for op=%s: %s",
                    record.get("op"),
                    exc,
                )
                ok = False
            if ok:
                replayed += 1
            else:
                remaining_records.append(stripped)

        if remaining_records:
            with self._lock:
                try:
                    with open(path, "a", encoding="utf-8") as fh:
                        for line in remaining_records:
                            fh.write(line + "\n")
                except OSError as exc:
                    logger.error(
                        "Failed to re-append unreplayed spillover lines to %s: %s",
                        path,
                        exc,
                    )
        try:
            os.remove(claim_path)
        except OSError:  # pragma: no cover - cleanup is best-effort
            logger.debug("Could not remove claim file %s", claim_path, exc_info=True)
        return (replayed, len(remaining_records))


def _read_lines(path: str) -> Iterable[str]:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                yield line
    except OSError as exc:
        logger.error("Could not read spillover file %s: %s", path, exc)
        return


def _count_lines(path: str) -> int:
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return sum(1 for line in fh if line.strip())
    except OSError:
        return 0
