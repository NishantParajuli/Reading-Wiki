from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import HTTPException

from novelwiki.kernel.errors import Forbidden, NotFound, ProviderUnavailable, QuotaExceeded
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.narration.application.service import NarrationService
from novelwiki.modules.narration.application.dto import BookAudioCommand, ChapterAudioCommand
from novelwiki.modules.narration.adapters.inbound.http import _result
from novelwiki.modules.ai_execution.adapters.outbound.limits import require_ask_spend_allowed


def principal():
    return Principal(user_id=2, role="reader", status="active", email_verified=True)


def service(*, enabled=True):
    ports = {name: AsyncMock() for name in ("access", "text", "quota", "queries", "jobs", "sidecar")}
    ports["text"].resolve.return_value = {"reason": "ok", "is_overlay": False, "content_version": 1}
    ports["jobs"].find_audio.return_value = None
    ports["jobs"].find_active_chapter_job.return_value = None
    ports["jobs"].find_active_book_job.return_value = None
    ports["queries"].book_candidates.return_value = [{"number": 1, "has_audio": False}]
    return NarrationService(**ports, files=Mock(), default_voice="voice", enabled=enabled, max_batch_chapters=10), ports


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["chapter", "book"])
async def test_disabled_narration_does_not_enqueue_or_check_quota(scope):
    app, ports = service(enabled=False)
    with pytest.raises(ProviderUnavailable):
        if scope == "chapter":
            await app.generate_chapter(7, 1, ChapterAudioCommand(), principal())
        else:
            await app.generate_book(7, BookAudioCommand(), principal())
    ports["quota"].check_available.assert_not_called()
    ports["jobs"].create_job.assert_not_called()


@pytest.mark.asyncio
async def test_cached_audio_remains_available_when_generation_disabled():
    app, ports = service(enabled=False)
    ports["jobs"].find_audio.return_value = {"audio_path": "cached.opus", "duration_seconds": 40}
    ports["jobs"].absolute_audio_path = Mock(return_value="cached.opus")
    app._files.read_timing_manifest.return_value = None
    result = await app.generate_chapter(7, 1, ChapterAudioCommand(), principal())
    assert result["cached"] is True
    ports["jobs"].create_job.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, 2, 3])
async def test_job_requires_current_access_to_private_novel_even_for_orphan_or_owner(owner):
    app, ports = service()
    ports["jobs"].get_job.return_value = {"id": 1, "novel_id": 7, "user_id": owner, "scope": "book"}
    ports["access"].require_readable.side_effect = Forbidden("Private novel")
    with pytest.raises(NotFound, match="Job not found"):
        await app.job(1, principal())


@pytest.mark.asyncio
@pytest.mark.parametrize("error,status", [(QuotaExceeded("Monthly limit reached"), 429), (ProviderUnavailable("Disabled"), 503)])
async def test_narration_expected_errors_have_actionable_http_status(error, status):
    async def failing():
        raise error
    with pytest.raises(HTTPException) as caught:
        await _result(failing())
    assert caught.value.status_code == status
    assert caught.value.detail == str(error)


@pytest.mark.parametrize("status", ["suspended", "banned"])
def test_inactive_admin_cannot_spend_on_uncached_ai_reads(status):
    with pytest.raises(Forbidden, match="not active"):
        require_ask_spend_allowed({"role": "admin", "status": status, "email_verified": True})
