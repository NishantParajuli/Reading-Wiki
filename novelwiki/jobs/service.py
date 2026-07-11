"""Stable compatibility wrapper for Work Management persistence operations."""

from novelwiki.modules.work.adapters.outbound import postgres as _implementation


async def create_job(*args, **kwargs):
    if kwargs.get("execution_backend") == "agy" and "policy_lookup" not in kwargs:
        from novelwiki.modules.ai_execution.adapters.outbound.policy import get_policy

        kwargs["policy_lookup"] = get_policy
    return await _implementation.create_job(*args, **kwargs)


def __getattr__(name):
    return getattr(_implementation, name)
