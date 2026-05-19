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
    _MemoryManager._instance = None
    yield
    _MemoryManager._instance = None


@pytest.fixture
def log_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "conversations"
    monkeypatch.setenv("CONVERSATION_LOG_DIR", str(d))
    return d
