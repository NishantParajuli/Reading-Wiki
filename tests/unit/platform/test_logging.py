from __future__ import annotations

import io
import json
import logging
import sys

from novelwiki.platform.observability import audit
from novelwiki.platform.observability.logging import (
    ConsoleFormatter,
    JsonFormatter,
    configure_logging,
    log_context,
)


def _record(message: str, *, event: str = "test.event", fields: dict | None = None):
    return logging.LogRecord(
        name="tests.logging", level=logging.INFO, pathname=__file__, lineno=12,
        msg=message, args=(), exc_info=None, func="test", sinfo=None,
    ), event, fields or {}


def test_json_formatter_emits_context_event_and_request_fields():
    record, event, fields = _record(
        "Starting codex job 42.", fields={"stage": "chunking", "progress": {"step": 1}}
    )
    record.event = event
    record.event_fields = fields
    request_token = audit.set_request_id("req-123")
    try:
        with log_context(
            worker_type="api", worker_id="api-100", job_system="generic",
            job_id=42, job_kind="codex_build", novel_id=7, user_id=9,
        ):
            payload = json.loads(JsonFormatter().format(record))
    finally:
        audit.reset_request_id(request_token)

    assert payload["event"] == "test.event"
    assert payload["message"] == "Starting codex job 42."
    assert payload["request_id"] == "req-123"
    assert payload["job_id"] == 42
    assert payload["job_kind"] == "codex_build"
    assert payload["worker_id"] == "api-100"
    assert payload["stage"] == "chunking"
    assert payload["progress"] == {"step": 1}
    assert payload["timestamp"].endswith("Z")
    assert payload["level"] == "info"


def test_json_formatter_redacts_credentials_and_includes_traceback():
    try:
        raise RuntimeError(
            "provider failed with Authorization: Bearer abc.def and "
            "postgresql://reader:supersecret@db/novelwiki"
        )
    except RuntimeError:
        record = logging.LogRecord(
            name="tests.logging", level=logging.ERROR, pathname=__file__, lineno=44,
            msg="token=visible password=hunter2", args=(), exc_info=sys.exc_info(),
            func="test", sinfo=None,
        )
    record.event = "job.crashed"
    record.event_fields = {"api_key": "api_key=should-not-appear"}

    payload = json.loads(JsonFormatter().format(record))
    rendered = json.dumps(payload)

    assert payload["event"] == "job.crashed"
    assert payload["error_type"] == "RuntimeError"
    assert "Traceback" in payload["stack_trace"]
    assert "abc.def" not in rendered
    assert "supersecret" not in rendered
    assert "hunter2" not in rendered
    assert "should-not-appear" not in rendered
    assert "[REDACTED]" in rendered


def test_nested_log_context_restores_outer_values():
    with log_context(job_id=1, job_kind="scrape"):
        with log_context(job_id=2, stage="scraping"):
            inner, _, _ = _record("inner")
            inner.event_fields = {}
            inner_payload = json.loads(JsonFormatter().format(inner))
        outer, _, _ = _record("outer")
        outer.event_fields = {}
        outer_payload = json.loads(JsonFormatter().format(outer))

    assert inner_payload["job_id"] == 2
    assert inner_payload["job_kind"] == "scrape"
    assert inner_payload["stage"] == "scraping"
    assert outer_payload["job_id"] == 1
    assert "stage" not in outer_payload


def test_formatters_keep_json_valid_and_redact_console_credentials():
    record, event, _ = _record("password=hunter2")
    record.event = event
    record.event_fields = {"duration_ms": float("inf")}

    payload = json.loads(JsonFormatter().format(record))
    console = ConsoleFormatter("%(message)s").format(record)

    assert payload["duration_ms"] is None
    assert "hunter2" not in console
    assert "[REDACTED]" in console


def test_configure_logging_drops_raw_uvicorn_access_targets():
    root = logging.getLogger()
    logger_names = ("uvicorn", "uvicorn.error", "uvicorn.access")
    root_state = (list(root.handlers), root.level)
    logger_state = {
        name: (
            list(logging.getLogger(name).handlers),
            logging.getLogger(name).propagate,
            logging.getLogger(name).disabled,
            logging.getLogger(name).level,
        )
        for name in logger_names
    }
    capture_stream = io.StringIO()
    capture = logging.StreamHandler(capture_stream)
    try:
        configure_logging(force=True)
        root.addHandler(capture)

        access = logging.getLogger("uvicorn.access")
        access.info(
            '127.0.0.1 - "GET /api/auth/oauth/callback?code=secret-code HTTP/1.1" 200'
        )

        assert access.disabled is True
        assert access.propagate is False
        assert access.handlers == []
        assert "secret-code" not in capture_stream.getvalue()
        assert logging.getLogger("uvicorn.error").propagate is True
    finally:
        root.handlers.clear()
        root.handlers.extend(root_state[0])
        root.setLevel(root_state[1])
        for name, (handlers, propagate, disabled, level) in logger_state.items():
            target = logging.getLogger(name)
            target.handlers.clear()
            target.handlers.extend(handlers)
            target.propagate = propagate
            target.disabled = disabled
            target.setLevel(level)
