"""Schema drift monitor (S3.5).

Tracks how the set of labels and relationship types evolves over time.
Catches two classes of problem:
  1. New labels with very few nodes attached (likely typo/drift — e.g.
     ``Stuff`` after the LLM hallucinated a label once).
  2. Labels or relationship types that vanished week-over-week (often
     means the merge canonicalizer collapsed something useful).

The monitor stores JSON snapshots under ``data/schema_snapshots/`` keyed
by an ISO date. ``check_drift`` compares the current state against the
most recent snapshot newer than ``older_than_days`` and surfaces what
changed.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_DEFAULT_SNAPSHOT_DIR = Path("./data/schema_snapshots")
_SMALL_LABEL_THRESHOLD = 3  # new labels with fewer than this many nodes are flagged


def _snapshot_dir() -> Path:
    path = Path(os.environ.get("SCHEMA_SNAPSHOT_DIR", str(_DEFAULT_SNAPSHOT_DIR)))
    path.mkdir(parents=True, exist_ok=True)
    return path


def take_snapshot(memory: "MemoryManager") -> dict:
    """Capture a fresh schema snapshot and write it to disk. Returns the snapshot."""
    snapshot = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "labels": memory.graph_label_counts(),
        "relationship_types": memory.graph_rel_type_counts(),
    }
    out = _snapshot_dir() / f"{snapshot['taken_at'].replace(':', '-')}.json"
    out.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    logger.info("schema_drift: snapshot written to %s", out)
    return snapshot


def _load_previous_snapshot(window_days: int = 7) -> dict | None:
    """Return the newest snapshot at least ``window_days`` old, or None.

    Reads ``taken_at`` from each file's JSON body rather than the
    filename — the on-disk name has ``:`` replaced with ``-`` for
    filesystem safety, which is not safely reversible (ISO timestamps
    contain date-component dashes too).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
    candidates: list[tuple[datetime, Path, dict]] = []
    for p in sorted(_snapshot_dir().glob("*.json")):
        try:
            body = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning("schema_drift: failed to read %s: %s", p, e)
            continue
        taken_at = body.get("taken_at")
        if not isinstance(taken_at, str):
            continue
        try:
            ts = datetime.fromisoformat(taken_at)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts <= cutoff:
            candidates.append((ts, p, body))
    if not candidates:
        return None
    candidates.sort(key=lambda t: t[0], reverse=True)
    _, _, newest_body = candidates[0]
    return newest_body


def check_drift(memory: "MemoryManager", *, window_days: int = 7) -> dict:
    """Compare the current schema to a snapshot ``window_days`` old.

    Returns ``{current, previous, alerts, added_labels, removed_labels,
    added_rel_types, removed_rel_types, small_labels}``. ``alerts`` is a
    human-readable list — anything an operator should glance at.
    """
    current = {
        "taken_at": datetime.now(timezone.utc).isoformat(),
        "labels": memory.graph_label_counts(),
        "relationship_types": memory.graph_rel_type_counts(),
    }
    previous = _load_previous_snapshot(window_days=window_days)

    prev_labels = (previous or {}).get("labels", {}) or {}
    prev_rels = (previous or {}).get("relationship_types", {}) or {}

    added_labels = sorted(set(current["labels"]) - set(prev_labels))
    removed_labels = sorted(set(prev_labels) - set(current["labels"]))
    added_rel_types = sorted(set(current["relationship_types"]) - set(prev_rels))
    removed_rel_types = sorted(set(prev_rels) - set(current["relationship_types"]))

    small_labels = sorted(
        lbl for lbl, c in current["labels"].items()
        if c < _SMALL_LABEL_THRESHOLD and lbl not in prev_labels
    )

    alerts: list[str] = []
    for lbl in small_labels:
        alerts.append(
            f"New label '{lbl}' has only {current['labels'][lbl]} node(s) "
            f"(threshold {_SMALL_LABEL_THRESHOLD}) — likely drift."
        )
    for lbl in removed_labels:
        alerts.append(f"Label '{lbl}' disappeared since last snapshot.")
    for rel in removed_rel_types:
        alerts.append(f"Relationship type '{rel}' disappeared since last snapshot.")

    return {
        "window_days": window_days,
        "current": current,
        "previous": previous,
        "added_labels": added_labels,
        "removed_labels": removed_labels,
        "added_rel_types": added_rel_types,
        "removed_rel_types": removed_rel_types,
        "small_labels": small_labels,
        "alerts": alerts,
    }
