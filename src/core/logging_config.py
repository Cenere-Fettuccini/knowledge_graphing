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


def _attach_redactor() -> None:
    """Attach the redactor filter idempotently to every handler and known logger.

    Doing this on handlers (not just loggers) is what actually catches every
    leaked secret — a Logger's filters only run for records originating at
    that logger, while handler filters run for every record the handler emits
    (including records that propagated up from any descendant logger).
    """
    redactor = RedactSecretsFilter()

    def _has_redactor(target) -> bool:
        return any(isinstance(f, RedactSecretsFilter) for f in target.filters)

    # All current handlers on the root logger emit records from every source.
    root = logging.getLogger()
    for handler in root.handlers:
        if not _has_redactor(handler):
            handler.addFilter(redactor)

    # Belt-and-braces: also attach at the logger level so unit tests that
    # bypass handlers (or call Filter.filter directly) still get redaction.
    for name in ("", "httpx", "httpcore", "urllib3", "requests", "google"):
        logger = logging.getLogger(name)
        if not _has_redactor(logger):
            logger.addFilter(redactor)


def setup_logging(level: str | int | None = None, *, force: bool = False) -> None:
    """Initialize root logging once for the whole app.

    Safe to call multiple times: the basic-config step is skipped if handlers
    already exist (unless ``force=True``), but the redactor filter is
    re-attached idempotently every call so a process that touched logging
    *before* importing this module still ends up with redaction wired in.
    """
    log_level = level or settings.log_level
    if isinstance(log_level, str):
        log_level = getattr(logging, log_level.upper(), logging.INFO)

    if not logging.getLogger().handlers or force:
        logging.basicConfig(
            level=log_level,
            format=LOG_FORMAT,
            handlers=[logging.StreamHandler(sys.stdout)],
            force=force,
        )

    _attach_redactor()
