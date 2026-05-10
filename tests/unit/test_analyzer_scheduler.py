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

    def add_job(self, func, **kwargs):
        self.jobs.append({"func": func, **kwargs})

    def start(self):
        self.started = True

    def shutdown(self, wait=False):
        self.shutdown_called = True


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
        analyzer_factory=lambda mem: _FakeAnalyzer([]),
        scheduler_factory=lambda: _FakeAPScheduler(),
    )
    # The floor lives on the instance — exposed via the configured tick.
    assert scheduler._tick_seconds >= 30
