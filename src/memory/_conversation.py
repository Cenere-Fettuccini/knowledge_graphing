"""On-disk JSONL conversation log + atomic ``.head`` pointer.

A session is two files under ``CONVERSATION_LOG_DIR``:

    <session_id>.jsonl   append-only, one turn per line
    <session_id>.head    {"active_leaf": "<turn_id>", "updated_at": "..."}

The JSONL is crash-safe by virtue of being append-only — a truncated
trailing line (the only kind a crash can produce) is skipped on read.
The head file is written via tmp+rename so it is always either the
previous valid head or the new valid head, never partial.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from src.log import get_logger

logger = get_logger(__name__)


def conversation_log_dir() -> Path:
    """Return the configured directory. Read from env on every call."""
    return Path(os.environ.get("CONVERSATION_LOG_DIR", "./data/conversations"))


def jsonl_path(session_id: str) -> Path:
    return conversation_log_dir() / f"{session_id}.jsonl"


def head_path(session_id: str) -> Path:
    return conversation_log_dir() / f"{session_id}.head"


def now_iso() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_dir() -> Path:
    """Create the log dir if missing. Returns the path."""
    d = conversation_log_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def iter_turns(session_id: str) -> Iterator[dict]:
    """Yield each well-formed turn from the JSONL. Skip truncated/garbled lines.

    A line that fails ``json.loads`` is logged at WARNING and skipped —
    the most common cause is a torn final line from a process crash
    mid-append. The next read after a clean append continues unaffected.
    """
    p = jsonl_path(session_id)
    if not p.exists():
        return
    try:
        with p.open("r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        "jsonl_line_skipped",
                        extra={"session_id": session_id, "lineno": lineno},
                    )
                    continue
    except OSError:
        logger.error(
            "jsonl_read_failed",
            extra={"session_id": session_id, "path": str(p)},
            exc_info=True,
        )


def read_turns(session_id: str) -> list[dict]:
    return list(iter_turns(session_id))


def read_head(session_id: str) -> str | None:
    """Return the active leaf id, or ``None`` if no head exists."""
    p = head_path(session_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        leaf = data.get("active_leaf")
        return leaf if isinstance(leaf, str) and leaf else None
    except (OSError, json.JSONDecodeError):
        logger.error(
            "head_read_failed",
            extra={"session_id": session_id, "path": str(p)},
            exc_info=True,
        )
        return None


def write_head(session_id: str, leaf_id: str) -> None:
    """Atomically rewrite the head file via tmp + rename."""
    ensure_dir()
    p = head_path(session_id)
    tmp = p.with_suffix(p.suffix + ".tmp")
    payload = json.dumps({"active_leaf": leaf_id, "updated_at": now_iso()})
    tmp.write_text(payload, encoding="utf-8")
    os.replace(tmp, p)


def append_turn(session_id: str, turn: dict) -> None:
    """Append one turn to the session's JSONL. Caller handles head update."""
    ensure_dir()
    p = jsonl_path(session_id)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(turn) + "\n")


def delete_session_files(session_id: str) -> None:
    """Remove both files. No-op for any that do not exist."""
    for p in (jsonl_path(session_id), head_path(session_id)):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            logger.error(
                "session_file_delete_failed",
                extra={"session_id": session_id, "path": str(p)},
                exc_info=True,
            )


def list_session_ids() -> list[str]:
    """Return every session id with a JSONL file in the log dir."""
    d = conversation_log_dir()
    if not d.exists():
        return []
    try:
        return sorted(p.stem for p in d.iterdir() if p.suffix == ".jsonl")
    except OSError:
        logger.error("session_list_failed", extra={"dir": str(d)}, exc_info=True)
        return []
