"""LOG_MODE controls which levels emit."""

from __future__ import annotations

import logging

from src.log import LogMode, get_logger, setup_logging
from tests.log.conftest import attach_capture


def _emit_all_levels(name: str = "tests.log.modes") -> None:
    logger = get_logger(name)
    logger.debug("d")
    logger.info("i")
    logger.warning("w")
    logger.error("e")
    logger.critical("c")


def test_dev_mode_emits_everything(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "dev")
    setup_logging()
    attach_capture(capture)
    _emit_all_levels()
    levels = [r.levelno for r in capture.records]
    assert logging.DEBUG in levels
    assert logging.INFO in levels
    assert logging.WARNING in levels
    assert logging.ERROR in levels
    assert logging.CRITICAL in levels


def test_prod_mode_emits_only_errors(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "prod")
    setup_logging()
    attach_capture(capture)
    _emit_all_levels()
    levels = {r.levelno for r in capture.records}
    assert levels == {logging.ERROR, logging.CRITICAL}


def test_active_dev_mode_unmarked_function_only_errors(capture, monkeypatch):
    """Functions not decorated emit only ERROR/CRITICAL in active_dev."""
    monkeypatch.setenv("LOG_MODE", "active_dev")
    setup_logging(LogMode.ACTIVE_DEV)
    attach_capture(capture)
    _emit_all_levels()
    levels = {r.levelno for r in capture.records}
    assert logging.DEBUG not in levels
    assert logging.INFO not in levels
    assert logging.ERROR in levels


def test_setup_logging_is_idempotent(monkeypatch):
    monkeypatch.setenv("LOG_MODE", "dev")
    setup_logging()
    setup_logging()
    root = logging.getLogger()
    # Re-applying must not stack handlers indefinitely.
    assert len([h for h in root.handlers if isinstance(h, logging.StreamHandler)]) == 1
