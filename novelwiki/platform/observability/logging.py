"""Application-owned structured logging for web requests and background workers.

Logs are emitted as one JSON object per line by default so container/journald output can be
ingested by Loki without parsing human prose.  A context variable carries request/job metadata
through nested async calls and child tasks; individual lifecycle events add their own fields.

Operational metadata belongs here.  Prompts, source/story text, generated output, credentials,
and subprocess stdout/stderr deliberately do not.
"""
from __future__ import annotations

import contextvars
import json
import logging
import math
import re
import socket
import sys
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Mapping

from novelwiki.platform.config import settings

_log_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "structured_log_context", default={}
)
_configure_lock = threading.Lock()
_HOSTNAME = socket.gethostname()

_BEARER_RE = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+\-/]+=*")
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_-]?key|authorization|cookie|password|secret|session|token)"
    r"(\s*[:=]\s*)([^\s,;&]+)"
)
_URL_PASSWORD_RE = re.compile(r"(?P<scheme>[a-z][a-z0-9+.-]*://)(?P<user>[^:/\s]+):[^@/\s]+@", re.I)


def _redact_text(value: str) -> str:
    value = _BEARER_RE.sub("Bearer [REDACTED]", value)
    value = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}[REDACTED]", value
    )
    return _URL_PASSWORD_RE.sub(
        lambda match: f"{match.group('scheme')}{match.group('user')}:[REDACTED]@",
        value,
    )


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        # JSON's NaN/Infinity extensions are rejected by Loki's JSON parser. Preserve
        # the record as valid JSON even if a provider metric is non-finite.
        return value if math.isfinite(value) else None
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, (datetime, Path)):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return _redact_text(str(value))


def current_log_context() -> dict[str, Any]:
    return dict(_log_context.get())


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Add non-null structured fields for this sync/async execution context."""
    merged = {**_log_context.get(), **{key: value for key, value in fields.items() if value is not None}}
    token = _log_context.set(merged)
    try:
        yield
    finally:
        try:
            _log_context.reset(token)
        except (LookupError, ValueError):
            pass


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    message: str,
    *,
    exc_info: Any = None,
    **fields: Any,
) -> None:
    """Emit a named event with queryable fields and an optional active traceback."""
    logger.log(
        level,
        message,
        extra={"event": event, "event_fields": fields},
        exc_info=exc_info,
        stacklevel=2,
    )


class JsonFormatter(logging.Formatter):
    """Compact one-line JSON formatter suitable for Docker, journald, and Loki."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, UTC).isoformat(
            timespec="milliseconds"
        ).replace("+00:00", "Z")
        fields = {
            **current_log_context(),
            **dict(getattr(record, "event_fields", {}) or {}),
        }
        try:
            from novelwiki.platform.observability.audit import get_request_id

            request_id = get_request_id()
        except Exception:
            request_id = None
        if request_id and "request_id" not in fields:
            fields["request_id"] = request_id

        payload = {
            **{key: _json_value(value) for key, value in fields.items()},
            "timestamp": timestamp,
            "level": record.levelname.lower(),
            "event": getattr(record, "event", "log"),
            "message": _redact_text(record.getMessage()),
            "logger": record.name,
            "service": settings.LOG_SERVICE,
            "environment": settings.LOG_ENVIRONMENT,
            "host": _HOSTNAME,
            "process_id": record.process,
            "process_name": record.processName,
            "thread_name": record.threadName,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }
        if record.exc_info:
            payload["error_type"] = record.exc_info[0].__name__
            payload["error_message"] = _redact_text(str(record.exc_info[1]))
            payload["stack_trace"] = _redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


class ConsoleFormatter(logging.Formatter):
    """Readable local format that retains the event name and correlation fields."""

    def format(self, record: logging.LogRecord) -> str:
        rendered = _redact_text(super().format(record))
        fields = {**current_log_context(), **dict(getattr(record, "event_fields", {}) or {})}
        useful = " ".join(
            f"{key}={_json_value(value)}" for key, value in fields.items() if value is not None
        )
        event = getattr(record, "event", "log")
        return f"{rendered} event={event}{(' ' + useful) if useful else ''}"


def configure_logging(*, force: bool = False) -> None:
    """Install the shared formatter and route safe Uvicorn loggers through it.

    ``force`` is used by tests or explicit entrypoints that need to replace an earlier
    configuration.  Normal repeated application imports are idempotent.
    """
    with _configure_lock:
        root = logging.getLogger()
        if not force and any(getattr(handler, "_tideglass_handler", False) for handler in root.handlers):
            return
        level_name = settings.LOG_LEVEL.strip().upper()
        level = getattr(logging, level_name, logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler._tideglass_handler = True  # type: ignore[attr-defined]
        if settings.LOG_FORMAT == "json":
            handler.setFormatter(JsonFormatter())
        else:
            handler.setFormatter(
                ConsoleFormatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
        root.handlers.clear()
        root.addHandler(handler)
        root.setLevel(level)

        # Uvicorn normally installs non-propagating handlers before importing the app.
        # Route server/application diagnostics through the shared formatter, but disable
        # its access logger: that logger renders the raw request target, including query
        # strings. Our http.request.* middleware events are the safe access-log contract.
        for name in ("uvicorn", "uvicorn.error"):
            uvicorn_logger = logging.getLogger(name)
            uvicorn_logger.handlers.clear()
            uvicorn_logger.propagate = True
            uvicorn_logger.disabled = False
            uvicorn_logger.setLevel(level)
        uvicorn_access = logging.getLogger("uvicorn.access")
        uvicorn_access.handlers.clear()
        uvicorn_access.propagate = False
        uvicorn_access.disabled = True
        uvicorn_access.setLevel(level)
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("httpcore").setLevel(logging.WARNING)


__all__ = [
    "ConsoleFormatter",
    "JsonFormatter",
    "configure_logging",
    "current_log_context",
    "log_context",
    "log_event",
]
