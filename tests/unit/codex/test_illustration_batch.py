from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from novelwiki.modules.codex.application.illustration_batch import (
    IllustrationBatchWorker,
)
from novelwiki.modules.codex.domain.illustrations import source_hash
from novelwiki.modules.ai_execution.public import AgyCanceled


@pytest.mark.asyncio
async def test_range_progress_hides_unread_identity_and_cancellation_stops_next_chapter():
    snapshot = {"title": "Chapter", "content": "A quiet evening by the river."}
    job = {
        "id": 1,
        "novel_id": 1,
        "options": {
            "style": "luminous",
            "chapters": [
                {"chapter": number, "source_hash": source_hash(snapshot)}
                for number in (25, 26)
            ],
        },
    }
    report = AsyncMock()
    calls = []

    async def chapter(child, progress):
        calls.append(child["options"]["chapter"])
        await progress(
            1, {"stage": "Designing Secret Identity"}, stage="Creating character sheets"
        )

    async def cancel(_job_id):
        if calls:
            raise AgyCanceled("Stopped")

    worker = IllustrationBatchWorker(
        store=SimpleNamespace(
            plan=AsyncMock(return_value={"mode": "range"}),
            range_plan=AsyncMock(return_value=None),
        ),
        snapshot=AsyncMock(return_value=snapshot),
        current_rows=AsyncMock(return_value=[]),
        execute_chapter=chapter,
        progress=report,
        cancel=cancel,
    )
    with pytest.raises(AgyCanceled):
        await worker.execute(job)
    assert calls == [25]
    assert all("Secret Identity" not in str(call) for call in report.call_args_list)
    assert (
        report.call_args_list[-1].args[1]["stage"]
        == "Chapter 25: Creating character sheets"
    )
