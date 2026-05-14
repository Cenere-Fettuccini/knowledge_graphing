"""Count-triggered graph ingestion (S0.6).

Replaces the time-based analyzer cadence for graph writes: instead of
waking up every N seconds, the system fires ingestion whenever the
unanalyzed Chroma queue crosses ``settings.graph_ingest_threshold``.

This module ships the trigger scaffolding — threshold check, lock, and
the asyncio scheduling hook. The actual extraction (raw conversation
text → list of graph_write Intent dicts via LLM) lands in a follow-up
(S0.6b); for now the run is a logged no-op so we can observe the
trigger firing under real load before committing the extraction prompt.

Concurrency model: a single asyncio.Lock so concurrent ``MemoryManager.store``
calls can't double-fire. If the lock is held, late callers skip rather
than queue — the next store() that sees a non-empty queue will pick it
up.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

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
        logger.info(
            "graph_ingest trigger: queue=%d (threshold=%d) — S0.6b stub, no extraction yet",
            depth_at_trigger,
            settings.graph_ingest_threshold,
        )
        # S0.6b: pull unanalyzed rows, run extraction prompt against an LLM
        # to produce a list of Intent dicts, POST to /graph/ingest with the
        # shared secret, then mark_analyzed on success. Until then the
        # existing analyzer scheduler keeps doing real work; this stub is
        # just observation.


def is_running() -> bool:
    """Inspector hook for tests / health endpoints."""
    return _lock.locked()
