"""Scheduler orchestration — APScheduler-driven Deep Pass + Rabbit Hole ticks."""

from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.memory.protocol import MemoryProtocol
from src.rumination.deep_pass import DeepSynthesisEngine

logger = logging.getLogger(__name__)


class RuminationScheduler:
    """Runs DeepSynthesisEngine on two independent clocks.

    - deep_pass_tick: retroactive belief analysis (evolutions, contradictions).
    - rabbit_hole_tick: creative tangent synthesis (late-night epiphanies).

    Started/stopped by FastAPI's lifespan in ``platform.app_factory``.
    Enable via ``RUMINATION_ENABLED=true`` in .env.
    """

    _DEEP_PASS_JOB = "rumination-deep-pass"
    _RABBIT_HOLE_JOB = "rumination-rabbit-hole"

    def __init__(
        self,
        memory: MemoryProtocol,
        *,
        deep_pass_tick_seconds: int,
        rabbit_hole_tick_seconds: int,
    ) -> None:
        self._memory = memory
        self._deep_pass_tick = max(int(deep_pass_tick_seconds), 60)
        self._rabbit_hole_tick = max(int(rabbit_hole_tick_seconds), 60)
        self._scheduler = AsyncIOScheduler()
        self._started = False

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return

        engine = DeepSynthesisEngine(memory=self._memory)

        self._scheduler.add_job(
            engine.run_batch,
            trigger=IntervalTrigger(seconds=self._deep_pass_tick),
            id=self._DEEP_PASS_JOB,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=None,
        )
        self._scheduler.add_job(
            engine.run_rabbit_hole,
            trigger=IntervalTrigger(seconds=self._rabbit_hole_tick),
            id=self._RABBIT_HOLE_JOB,
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            next_run_time=None,
        )

        self._scheduler.start()
        self._started = True
        logger.info(
            "RuminationScheduler started — deep_pass=%ss, rabbit_hole=%ss",
            self._deep_pass_tick,
            self._rabbit_hole_tick,
        )

    def stop(self) -> None:
        if not self._started:
            return
        try:
            self._scheduler.shutdown(wait=False)
        except Exception:
            logger.warning("RuminationScheduler shutdown raised", exc_info=True)
        self._started = False
        logger.info("RuminationScheduler stopped.")
