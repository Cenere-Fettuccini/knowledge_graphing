"""Count-triggered cloud belief extraction (CT7).

Companion to ``graph_ingest_trigger``. The local pass flags every
analyzed row with ``belief_candidate: true``; this module watches that
queue and fires ``run_belief_extraction_once`` when enough candidates
have accumulated.

Why a separate trigger:
  - Cloud calls cost real money, so the threshold is independent of
    the local one (and typically lower so we don't sit on a backlog).
  - The two passes hold separate ``asyncio.Lock`` instances so a long
    local extraction doesn't block the cloud pass and vice versa.
  - The cloud pass needs a different failure-handling story: a Gemini
    timeout shouldn't fail-closed on the local pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from src.agent_platform.analyzers import cloud_belief_extraction
from src.core.config import settings

if TYPE_CHECKING:
    from src.memory.manager import MemoryManager

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()


def maybe_trigger(memory: "MemoryManager") -> None:
    """Schedule a cloud belief extraction run if the queue is deep enough.

    Safe to call from any sync code path. Never blocks. No-op when the
    threshold is disabled or no event loop is running.
    """
    threshold = settings.cloud_belief_threshold
    if threshold <= 0:
        return

    try:
        depth = memory.count_belief_candidates()
    except Exception as e:
        logger.debug("count_belief_candidates failed; skipping trigger: %s", e)
        return

    if depth < threshold:
        return

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.debug("cloud_belief trigger fired but no event loop is running")
        return

    loop.create_task(_run_once(memory, depth))


async def _run_once(memory: "MemoryManager", depth_at_trigger: int) -> None:
    if _lock.locked():
        logger.debug(
            "cloud_belief already running; skipping (queue=%d)", depth_at_trigger
        )
        return
    async with _lock:
        threshold = max(settings.cloud_belief_threshold, 1)
        logger.info(
            "cloud_belief trigger: queue=%d (threshold=%d)",
            depth_at_trigger, threshold,
        )
        try:
            result = await cloud_belief_extraction.run_belief_extraction_once(
                memory, batch_size=max(threshold, depth_at_trigger)
            )
        except Exception:
            logger.exception("cloud_belief trigger: run crashed")
            return
        logger.info(
            "cloud_belief trigger: result ok=%s rows=%d intents=%d written=%d",
            result.get("ok"),
            result.get("rows", 0),
            result.get("intents", 0),
            result.get("written", 0),
        )


def is_running() -> bool:
    """Inspector hook for tests / health endpoints."""
    return _lock.locked()
