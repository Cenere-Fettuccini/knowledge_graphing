from __future__ import annotations

from src.agent_platform.analyzers.knowledge import AnalysisResult
from src.agent_platform.analyzers.scheduler import AnalyzerScheduler


class _FakeAnalyzer:
    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def analyze_pending(self, *, batch_size, model=None):
        self.calls.append({"batch_size": batch_size, "model": model})
        return self._results.pop(0)


class _FakeAPScheduler:
    """Stand-in that records jobs but doesn't actually tick on a clock."""
    def __init__(self):
        self.jobs = []
        self.started = False
        self.shutdown_called = False
        self.reschedules: list[dict] = []

    def add_job(self, func, **kwargs):
        self.jobs.append({"func": func, **kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.shutdown_called = True

    def reschedule_job(self, job_id, *, trigger):
        # IntervalTrigger exposes the configured interval via __slots__
        seconds = getattr(trigger, "interval", None)
        seconds_val = seconds.total_seconds() if seconds else None
        self.reschedules.append({"job_id": job_id, "seconds": seconds_val})


class _DepthMemory:
    """Minimal memory stand-in for pacing decisions."""

    def __init__(self, depth: int):
        self._depth = depth

    def count_unanalyzed(self) -> int:
        return self._depth

    def set_depth(self, value: int) -> None:
        self._depth = value


def _result(processed=0, **kwargs):
    return AnalysisResult(
        run_id="r",
        processed_messages=processed,
        entities_written=kwargs.get("entities_written", 0),
        relationships_written=kwargs.get("relationships_written", 0),
        skipped=kwargs.get("skipped", False),
        reason=kwargs.get("reason", ""),
    )


def test_start_registers_a_single_periodic_job():
    fake_scheduler = _FakeAPScheduler()
    analyzer = _FakeAnalyzer([_result(processed=3, entities_written=2)])
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=120,
        batch_size=15,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake_scheduler,
    )
    scheduler.start()

    assert fake_scheduler.started is True
    assert len(fake_scheduler.jobs) == 1
    assert fake_scheduler.jobs[0]["id"] == "knowledge-analyzer-tick"
    assert fake_scheduler.jobs[0]["max_instances"] == 1
    assert fake_scheduler.jobs[0]["coalesce"] is True


def test_start_is_idempotent():
    fake_scheduler = _FakeAPScheduler()
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=300,
        batch_size=20,
        analyzer_factory=lambda mem: _FakeAnalyzer([]),
        scheduler_factory=lambda: fake_scheduler,
    )
    scheduler.start()
    scheduler.start()
    assert len(fake_scheduler.jobs) == 1   # second start() is a no-op


def test_stop_shuts_down_underlying_scheduler():
    fake_scheduler = _FakeAPScheduler()
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=300,
        batch_size=20,
        analyzer_factory=lambda mem: _FakeAnalyzer([]),
        scheduler_factory=lambda: fake_scheduler,
    )
    scheduler.start()
    scheduler.stop()
    assert fake_scheduler.shutdown_called is True


def test_tick_calls_analyzer_with_configured_batch_size():
    analyzer = _FakeAnalyzer([_result(processed=5, entities_written=2, relationships_written=1)])
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=300,
        batch_size=42,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: _FakeAPScheduler(),
    )

    payload = scheduler.tick()
    assert analyzer.calls == [{"batch_size": 42, "model": None}]
    assert payload["processed_messages"] == 5
    assert payload["entities_written"] == 2


def test_tick_handles_skip_gracefully():
    analyzer = _FakeAnalyzer([_result(processed=0, skipped=True, reason="llm_unavailable")])
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=300,
        batch_size=20,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: _FakeAPScheduler(),
    )
    payload = scheduler.tick()
    assert payload["skipped"] is True
    assert payload["reason"] == "llm_unavailable"


def test_tick_seconds_floor_prevents_runaway_tight_loop():
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=5,           # too aggressive
        batch_size=20,
        bulk_tick_seconds=1,       # also too aggressive
        analyzer_factory=lambda mem: _FakeAnalyzer([]),
        scheduler_factory=lambda: _FakeAPScheduler(),
    )
    # The floor lives on the instance — exposed via the configured tick.
    assert scheduler._normal_tick >= 30
    assert scheduler._bulk_tick >= 30


# ── Adaptive bulk-mode pacing (S2.2) ─────────────────────────────────────────


def _build_scheduler(memory, fake_scheduler, *, results=None, **kwargs):
    return AnalyzerScheduler(
        memory=memory,
        tick_seconds=kwargs.get("tick_seconds", 900),
        batch_size=kwargs.get("batch_size", 20),
        bulk_tick_seconds=kwargs.get("bulk_tick_seconds", 60),
        bulk_batch_size=kwargs.get("bulk_batch_size", 100),
        bulk_threshold=kwargs.get("bulk_threshold", 100),
        analyzer_factory=lambda mem: _FakeAnalyzer(results or [_result()]),
        scheduler_factory=lambda: fake_scheduler,
    )


def test_tick_stays_in_normal_mode_when_queue_below_threshold():
    fake = _FakeAPScheduler()
    memory = _DepthMemory(depth=10)
    analyzer = _FakeAnalyzer([_result()])
    scheduler = AnalyzerScheduler(
        memory=memory,
        tick_seconds=900,
        batch_size=20,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    scheduler.start()
    scheduler.tick()
    assert scheduler.in_bulk_mode is False
    assert scheduler.current_batch_size == 20
    assert analyzer.calls[0]["batch_size"] == 20
    assert fake.reschedules == []  # never re-triggered the job


def test_tick_enters_bulk_mode_when_queue_exceeds_threshold():
    fake = _FakeAPScheduler()
    memory = _DepthMemory(depth=500)
    analyzer = _FakeAnalyzer([_result()])
    scheduler = AnalyzerScheduler(
        memory=memory,
        tick_seconds=900,
        batch_size=20,
        bulk_tick_seconds=60,
        bulk_batch_size=100,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    scheduler.start()
    scheduler.tick()
    assert scheduler.in_bulk_mode is True
    assert scheduler.current_batch_size == 100
    assert analyzer.calls[0]["batch_size"] == 100
    # Job was rescheduled to the bulk tick interval.
    assert len(fake.reschedules) == 1
    assert fake.reschedules[0]["seconds"] == 60


def test_tick_leaves_bulk_mode_when_queue_drains_below_threshold():
    fake = _FakeAPScheduler()
    memory = _DepthMemory(depth=500)
    analyzer = _FakeAnalyzer([_result(), _result()])
    scheduler = AnalyzerScheduler(
        memory=memory,
        tick_seconds=900,
        batch_size=20,
        bulk_tick_seconds=60,
        bulk_batch_size=100,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    scheduler.start()
    scheduler.tick()
    assert scheduler.in_bulk_mode is True
    # Queue drained — next tick should fall back to normal pacing.
    memory.set_depth(0)
    scheduler.tick()
    assert scheduler.in_bulk_mode is False
    assert scheduler.current_batch_size == 20
    assert analyzer.calls[1]["batch_size"] == 20
    # Two reschedules: into bulk, then back out.
    assert [r["seconds"] for r in fake.reschedules] == [60, 900]


def test_pacing_check_tolerates_count_unanalyzed_failures():
    """If queue-depth probe raises, the scheduler stays in its current mode."""
    fake = _FakeAPScheduler()

    class _BrokenMemory:
        def count_unanalyzed(self):
            raise RuntimeError("chroma offline")

    analyzer = _FakeAnalyzer([_result()])
    scheduler = AnalyzerScheduler(
        memory=_BrokenMemory(),
        tick_seconds=900,
        batch_size=20,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    scheduler.start()
    payload = scheduler.tick()
    assert scheduler.in_bulk_mode is False
    assert analyzer.calls[0]["batch_size"] == 20
    assert payload["processed_messages"] == 0  # the underlying analyze_pending result


def test_pacing_check_skipped_for_memory_without_count_unanalyzed():
    """Backwards-compatible: a memory mock without count_unanalyzed just stays normal."""
    fake = _FakeAPScheduler()
    analyzer = _FakeAnalyzer([_result()])
    scheduler = AnalyzerScheduler(
        memory=object(),
        tick_seconds=900,
        batch_size=20,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    scheduler.start()
    scheduler.tick()
    assert scheduler.in_bulk_mode is False


def test_reschedule_is_a_noop_before_start():
    """Pacing changes before start() shouldn't try to reschedule a non-existent job."""
    fake = _FakeAPScheduler()
    memory = _DepthMemory(depth=500)
    analyzer = _FakeAnalyzer([_result()])
    scheduler = AnalyzerScheduler(
        memory=memory,
        tick_seconds=900,
        batch_size=20,
        bulk_threshold=100,
        analyzer_factory=lambda mem: analyzer,
        scheduler_factory=lambda: fake,
    )
    # Drive a tick without calling start() first. Pacing flips internally,
    # but no reschedule call should be issued.
    scheduler.tick()
    assert scheduler.in_bulk_mode is True
    assert fake.reschedules == []
