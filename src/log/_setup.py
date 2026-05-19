"""Central handler/formatter configuration. Reads LOG_MODE / LOG_FORMAT / LOG_FILE."""

from __future__ import annotations

import json
import logging
import os
import sys
from datetime import datetime, timezone

from src.log._filter import LogMode, ModeFilter

_RESERVED_LOGRECORD_KEYS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        base = (
            f"{ts} level={record.levelname} logger={record.name} "
            f"func={record.funcName} msg=\"{record.getMessage()}\""
        )
        extras = []
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOGRECORD_KEYS or k.startswith("_"):
                continue
            extras.append(f"{k}={v}")
        if extras:
            base = base + " " + " ".join(extras)
        if record.exc_info:
            base = base + "\n" + self.formatException(record.exc_info)
        return base


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:  # noqa: A003
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        out: dict = {
            "timestamp": ts,
            "level": record.levelname,
            "logger": record.name,
            "func": record.funcName,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k in _RESERVED_LOGRECORD_KEYS or k.startswith("_"):
                continue
            out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        try:
            return json.dumps(out, default=str)
        except Exception:
            return json.dumps({"level": record.levelname, "msg": str(record.getMessage())})


_configured: bool = False


def _coerce_mode(mode: LogMode | str | None) -> LogMode:
    if mode is None:
        mode = os.environ.get("LOG_MODE", "dev")
    if isinstance(mode, LogMode):
        return mode
    try:
        return LogMode(str(mode).lower())
    except ValueError:
        return LogMode.DEV


def _build_formatter() -> logging.Formatter:
    fmt = os.environ.get("LOG_FORMAT", "text").lower()
    return _JsonFormatter() if fmt == "json" else _TextFormatter()


def setup_logging(mode: LogMode | str | None = None) -> None:
    """Configure the root logger. Idempotent."""
    global _configured
    active_mode = _coerce_mode(mode)
    root = logging.getLogger()

    # Remove existing handlers — idempotent reconfigure.
    for h in list(root.handlers):
        root.removeHandler(h)

    root.setLevel(logging.DEBUG)  # let the filter decide; never block at the root level

    formatter = _build_formatter()
    mode_filter = ModeFilter(active_mode)

    stderr_handler = logging.StreamHandler(stream=sys.stderr)
    stderr_handler.setLevel(logging.DEBUG)
    stderr_handler.setFormatter(formatter)
    stderr_handler.addFilter(mode_filter)
    root.addHandler(stderr_handler)

    log_file = os.environ.get("LOG_FILE")
    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            file_handler.addFilter(mode_filter)
            root.addHandler(file_handler)
        except OSError:
            # Resilience: bad LOG_FILE path must not crash setup.
            root.error(
                "log_file_unwritable",
                extra={"log_file": log_file},
            )

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a logger. Auto-invokes setup_logging() with defaults if needed."""
    if not _configured:
        setup_logging()
    logger = logging.getLogger(name)
    # Wrap each call so a broken handler can never crash the caller.
    return _ResilientLogger(logger)


class _ResilientLogger:
    """Thin proxy around a logging.Logger that swallows handler errors.

    Every public log call (info/debug/warning/error/critical/log/exception)
    is wrapped — if the underlying handler raises (unwritable file, broken
    socket, formatter bug), the call returns instead of bubbling up.
    """

    __slots__ = ("_logger",)

    def __init__(self, inner: logging.Logger) -> None:
        self._logger = inner

    # Forward attribute access so callers can still use level constants etc.
    def __getattr__(self, item: str):
        attr = getattr(self._logger, item)
        if callable(attr) and item in {
            "debug", "info", "warning", "warn", "error", "critical", "exception", "log"
        }:
            def safe(*args, **kwargs):
                # Hide this wrapper frame from logging's caller-detection.
                kwargs["stacklevel"] = kwargs.get("stacklevel", 1) + 1
                try:
                    return attr(*args, **kwargs)
                except Exception:
                    # Last-ditch: never raise from a log call.
                    return None
            return safe
        return attr

    @property
    def name(self) -> str:
        return self._logger.name

    @property
    def level(self) -> int:
        return self._logger.level

    def isEnabledFor(self, level: int) -> bool:  # noqa: N802
        try:
            return self._logger.isEnabledFor(level)
        except Exception:
            return False
