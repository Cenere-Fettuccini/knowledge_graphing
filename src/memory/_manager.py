"""Concrete ``_MemoryManager`` — the singleton behind ``get_memory_manager``.

The class is private. Public consumers see only the ``MemoryManager``
Protocol exported from ``__init__.py``. The single instance is built on
the first call to ``_MemoryManager.get()``.
"""

from __future__ import annotations

import os
from typing import ClassVar, Literal

from src.log import get_logger
from src.memory import _conversation as conv
from src.memory._ids import new_turn_id

logger = get_logger(__name__)

Role = Literal["user", "assistant"]


def _default_recent_limit() -> int:
    try:
        return int(os.environ.get("DEFAULT_RECENT_LIMIT", "20"))
    except ValueError:
        return 20


def _preview(text: str, n: int = 80) -> str:
    text = text.strip().replace("\n", " ")
    return text if len(text) <= n else text[: n - 1] + "…"


class _MemoryManager:
    """Concrete implementation. Construct only via ``_MemoryManager.get()``."""

    _instance: ClassVar["_MemoryManager | None"] = None

    def __init__(self, _key: object) -> None:
        if _key is not _SINGLETON_KEY:
            raise RuntimeError(
                "_MemoryManager is a singleton — use _MemoryManager.get()"
            )

    @classmethod
    def get(cls) -> "_MemoryManager":
        if cls._instance is None:
            cls._instance = cls(_SINGLETON_KEY)
            logger.info("memory_manager_initialised")
        return cls._instance

    # ----- turn-level -------------------------------------------------

    def append(
        self,
        session_id: str,
        role: Role,
        text: str,
        *,
        parent_id: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        if parent_id is None:
            parent_id = conv.read_head(session_id)
        turn_id = new_turn_id()
        turn = {
            "id": turn_id,
            "parent_id": parent_id,
            "role": role,
            "text": text,
            "timestamp": conv.now_iso(),
            "metadata": metadata or {},
        }
        try:
            conv.append_turn(session_id, turn)
            conv.write_head(session_id, turn_id)
        except OSError:
            logger.error(
                "append_failed",
                extra={"session_id": session_id, "role": role},
                exc_info=True,
            )
            raise
        logger.info(
            "turn_appended",
            extra={
                "session_id": session_id,
                "turn_id": turn_id,
                "role": role,
                "parent_id": parent_id,
            },
        )
        return turn_id

    def recent_turns(
        self,
        session_id: str,
        *,
        leaf_id: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        if limit is None:
            limit = _default_recent_limit()
        target_leaf = leaf_id if leaf_id is not None else conv.read_head(session_id)
        if target_leaf is None:
            return []
        by_id = {t["id"]: t for t in conv.iter_turns(session_id)}
        if target_leaf not in by_id:
            return []
        out: list[dict] = []
        cursor: str | None = target_leaf
        seen: set[str] = set()
        while cursor is not None and len(out) < limit:
            if cursor in seen:
                logger.error(
                    "parent_cycle_detected",
                    extra={"session_id": session_id, "turn_id": cursor},
                )
                break
            seen.add(cursor)
            t = by_id.get(cursor)
            if t is None:
                break
            out.append(t)
            cursor = t.get("parent_id")
        return out

    def list_branches(self, session_id: str) -> list[dict]:
        turns = conv.read_turns(session_id)
        if not turns:
            return []
        by_id = {t["id"]: t for t in turns}
        parent_ids = {t["parent_id"] for t in turns if t.get("parent_id")}
        active = conv.read_head(session_id)
        leaves: list[dict] = []
        for t in turns:
            tid = t["id"]
            if tid in parent_ids:
                continue
            count = 0
            cursor: str | None = tid
            seen: set[str] = set()
            while cursor is not None and cursor not in seen:
                seen.add(cursor)
                count += 1
                node = by_id.get(cursor)
                cursor = node.get("parent_id") if node else None
            leaves.append(
                {
                    "leaf_id": tid,
                    "head_role": t.get("role"),
                    "head_text_preview": _preview(t.get("text", "")),
                    "head_timestamp": t.get("timestamp"),
                    "turn_count": count,
                    "label": (t.get("metadata") or {}).get("branch_label"),
                    "is_active": tid == active,
                }
            )
        return leaves

    def set_active(self, session_id: str, leaf_id: str) -> None:
        ids = {t["id"] for t in conv.iter_turns(session_id)}
        if leaf_id not in ids:
            raise ValueError(
                f"leaf {leaf_id!r} does not exist in session {session_id!r}"
            )
        try:
            conv.write_head(session_id, leaf_id)
        except OSError:
            logger.error(
                "set_active_failed",
                extra={"session_id": session_id, "leaf_id": leaf_id},
                exc_info=True,
            )
            raise
        logger.info(
            "active_leaf_set",
            extra={"session_id": session_id, "leaf_id": leaf_id},
        )

    def active_leaf(self, session_id: str) -> str | None:
        return conv.read_head(session_id)

    # ----- session-level ----------------------------------------------

    def list_sessions(self) -> list[dict]:
        out: list[dict] = []
        for sid in conv.list_session_ids():
            turns = conv.read_turns(sid)
            last_active = turns[-1].get("timestamp") if turns else None
            out.append(
                {
                    "session_id": sid,
                    "turn_count": len(turns),
                    "last_active": last_active,
                }
            )
        return out

    def delete_session(self, session_id: str) -> None:
        conv.delete_session_files(session_id)
        logger.info("session_deleted", extra={"session_id": session_id})

    # ----- health -----------------------------------------------------

    def status(self) -> dict:
        d = conv.conversation_log_dir()
        try:
            conv.ensure_dir()
            writable = os.access(d, os.W_OK)
        except OSError:
            logger.error("status_dir_check_failed", extra={"dir": str(d)}, exc_info=True)
            return {"conversation_log": "degraded", "dir": str(d), "writable": False}
        return {
            "conversation_log": "online" if writable else "degraded",
            "dir": str(d),
            "writable": writable,
        }


_SINGLETON_KEY = object()
