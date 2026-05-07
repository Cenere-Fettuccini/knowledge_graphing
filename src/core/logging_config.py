"""Shared application logging configuration."""

from __future__ import annotations

import logging
import sys

from src.core.config import settings

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def setup_logging(level: str | int | None = None, *, force: bool = False) -> None:
    """Initialize root logging once for the whole app."""
    if logging.getLogger().handlers and not force:
        return

    log_level = level or settings.log_level
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format=LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stdout)],
        force=force,
    )
