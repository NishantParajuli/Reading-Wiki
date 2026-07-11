from __future__ import annotations

import contextlib

import pytest

from novelwiki.kernel.errors import Conflict, ValidationFailed
from novelwiki.modules.codex.application import (
    ActiveCodexJob, BackendDecision, BuildCodex, CeilingContext,
    CodexCommandService, CodexQueryService,
)
from novelwiki.modules.codex.public import ChapterCeiling
from novelwiki.modules.identity.public import Principal


PRINCIPAL = Principal(
    user_id=7, role="user", email_verified=True,
    quota_limits={"codex_builds": 20},
)


class Ceiling:
    calls = 0

    async def resolve(self, novel_id, principal, requested):
        self.calls += 1
        return CeilingContext(
            ChapterCeiling(4.0), requested, 4.0, requested not in (None, 4.0),
            10, 1.0, 10.0, "Novel", "Blurb", 4.0, "Fourth",
        )


class Queries:
    async def stats(self, novel_id, ceiling):
        assert isinstance(ceiling, ChapterCeiling)
        return {"entities_revealed": 2, "facts_known": 3, "relationships_known": 1}

    async def cached_profile(self, novel_id, entity_id, ceiling):
        assert isinstance(ceiling, ChapterCeiling)
        return "cached profile"

    async def entity_profile(self, novel_id, entity_id, ceiling):
        assert isinstance(ceiling, ChapterCeiling)
        return {"id": entity_id, "facts": [], "aliases": []}


class Agent:
    def __init__(self, cached=None):
        self.cached = cached

    def query_hash(self, question):
        return "same-byte-key"

    async def cached_answer(self, novel_id, query_hash, ceiling):
        assert isinstance(ceiling, ChapterCeiling)
        return self.cached

    async def citations(self, novel_id, answer, ceiling):
        return [{"kind": "fact", "id": 1, "chapter": 4.0, "snippet": "x"}]


class Costs:
    def __init__(self):
        self.calls = []

    def require_spend_allowed(self, principal):
        self.calls.append("spend")

    @contextlib.asynccontextmanager
    async def concurrency_slot(self, principal, kind):
        self.calls.append(f"slot:{kind}")
        yield

    async def consume_rate(self, principal, kind):
        self.calls.append(f"rate:{kind}")


def query_service(*, cached=None):
    ceiling = Ceiling()
    ceiling.calls = 0
    costs = Costs()
    return CodexQueryService(
        ceiling, Queries(), Agent(cached), costs,
        ask_max_query_chars=20, ask_requires_verified=True,
        profile_requires_verified=True, profile_model="pro",
    ), ceiling, costs


@pytest.mark.asyncio
async def test_ask_validates_before_ceiling_or_provider_work():
    service, ceiling, costs = query_service()

    with pytest.raises(ValidationFailed, match="can't be empty"):
        await service.ask(1, "  ", 9, PRINCIPAL)

    assert ceiling.calls == 0
    assert costs.calls == []


@pytest.mark.asyncio
async def test_cached_ask_is_clamped_and_bypasses_all_cost_gates():
    service, _, costs = query_service(cached={
        "answer_md": "answer [Fact 1]", "evidence_ids": {"fact_ids": [1]},
    })

    result = await service.ask(1, "question", 9, PRINCIPAL)

    assert result["effective_ceiling"] == 4.0
    assert result["ceiling_clamped"] is True
    assert result["citations"][0]["id"] == 1
    assert costs.calls == []


@pytest.mark.asyncio
async def test_cached_profile_bypasses_synthesis_cost_gates():
    service, _, costs = query_service()

    result = await service.entity_profile(1, 8, 4, PRINCIPAL)

    assert result["rendered_md"] == "cached profile"
    assert costs.calls == []


class Catalog:
    def __init__(self):
        self.enabled = 0

    async def require_editable(self, novel_id, principal):
        pass

    async def enable_codex(self, novel_id):
        self.enabled += 1


class Backend:
    def __init__(self):
        self.calls = 0

    async def resolve(self, principal, requested):
        self.calls += 1
        return BackendDecision("auto", "api", "global_disabled", "flash", None, False)


class Work:
    def __init__(self, *, active=None, result=(11, True), error=None):
        self.active = active
        self.result = result
        self.error = error

    async def find_active(self, key):
        return self.active

    async def schedule(self, **kwargs):
        if self.error:
            raise self.error
        return self.result


class Quota:
    def __init__(self):
        self.reserved = 0
        self.refunded = 0

    async def reserve(self, principal):
        self.reserved += 1

    async def refund(self, user_id):
        self.refunded += 1


class Merger:
    async def merge(self, novel_id, keep_id, drop_id):
        pass


def command_service(work):
    catalog, backend, quota = Catalog(), Backend(), Quota()
    service = CodexCommandService(
        catalog, backend, work, quota, Merger(), agy_max_attempts=3
    )
    return service, catalog, backend, quota


@pytest.mark.asyncio
async def test_build_dedupes_before_backend_resolution_or_quota_reservation():
    service, catalog, backend, quota = command_service(Work(active=ActiveCodexJob(9, "agy", "m")))

    result = await service.schedule_build(1, PRINCIPAL, BuildCodex())

    assert result["job_id"] == 9 and result["deduped"] is True
    assert backend.calls == 0
    assert quota.reserved == 0
    assert catalog.enabled == 0


@pytest.mark.asyncio
async def test_build_refunds_reservation_on_race_and_schedule_failure():
    raced, _, _, raced_quota = command_service(Work(result=(9, False)))
    result = await raced.schedule_build(1, PRINCIPAL, BuildCodex())
    assert result["deduped"] is True
    assert (raced_quota.reserved, raced_quota.refunded) == (1, 1)

    failed, _, _, failed_quota = command_service(Work(error=Conflict("changed")))
    with pytest.raises(Conflict, match="changed"):
        await failed.schedule_build(1, PRINCIPAL, BuildCodex())
    assert (failed_quota.reserved, failed_quota.refunded) == (1, 1)


@pytest.mark.asyncio
async def test_build_range_validation_happens_before_backend_or_quota():
    service, _, backend, quota = command_service(Work())

    with pytest.raises(ValidationFailed, match="less than or equal"):
        await service.schedule_build(
            1, PRINCIPAL, BuildCodex(from_chapter=10, to_chapter=2)
        )

    assert backend.calls == 0
    assert quota.reserved == 0

