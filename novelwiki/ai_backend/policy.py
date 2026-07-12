"""External compatibility surface for AI backend policy operations."""

from novelwiki.bootstrap.ai_execution import wire_ai_policy

wire_ai_policy()

from fastapi import HTTPException
from novelwiki.kernel.errors import Forbidden, NotFound, ProviderUnavailable, RateLimited, ValidationFailed
from novelwiki.modules.ai_execution.adapters.outbound import policy as _policy


def _http(exc):
    status = (
        404 if isinstance(exc, NotFound) else
        403 if isinstance(exc, Forbidden) else
        429 if isinstance(exc, RateLimited) else
        503 if isinstance(exc, ProviderUnavailable) else 422
    )
    raise HTTPException(status_code=status, detail=str(exc)) from exc


async def resolve_backend(*args, **kwargs):
    try:
        return await _policy.resolve_backend(*args, **kwargs)
    except (Forbidden, NotFound, ProviderUnavailable, RateLimited, ValidationFailed) as exc:
        _http(exc)


async def upsert_policy(*args, **kwargs):
    try:
        return await _policy.upsert_policy(*args, **kwargs)
    except (Forbidden, NotFound, ProviderUnavailable, RateLimited, ValidationFailed) as exc:
        _http(exc)


async def delete_policy(*args, **kwargs):
    try:
        return await _policy.delete_policy(*args, **kwargs)
    except (Forbidden, NotFound, ProviderUnavailable, RateLimited, ValidationFailed) as exc:
        _http(exc)


def __getattr__(name):
    return getattr(_policy, name)
