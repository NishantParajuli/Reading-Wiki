"""Direct-call compatibility exports for Narration HTTP handlers."""

from __future__ import annotations

import inspect
from functools import wraps

from novelwiki.modules.narration.adapters.inbound import http as _native


async def _invoke(handler, *args, **kwargs):
    parameters = inspect.signature(handler).parameters
    if "service" in parameters:
        from novelwiki.bootstrap.narration import build_narration_service
        kwargs.setdefault("service", await build_narration_service())
    if "principal_factory" in parameters:
        from novelwiki.bootstrap.narration import build_narration_principal_factory
        kwargs.setdefault("principal_factory", build_narration_principal_factory())
    return await handler(*args, **kwargs)


def _direct(handler):
    @wraps(handler)
    async def invoke(*args, **kwargs):
        return await _invoke(handler, *args, **kwargs)
    return invoke


for _name in dir(_native):
    _value = getattr(_native, _name)
    if _name.startswith("api_") and callable(_value):
        globals()[_name] = _direct(_value)
    elif not _name.startswith("_"):
        globals()[_name] = _value

del _name, _value
