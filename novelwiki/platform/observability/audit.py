"""Durable audit log + per-request correlation id.

Two small pieces of observability that let us operate the background pipelines confidently:

- A ``request_id`` contextvar propagated by the HTTP middleware (novelwiki/api/app.py). It is
  echoed back in the ``X-Request-ID`` response header and stamped onto audit rows and log lines,
  so a single user action can be traced across the request and any jobs it spawns.
- ``record()`` appends a row to ``audit_events`` (job lifecycle, quota reservations/refunds, and
  room for auth/visibility/admin actions). Best-effort: an audit write must never break the work
  it is describing, so failures are swallowed and logged at debug.
"""
from __future__ import annotations

import contextvars
import json
import logging
import uuid
from typing import Protocol

from novelwiki.platform.database import get_db_pool

logger = logging.getLogger(__name__)

# Set by the request-id middleware for the duration of an HTTP request; None for worker-initiated
# work (a job created in one request keeps that request's id via the stored row, not this var).
_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)


def new_request_id() -> str:
    return uuid.uuid4().hex


def set_request_id(value: str | None) -> contextvars.Token:
    return _request_id.set(value)


def reset_request_id(token: contextvars.Token) -> None:
    try:
        _request_id.reset(token)
    except (LookupError, ValueError):
        pass


def get_request_id() -> str | None:
    return _request_id.get()


async def record(event: str, *, user_id: int | None = None, novel_id: int | None = None,
                 request_id: str | None = None, data: dict | None = None) -> None:
    """Append one audit row. Best-effort — never raises into the caller."""
    rid = request_id if request_id is not None else get_request_id()
    try:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO audit_events (event, user_id, novel_id, request_id, data)
                VALUES ($1, $2, $3, $4, $5);
                """,
                event, user_id, novel_id, rid, json.dumps(data or {}),
            )
    except Exception as e:  # observability must not take down the actual work
        logger.debug(f"audit.record({event!r}) skipped: {e}")


class AuditSink(Protocol):
    async def record(self, event: str, **fields) -> None: ...


class FunctionAuditSink:
    """Object adapter for modules that consume the explicit AuditSink port."""

    async def record(self, event: str, **fields) -> None:
        await record(event, **fields)
