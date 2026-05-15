"""Count-triggered graph ingestion (S0.6).

Replaces the time-based analyzer cadence for graph writes: instead of
waking up every N seconds, the system fires ingestion whenever the
unanalyzed Chroma queue crosses ``settings.graph_ingest_threshold``.

Flow per run:
  1. Pull up to ``threshold`` unanalyzed Chroma rows.
  2. Convert them to ``graph_write`` Intent dicts via the local LLM
     (``graph_extraction.extract_intents``).
  3. Call ``graph_write`` in-process. The isolation guard and
     reachability sweep run as part of that call.
  4. Mark the consumed Chroma rows analyzed iff the write succeeded.

Concurrency model: a single asyncio.Lock so concurrent ``MemoryManager.store``
calls can't double-fire. If the lock is held, late callers skip rather
than queue — the next store() that sees a non-empty queue will pick it
up.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING

from src.agent_platform.analyzers import cloud_belief_trigger, graph_extraction
from src.agent_platform.tools.graph_write import graph_write
from src.core.config import settings

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def maybe_trigger(memory: "MemoryManager") -> None:
    """Schedule an ingestion run if the queue has crossed the threshold.

    Safe to call from any sync code path; the actual run is dispatched
    onto the running event loop. Returns immediately — never blocks.
    No-op if no event loop is running (e.g. during tests that don't use
    asyncio) or if the threshold is disabled.
    """
    threshold = settings.graph_ingest_threshold
    if threshold <= 0:
        return

    try:
        depth = memory.count_unanalyzed()
    except Exception as e:
        logger.debug("count_unanalyzed failed; skipping trigger: %s", e)
        return

    if depth < threshold:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("graph_ingest trigger fired but no event loop is running")
        return

    loop.create_task(_run_once(memory, depth))


async def _run_once(memory: "MemoryManager", depth_at_trigger: int) -> None:
    if _lock.locked():
        logger.debug(
            "graph_ingest already running; skipping (queue=%d)", depth_at_trigger
        )
        return
    async with _lock:
        await run_extraction_pass(
            memory, batch_size=max(settings.graph_ingest_threshold, 1)
        )


async def run_extraction_pass(
    memory: "MemoryManager", *, batch_size: int | None = None
) -> dict:
    """One full pass: list_unanalyzed → extract → graph_write → mark.

    Public entry point used by:
      - ``_run_once`` (under the auto-trigger lock)
      - The manual ``POST /api/explorer/analyze/run`` route
      - The bulk-importer post-write drain

    Returns a stats dict compatible with the legacy KnowledgeAnalyzer
    result shape so the explorer panel doesn't need to change:
    ``{processed_messages, entities_written, relationships_written,
    quarantined, skipped, reason, run_id}``.
    """
    run_id = f"graph_ingest_{uuid.uuid4().hex[:12]}"
    if batch_size is None:
        batch_size = max(settings.graph_ingest_threshold, 1)
    logger.info("graph_ingest %s: starting (batch=%d)", run_id, batch_size)

    base = {
        "run_id": run_id,
        "processed_messages": 0,
        "entities_written": 0,
        "relationships_written": 0,
        "quarantined": 0,
        "skipped": False,
        "reason": None,
    }

    try:
        rows = memory.list_unanalyzed(limit=batch_size)
    except Exception as e:
        logger.exception("graph_ingest %s: list_unanalyzed failed", run_id)
        return {**base, "skipped": True, "reason": f"list_unanalyzed failed: {e}"}

    if not rows:
        return {**base, "skipped": True, "reason": "queue empty"}

    row_ids = [r["id"] for r in rows if r.get("id")]
    schema = _safe_schema(memory)

    try:
        intents = await graph_extraction.extract_intents(rows, schema)
    except Exception as e:
        logger.exception("graph_ingest %s: extraction crashed", run_id)
        return {**base, "skipped": True, "reason": f"extraction crashed: {e}"}

    if not intents:
        logger.info(
            "graph_ingest %s: 0 intents produced, marking %d rows analyzed",
            run_id, len(row_ids),
        )
        _mark_analyzed(memory, row_ids, run_id)
        return {**base, "processed_messages": len(row_ids), "reason": "no intents"}

    result = graph_write(intents)
    if not result.get("ok"):
        logger.warning(
            "graph_ingest %s: graph_write rejected (error=%s); leaving rows for retry",
            run_id, result.get("error"),
        )
        return {**base, "skipped": True, "reason": result.get("error") or "graph_write rejected"}

    nodes = result.get("nodes_written", [])
    edges = result.get("edges_written", [])
    quarantined = int(result.get("quarantined") or 0)
    logger.info(
        "graph_ingest %s: wrote %d nodes / %d edges; marking %d rows analyzed",
        run_id, len(nodes), len(edges), len(row_ids),
    )
    _mark_analyzed(memory, row_ids, run_id)

    # S3.4: hand the same rows off to the cloud belief extractor. We flag
    # every analyzed row; the cloud pass clears the flag whether it
    # produces beliefs or not.
    flagged = False
    try:
        memory.mark_belief_candidates(row_ids)
        flagged = True
    except Exception:
        logger.exception("graph_ingest %s: mark_belief_candidates failed", run_id)
    # CT7: fire the cloud trigger after flagging. Separate lock + own
    # threshold so we don't block on a long Gemini call.
    if flagged:
        try:
            cloud_belief_trigger.maybe_trigger(memory)
        except Exception:
            logger.exception("graph_ingest %s: cloud_belief_trigger raised", run_id)

    return {
        **base,
        "processed_messages": len(row_ids),
        "entities_written": len(nodes),
        "relationships_written": len(edges),
        "quarantined": quarantined,
    }


def _safe_schema(memory: "MemoryManager") -> dict:
    try:
        return memory.graph_schema_snapshot()
    except Exception:
        logger.debug("graph_schema_snapshot failed; running extraction without schema")
        return {"labels": [], "relationship_types": [], "entities": []}


def _mark_analyzed(memory: "MemoryManager", ids: list[str], run_id: str) -> None:
    if not ids:
        return
    try:
        memory.mark_analyzed(ids, run_id=run_id)
    except Exception:
        logger.exception("graph_ingest %s: mark_analyzed failed for %d ids", run_id, len(ids))


def is_running() -> bool:
    """Inspector hook for tests / health endpoints."""
    return _lock.locked()
