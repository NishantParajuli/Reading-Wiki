from __future__ import annotations

import pytest

from novelwiki.modules.identity.public import Principal
from novelwiki.modules.translation.application.ports import BackendDecision
from novelwiki.modules.translation.application.scheduling import (
    ScheduleTranslation,
    TranslationSchedulingService,
)


PRINCIPAL = Principal(
    user_id=7,
    role="user",
    email_verified=True,
    quota_limits={"translation_chapters": 20},
)


class Catalog:
    async def require_editable(self, _novel_id, _principal):
        return None


class Reading:
    async def count_pending(self, *_args):
        return 2


class Backend:
    def __init__(self, resolved):
        self.resolved = resolved

    async def resolve(self, _principal, requested):
        return BackendDecision(requested, self.resolved, "test", "model", None, False)


class Work:
    def __init__(self):
        self.scheduled = None

    async def find_active(self, _key):
        return None

    async def schedule(self, **kwargs):
        self.scheduled = kwargs
        return 11, True


class Quota:
    async def check_available(self, _principal, _units):
        return None

    async def reserve(self, _principal, _units):
        return None

    async def refund(self, _user_id, _units):
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("resolved", "expected"),
    [("agy", 4), ("openai_codex", 2), ("api", None)],
)
async def test_translation_uses_provider_specific_attempt_limit(resolved, expected):
    work = Work()
    service = TranslationSchedulingService(
        Catalog(),
        Reading(),
        Backend(resolved),
        work,
        Quota(),
        agy_max_attempts=4,
        openai_codex_max_attempts=2,
    )

    await service.schedule(1, PRINCIPAL, ScheduleTranslation())

    assert work.scheduled["max_attempts"] == expected
