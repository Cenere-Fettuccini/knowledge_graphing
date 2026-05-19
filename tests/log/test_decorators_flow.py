"""@in_development and @done flip emission in active_dev mode."""

from __future__ import annotations

import logging

from src.log import done, get_logger, in_development, setup_logging
from tests.log.conftest import attach_capture


@in_development
def _emit_dev_marked():
    logger = get_logger("tests.log.decorators")
    logger.info("dev-info")
    logger.debug("dev-debug")
    logger.error("dev-error")


@done
def _emit_done_marked():
    logger = get_logger("tests.log.decorators")
    logger.info("done-info")
    logger.error("done-error")


def _emit_unmarked():
    logger = get_logger("tests.log.decorators")
    logger.info("plain-info")
    logger.error("plain-error")


def test_active_dev_in_development_function_emits_all_levels(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "active_dev")
    setup_logging()
    attach_capture(capture)
    _emit_dev_marked()
    msgs = {r.getMessage() for r in capture.records}
    assert "dev-info" in msgs
    assert "dev-debug" in msgs
    assert "dev-error" in msgs


def test_active_dev_done_function_emits_only_errors(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "active_dev")
    setup_logging()
    attach_capture(capture)
    _emit_done_marked()
    msgs = {r.getMessage() for r in capture.records}
    assert "done-info" not in msgs
    assert "done-error" in msgs


def test_active_dev_unmarked_function_emits_only_errors(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "active_dev")
    setup_logging()
    attach_capture(capture)
    _emit_unmarked()
    msgs = {r.getMessage() for r in capture.records}
    assert "plain-info" not in msgs
    assert "plain-error" in msgs


def test_dev_mode_ignores_decorators(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "dev")
    setup_logging()
    attach_capture(capture)
    _emit_done_marked()
    msgs = {r.getMessage() for r in capture.records}
    assert "done-info" in msgs  # dev mode shows everything regardless of @done
    assert "done-error" in msgs


def test_prod_mode_ignores_decorators(capture, monkeypatch):
    monkeypatch.setenv("LOG_MODE", "prod")
    setup_logging()
    attach_capture(capture)
    _emit_dev_marked()
    levels = {r.levelno for r in capture.records}
    assert logging.INFO not in levels
    assert logging.DEBUG not in levels
    assert logging.ERROR in levels
