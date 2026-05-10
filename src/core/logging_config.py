"""Shared application logging configuration."""

from __future__ import annotations

import logging
import re
import sys

from src.core.config import settings

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

# Query-string parameters that look like credentials. We replace the value with
# REDACTED so log lines (httpx is the loud offender) don't leak api keys when
# pasted into chats / bug reports / terminals over someone's shoulder.
_SECRET_QUERY_PARAMS = (
    "key",
    "api_key",
    "apikey",
    "access_token",
    "token",
    "secret",
    "authorization",
    "auth",
    "x-api-key",
)
_SECRET_QUERY_RE = re.compile(
    r"([?&](?:" + "|".join(_SECRET_QUERY_PARAMS) + r")=)([^&\s\"']+)",
    flags=re.IGNORECASE,
)
# Bare bearer tokens that aren't in a URL query — e.g. "Authorization: Bearer …".
_BEARER_RE = re.compile(r"(Bearer\s+)([A-Za-z0-9\-_.~+/=]{8,})", flags=re.IGNORECASE)


def _redact(value: str) -> str:
    return _BEARER_RE.sub(r"\1REDACTED", _SECRET_QUERY_RE.sub(r"\1REDACTED", value))


class RedactSecretsFilter(logging.Filter):
    """Strip credentials out of log records before any handler sees them."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - stdlib API
        try:
            if isinstance(record.msg, str) and ("=" in record.msg or "Bearer" in record.msg):
                record.msg = _redact(record.msg)
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(
                        _redact(a) if isinstance(a, str) else a for a in record.args
                    )
                elif isinstance(record.args, dict):
                    record.args = {
                        k: (_redact(v) if isinstance(v, str) else v)
                        for k, v in record.args.items()
                    }
        except Exception:  # pragma: no cover - filters must never raise
            pass
        return True


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

    # Apply on the root logger so every handler downstream gets redacted records.
    redactor = RedactSecretsFilter()
    logging.getLogger().addFilter(redactor)
    # Belt-and-braces: also attach directly to the loudest known sources.
    for noisy in ("httpx", "httpcore", "urllib3", "requests"):
        logging.getLogger(noisy).addFilter(redactor)
