import io
import logging

import pytest

from src.core.logging_config import RedactSecretsFilter, _redact, setup_logging


def test_redact_query_param_key():
    out = _redact("GET https://example.com/v1/models?key=AIzaSyABCDEFG12345 HTTP/1.1")
    assert "AIzaSyABCDEFG12345" not in out
    assert "key=REDACTED" in out


def test_redact_preserves_other_params():
    out = _redact("https://example.com/x?key=secret&page=2&token=t1")
    assert "key=REDACTED" in out
    assert "page=2" in out
    assert "token=REDACTED" in out


def test_redact_bearer_header():
    out = _redact('Authorization: Bearer abcd1234EFGH-_=.+/')
    assert "abcd1234EFGH-_=.+/" not in out
    assert "Bearer REDACTED" in out


def test_filter_redacts_record_msg():
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg="HTTP Request: GET https://api.example.com/v1?key=AIzaSyXYZ \"HTTP/1.1 200 OK\"",
        args=None, exc_info=None,
    )
    RedactSecretsFilter().filter(record)
    assert "AIzaSyXYZ" not in record.getMessage()
    assert "key=REDACTED" in record.getMessage()


def test_filter_redacts_string_args():
    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=("GET", "https://api.example.com/v1?key=SECRETKEY", "HTTP/1.1", 200, "OK"),
        exc_info=None,
    )
    RedactSecretsFilter().filter(record)
    formatted = record.getMessage()
    assert "SECRETKEY" not in formatted
    assert "key=REDACTED" in formatted


def test_filter_redacts_non_string_url_arg():
    """Regression: httpx logs request.url as a URL *object*, not a str. The filter
    must still strip the api key out of the formatted message — otherwise logging
    stringifies the URL *after* the filter runs and the secret leaks."""

    class FakeURL:
        def __init__(self, value: str) -> None:
            self._value = value

        def __str__(self) -> str:
            return self._value

    record = logging.LogRecord(
        name="httpx", level=logging.INFO, pathname=__file__, lineno=1,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=("GET", FakeURL("https://api.example.com/v1?key=LEAKEDKEY"),
              "HTTP/1.1", 200, "OK"),
        exc_info=None,
    )
    RedactSecretsFilter().filter(record)
    formatted = record.getMessage()
    assert "LEAKEDKEY" not in formatted
    assert "key=REDACTED" in formatted


def test_filter_passes_non_string_args_unchanged():
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="status=%d", args=(200,), exc_info=None,
    )
    assert RedactSecretsFilter().filter(record) is True
    assert record.getMessage() == "status=200"


# ── Integration: setup_logging actually wires redaction into the real handlers ─


@pytest.fixture
def isolated_logging():
    """Snapshot/restore the root logger so these tests don't leak handlers/filters."""
    root = logging.getLogger()
    saved_handlers = list(root.handlers)
    saved_filters = list(root.filters)
    saved_level = root.level
    # Snapshot the loggers we touch too.
    saved_loggers = {
        name: list(logging.getLogger(name).filters)
        for name in ("httpx", "httpcore", "urllib3", "requests", "google")
    }
    try:
        yield
    finally:
        root.handlers = saved_handlers
        root.filters = saved_filters
        root.level = saved_level
        for name, filters in saved_loggers.items():
            logging.getLogger(name).filters = list(filters)


def test_setup_logging_attaches_redactor_to_root_handler(isolated_logging):
    """Records emitted via the root handler (where httpx-propagated records go) must be redacted."""
    root = logging.getLogger()
    root.handlers = []  # force a fresh basicConfig
    setup_logging(force=True)

    # At least one handler is attached and carries the redactor filter.
    assert root.handlers, "setup_logging should leave at least one handler on root"
    assert any(
        any(isinstance(f, RedactSecretsFilter) for f in h.filters)
        for h in root.handlers
    ), "redactor must be attached to a root handler so it catches propagated records"


def test_setup_logging_is_idempotent_for_filters(isolated_logging):
    """Calling setup_logging twice must not double-attach the redactor."""
    logging.getLogger().handlers = []
    setup_logging(force=True)
    setup_logging()  # second call — should not duplicate

    counts = {
        target_name: sum(
            isinstance(f, RedactSecretsFilter) for f in target.filters
        )
        for target_name, target in (
            ("root", logging.getLogger()),
            ("httpx", logging.getLogger("httpx")),
            ("google", logging.getLogger("google")),
        )
    }
    for name, count in counts.items():
        assert count == 1, f"{name} has {count} redactor filters; expected exactly 1"


def test_httpx_style_emit_through_root_handler_is_redacted(isolated_logging):
    """End-to-end: an httpx-shaped record emitted to a stream handler comes out redacted."""
    logging.getLogger().handlers = []
    setup_logging(force=True)

    buf = io.StringIO()
    stream_handler = logging.StreamHandler(buf)
    stream_handler.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
    # Attach the same redactor to this test handler so we mirror production
    # (where setup_logging attaches it to whatever handlers are on root).
    for f in logging.getLogger().handlers[0].filters:
        if isinstance(f, RedactSecretsFilter):
            stream_handler.addFilter(f)
            break
    logging.getLogger().addHandler(stream_handler)

    logging.getLogger("httpx").info(
        'HTTP Request: GET https://example.com/v1/models?key=AIzaSyREALKEYABCDEF "HTTP/1.1 200 OK"'
    )

    output = buf.getvalue()
    assert "AIzaSyREALKEYABCDEF" not in output
    assert "key=REDACTED" in output


def test_setup_logging_reattaches_redactor_when_called_after_external_setup(isolated_logging):
    """If something else configured logging first, setup_logging must still wire redaction in."""
    # Simulate an external library installing a handler before our code runs.
    logging.getLogger().handlers = [logging.StreamHandler(io.StringIO())]
    setup_logging()  # no force — should still attach the filter
    handler = logging.getLogger().handlers[0]
    assert any(isinstance(f, RedactSecretsFilter) for f in handler.filters), (
        "redactor must be attached even when basicConfig is skipped"
    )
