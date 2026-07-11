from typing import Protocol


class NarrationApi(Protocol):
    async def schedule_chapter(self, novel_id: int, chapter: float, user_id: int, voice: str) -> int: ...
    async def cancel(self, job_id: int, user_id: int) -> None: ...


async def coverage_for_novel(novel_id: int) -> dict:
    from .adapters.outbound.coverage import coverage_for_novel as implementation

    return await implementation(novel_id)


async def shared_audio_coverage(
    novel_id: int, include_voice_ids=None
) -> dict:
    from .adapters.outbound.coverage import shared_audio_coverage as implementation

    return await implementation(novel_id, include_voice_ids)
