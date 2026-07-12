"""FastAPI compatibility adapter for framework-free AI cost controls."""

from contextlib import asynccontextmanager
from fastapi import HTTPException
from novelwiki.kernel.errors import Forbidden, RateLimited
from novelwiki.modules.ai_execution.adapters.outbound import limits as _limits


def _translate(exc):
    headers = None
    if isinstance(exc, RateLimited) and exc.retry_after is not None:
        headers = {"Retry-After": str(exc.retry_after)}
    raise HTTPException(
        status_code=429 if isinstance(exc, RateLimited) else 403,
        detail=str(exc), headers=headers,
    ) from exc


def require_ask_spend_allowed(user):
    try:
        return _limits.require_ask_spend_allowed(user)
    except (Forbidden, RateLimited) as exc:
        _translate(exc)


async def consume_ask_rate(user, kind="ask"):
    try:
        return await _limits.consume_ask_rate(user, kind)
    except (Forbidden, RateLimited) as exc:
        _translate(exc)


@asynccontextmanager
async def concurrency_slot(user, kind="ask"):
    try:
        async with _limits.concurrency_slot(user, kind):
            yield
    except (Forbidden, RateLimited) as exc:
        _translate(exc)


def __getattr__(name):
    return getattr(_limits, name)
