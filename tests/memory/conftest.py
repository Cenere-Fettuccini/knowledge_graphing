"""Shared fixtures for memory-module tests.

Every test gets:
- A fresh ``CONVERSATION_LOG_DIR`` under tmp_path.
- A fresh ``_MemoryManager`` singleton (we reset the class-level slot).
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from src.memory._manager import _MemoryManager


@pytest.fixture(autouse=True)
def _reset_singleton() -> Iterator[None]:
    _MemoryManager.reset_for_tests()
    yield
    _MemoryManager.reset_for_tests()


@pytest.fixture(autouse=True)
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Configure and return a temporary conversation log directory for tests."""
    d = tmp_path / "conversations"
    monkeypatch.setenv("CONVERSATION_LOG_DIR", str(d))
    return d
