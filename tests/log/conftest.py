"""Shared fixtures for log-module tests.

Each test gets a fresh logging stack: cleared registry, cleared handlers,
and an in-memory handler attached that captures records pre-filter so we
can assert on emission decisions made by the filter (not on what got
through to stderr).
"""

from __future__ import annotations

import logging
from typing import Iterator

import pytest

from src.log import _setup


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        # Apply each attached filter manually so we test the filter's decision.
        for f in self.filters:
            if not f.filter(record):
                return
        self.records.append(record)


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    # Registry is keyed by qualname and populated at module import time —
    # never clear it here, or @in_development/@done decorators would be lost.
    monkeypatch.setattr(_setup, "_configured", False)
    root = logging.getLogger()
    saved = list(root.handlers)
    root.handlers.clear()
    yield
    root.handlers.clear()
    for h in saved:
        root.addHandler(h)


@pytest.fixture
def capture() -> _Capture:
    """An in-memory handler that mirrors root + applies the same filter."""
    return _Capture()


def attach_capture(capture: _Capture) -> None:
    """Attach `capture` to root, copying the ModeFilter from the StreamHandler."""
    root = logging.getLogger()
    # Copy the filter set on the first existing handler (the StreamHandler).
    if root.handlers:
        for f in root.handlers[0].filters:
            capture.addFilter(f)
    root.addHandler(capture)
