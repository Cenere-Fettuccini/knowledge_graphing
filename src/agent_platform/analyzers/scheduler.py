"""Periodic auto-drain for the knowledge analyzer queue.

Runs a single ``analyze_pending()`` per tick. Each tick is cheap when the
queue is empty (a single Chroma count) or when LM Studio is offline (the
analyzer skips and bails). When work *is* available and the LLM is
reachable, the scheduler drains one batch per tick rather than looping —
that way a long queue gets processed across multiple ticks without any
single tick blocking the event loop for minutes.

Started/stopped by FastAPI's lifespan in ``platform.app_factory``.
"""

from __future__ import annotations

import logging
from typing import Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.agent_platform.analyzers.knowledge import KnowledgeAnalyzer
from src.memory.protocol import MemoryProtocol

logger = logging.getLogger(__name__)


class AnalyzerScheduler:
    """Thin wrapper around APScheduler that calls ``analyze_pending`` on a clock.

    Adapts its pacing based on the queue depth: when the unanalyzed queue
    exceeds ``bulk_threshold`` the scheduler switches to tighter ticks and a
    larger per-batch size so a backfill drains in hours rather than days.
    Reverts to normal pacing as soon as the queue is back below the
    threshold.
    """

    def __init__(
        self,
        memory: MemoryProtocol,
        *,
        tick_seconds: int,
        batch_size: int,
        bulk_tick_seconds: int = 60,
        bulk_batch_size: int = 100,
        bulk_threshold: int = 100,
        analyzer_factory: Callable[[MemoryProtocol], KnowledgeAnalyzer] | None = None,
        scheduler_factory: Callable[[], AsyncIOScheduler] | None = None,
    ) -> None:
        self._memory = memory
        # Don't allow runaway tight loops in either mode.
        self._normal_tick = max(int(tick_seconds), 30)
        self._normal_batch = batch_size
        self._bulk_tick = max(int(bulk_tick_seconds), 30)
        self._bulk_batch = max(int(bulk_batch_size), 1)
        self._bulk_threshold = max(int(bulk_threshold), 1)
        self._bulk_mode = False
        self._analyzer_factory = analyzer_factory or (lambda mem: KnowledgeAnalyzer(memory=mem))
        self._scheduler = (scheduler_factory or AsyncIOScheduler)()
        self._job_id = "knowledge-analyzer-tick"
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    @property
    def in_bulk_mode(self) -> bool:
        return self._bulk_mode

    @property
    def current_tick_seconds(self) -> int:
        return self._bulk_tick if self._bulk_mode else self._normal_tick

    @property
    def current_batch_size(self) -> int:
        return self._bulk_batch if self._bulk_mode else self._normal_batch

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.add_job(
            self.tick,
            trigger=IntervalTrigger(seconds=self._normal_tick),
            id=self._job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=None,  # don't fire at startup — first tick after one interval
        )
        self._scheduler.start()
        self._started = True
        logger.info(
            "AnalyzerScheduler started — interval %ss, batch_size %s "
            "(bulk activates above %s pending @ %ss/%s)",
            self._normal_tick,
            self._normal_batch,
            self._bulk_threshold,
            self._bulk_tick,
            self._bulk_batch,
        )

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover - shutdown is best-effort
            logger.warning("AnalyzerScheduler shutdown raised", exc_info=True)
        self._started = False
        logger.info("AnalyzerScheduler stopped.")

    # ── The work ──────────────────────────────────────────────────────────────

    def tick(self) -> dict:
        """Run one analyzer pass. Logs a one-line summary and returns the dict."""
        self._maybe_switch_pacing()
        self._replay_spillover()
        analyzer = self._analyzer_factory(self._memory)
        result = analyzer.analyze_pending(batch_size=self.current_batch_size)
        payload = result.as_dict()
        if result.skipped:
            logger.info("Analyzer tick skipped: %s", result.reason or "no reason")
        else:
            logger.info(
                "Analyzer tick processed=%s entities=%s relationships=%s (bulk=%s)",
                result.processed_messages,
                result.entities_written,
                result.relationships_written,
                self._bulk_mode,
            )
        return payload

    def _maybe_switch_pacing(self) -> None:
        """Flip in/out of bulk mode based on queue depth."""
        count_unanalyzed = getattr(self._memory, "count_unanalyzed", None)
        if not callable(count_unanalyzed):
            return
        try:
            depth = int(count_unanalyzed() or 0)
        except Exception:
            logger.debug("count_unanalyzed raised during pacing check", exc_info=True)
            return
        if depth >= self._bulk_threshold and not self._bulk_mode:
            self._bulk_mode = True
            logger.info(
                "Analyzer entering bulk mode — queue depth=%d, tick=%ds, batch=%d",
                depth, self._bulk_tick, self._bulk_batch,
            )
            self._reschedule(self._bulk_tick)
        elif depth < self._bulk_threshold and self._bulk_mode:
            self._bulk_mode = False
            logger.info(
                "Analyzer leaving bulk mode — queue depth=%d, back to tick=%ds, batch=%d",
                depth, self._normal_tick, self._normal_batch,
            )
            self._reschedule(self._normal_tick)

    def _reschedule(self, seconds: int) -> None:
        """Re-trigger the job at a new interval. No-op if the scheduler hasn't started."""
        if not self._started:
            return
        reschedule = getattr(self._scheduler, "reschedule_job", None)
        if not callable(reschedule):
            return
        try:
            reschedule(self._job_id, trigger=IntervalTrigger(seconds=seconds))
        except Exception:  # pragma: no cover - never let pacing changes crash a tick
            logger.warning("Failed to reschedule analyzer job", exc_info=True)

    def _replay_spillover(self) -> None:
        """Drain any pending spilled writes so recovered data lands before analysis."""
        replay = getattr(self._memory, "replay_spillover", None)
        if not callable(replay):
            return
        try:
            stats = replay()
        except Exception:
            logger.warning("Spillover replay raised", exc_info=True)
            return
        if any(v for v in stats.values()):
            logger.info("Spillover replay stats: %s", stats)
