from __future__ import annotations

from collections.abc import Awaitable, Callable


async def schedule_ai_job(
    reserve: Callable[[], Awaitable[None]],
    schedule: Callable[[], Awaitable[tuple[int, bool]]],
    refund: Callable[[], Awaitable[None]],
    before_schedule: Callable[[], Awaitable[None]] | None = None,
) -> tuple[int, bool]:
    """Preserve reserve → command → create/dedupe → refund ordering for AI work."""
    await reserve()
    try:
        if before_schedule is not None:
            await before_schedule()
        job_id, created = await schedule()
    except Exception:
        await refund()
        raise
    if not created:
        await refund()
    return job_id, created
