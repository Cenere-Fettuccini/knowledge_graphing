import logging

from src.core.logging_config import RedactSecretsFilter, _redact


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


def test_filter_passes_non_string_args_unchanged():
    record = logging.LogRecord(
        name="x", level=logging.INFO, pathname=__file__, lineno=1,
        msg="status=%d", args=(200,), exc_info=None,
    )
    assert RedactSecretsFilter().filter(record) is True
    assert record.getMessage() == "status=200"
