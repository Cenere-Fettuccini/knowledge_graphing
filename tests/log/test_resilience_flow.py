"""Logger never crashes the caller even when its sinks are broken."""

from __future__ import annotations

import logging

from src.log import get_logger, setup_logging


def test_unwritable_log_file_does_not_crash_setup(monkeypatch, tmp_path):
    """Setting up a log file in a non-writable path must not crash setup_logging."""
    bad_path = tmp_path / "nope" / "nested" / "deep" / "log.txt"  # parent dirs missing
    monkeypatch.setenv("LOG_MODE", "dev")
    monkeypatch.setenv("LOG_FILE", str(bad_path))
    # Must not raise.
    setup_logging()
    logger = get_logger("tests.log.resilience")
    # Subsequent calls must also not raise.
    logger.info("still alive")
    logger.error("still alive on error")


def test_logger_call_swallows_handler_exceptions(monkeypatch):
    """Logger calls should swallow exceptions raised from broken logging handlers."""
    monkeypatch.setenv("LOG_MODE", "dev")
    setup_logging()
    root = logging.getLogger()

    class _Boom(logging.Handler):
        def emit(self, record):  # noqa: D401
            raise RuntimeError("handler is broken")

    root.addHandler(_Boom(level=logging.DEBUG))
    logger = get_logger("tests.log.resilience")
    # The caller must not see the RuntimeError.
    logger.info("safe")
    logger.error("safe-error")


def test_get_logger_works_without_explicit_setup(monkeypatch):
    """Calling get_logger before setup_logging must auto-invoke default setup."""
    monkeypatch.delenv("LOG_MODE", raising=False)
    # First call to get_logger auto-invokes setup_logging.
    logger = get_logger("tests.log.resilience.bootstrap")
    logger.info("ok")
    logger.error("ok-error")


def test_invalid_log_mode_falls_back_to_dev(monkeypatch):
    """An invalid LOG_MODE should fall back to 'dev' mode during setup."""
    monkeypatch.setenv("LOG_MODE", "this-is-not-a-mode")
    setup_logging()
    logger = get_logger("tests.log.resilience.fallback")
    logger.info("must not raise")
