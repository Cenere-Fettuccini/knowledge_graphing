"""Custom logging.Filter consulting the @in_development / @done registry."""

from __future__ import annotations

import logging
import sys
from enum import Enum

from src.log._registry import Status, lookup


class LogMode(str, Enum):
    DEV = "dev"
    PROD = "prod"
    ACTIVE_DEV = "active_dev"


def _record_qualname(record: logging.LogRecord) -> str:
    """Best-effort qualified name for the function that emitted `record`.

    The stdlib LogRecord exposes module + funcName but not __qualname__.
    We walk the frame stack to recover the bound method's qualified name
    where possible. Falls back to module.funcName.
    """
    module = record.module if record.module else ""
    func = record.funcName or ""
    # Walk up the stack to find the frame matching this record.
    try:
        frame = sys._getframe(1)
        while frame is not None:
            if (
                frame.f_code.co_name == func
                and frame.f_globals.get("__name__", "").endswith(module)
            ):
                # Try to find self/cls for a qualified name.
                self_obj = frame.f_locals.get("self")
                if self_obj is not None:
                    cls = type(self_obj).__name__
                    return f"{frame.f_globals.get('__name__', module)}.{cls}.{func}"
                cls_obj = frame.f_locals.get("cls")
                if cls_obj is not None:
                    return (
                        f"{frame.f_globals.get('__name__', module)}."
                        f"{getattr(cls_obj, '__name__', '')}.{func}"
                    )
                return f"{frame.f_globals.get('__name__', module)}.{func}"
            frame = frame.f_back
    except Exception:
        pass
    full_module = record.name if record.name else module
    return f"{full_module}.{func}"


class ModeFilter(logging.Filter):
    """Decide whether a LogRecord emits given the active mode + registry."""

    def __init__(self, mode: LogMode) -> None:
        super().__init__()
        self.mode = mode

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        try:
            if self.mode is LogMode.DEV:
                return True
            if self.mode is LogMode.PROD:
                return record.levelno >= logging.ERROR
            # ACTIVE_DEV: errors always; otherwise depend on registry
            if record.levelno >= logging.ERROR:
                return True
            qual = _record_qualname(record)
            status = lookup(qual)
            # Also try shorter variants in case the frame walk missed.
            if status is None:
                # Try suffix match for any registered name ending with .funcName
                func = record.funcName or ""
                for name, st in _iter_registry():
                    if name.endswith("." + func) or name == func:
                        status = st
                        break
            if status is Status.IN_DEVELOPMENT:
                return True
            # done or unmarked: suppress below ERROR
            return False
        except Exception:
            # Resilience: never let the filter raise.
            return True


def _iter_registry():
    # Local import to avoid cycles at import time and to read live state.
    from src.log._registry import _registry

    return list(_registry.items())
