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
    """Thin wrapper around APScheduler that calls ``analyze_pending`` on a clock."""

    def __init__(
        self,
        memory: MemoryProtocol,
        *,
        tick_seconds: int,
        batch_size: int,
        analyzer_factory: Callable[[MemoryProtocol], KnowledgeAnalyzer] | None = None,
        scheduler_factory: Callable[[], AsyncIOScheduler] | None = None,
    ) -> None:
        self._memory = memory
        self._tick_seconds = max(int(tick_seconds), 30)  # don't allow runaway tight loops
        self._batch_size = batch_size
        self._analyzer_factory = analyzer_factory or (lambda mem: KnowledgeAnalyzer(memory=mem))
        self._scheduler = (scheduler_factory or AsyncIOScheduler)()
        self._job_id = "knowledge-analyzer-tick"
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return
        self._scheduler.add_job(
            self.tick,
            trigger=IntervalTrigger(seconds=self._tick_seconds),
            id=self._job_id,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=None,  # don't fire at startup — first tick after one interval
        )
        self._scheduler.start()
        self._started = True
        logger.info(
            "AnalyzerScheduler started — interval %ss, batch_size %s",
            self._tick_seconds,
            self._batch_size,
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
        self._replay_spillover()
        analyzer = self._analyzer_factory(self._memory)
        result = analyzer.analyze_pending(batch_size=self._batch_size)
        payload = result.as_dict()
        if result.skipped:
            logger.info("Analyzer tick skipped: %s", result.reason or "no reason")
        else:
            logger.info(
                "Analyzer tick processed=%s entities=%s relationships=%s",
                result.processed_messages,
                result.entities_written,
                result.relationships_written,
            )
        return payload

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
