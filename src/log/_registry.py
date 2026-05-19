"""Function-status registry and the @in_development / @done decorators.

Decorators don't wrap behaviour — they register a function's qualified name
in a process-wide dict. The filter consults this dict at log-emit time.
"""

from __future__ import annotations

from enum import Enum
from typing import Callable, TypeVar

F = TypeVar("F", bound=Callable)


class Status(str, Enum):
    IN_DEVELOPMENT = "in_development"
    DONE = "done"


_registry: dict[str, Status] = {}


def _qualname(fn: Callable) -> str:
    module = getattr(fn, "__module__", "") or ""
    qual = getattr(fn, "__qualname__", "") or getattr(fn, "__name__", "")
    return f"{module}.{qual}" if module else qual


def in_development(fn: F) -> F:
    """Mark a function as actively under development.

    In active_dev mode, log lines from this function emit at every level.
    """
    _registry[_qualname(fn)] = Status.IN_DEVELOPMENT
    return fn


def done(fn: F) -> F:
    """Mark a function as complete.

    In active_dev mode, only ERROR/CRITICAL lines from this function emit.
    """
    _registry[_qualname(fn)] = Status.DONE
    return fn


def lookup(qualified_name: str) -> Status | None:
    return _registry.get(qualified_name)


def clear() -> None:
    """Test helper — reset the registry between tests."""
    _registry.clear()
