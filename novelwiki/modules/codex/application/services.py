from __future__ import annotations

from novelwiki.kernel.errors import NotFound, ValidationFailed
from novelwiki.modules.identity.public import Principal

from .dto import BuildCodex
from .ports import (
    AiCostControlPort, BackendResolutionPort, CatalogEditPort, CeilingPort,
    CodexAgentPort, CodexQueryPort, CodexQuotaPort, CodexWorkPort,
    EntityMergePort,
)


class CodexQueryService:
    def __init__(
        self, ceiling: CeilingPort, queries: CodexQueryPort,
        agent: CodexAgentPort, costs: AiCostControlPort, *,
        ask_max_query_chars: int, ask_requires_verified: bool,
        profile_requires_verified: bool, profile_model: str,
    ):
        self._ceiling = ceiling
        self._queries = queries
        self._agent = agent
        self._costs = costs
        self._ask_max_query_chars = ask_max_query_chars
        self._ask_requires_verified = ask_requires_verified
        self._profile_requires_verified = profile_requires_verified
        self._profile_model = profile_model

    async def meta(self, novel_id: int, principal: Principal) -> dict:
        boundary = await self._ceiling.resolve(novel_id, principal, None)
        return {
            "novel_title": boundary.novel_title,
            "novel_blurb": boundary.novel_blurb,
            "count": boundary.chapter_count,
            "min_chapter": boundary.min_chapter,
            "max_chapter": boundary.max_chapter,
            "allowed_ceiling": boundary.allowed_ceiling,
            "effective_ceiling": boundary.ceiling.value,
        }

    async def stats(self, novel_id: int, requested: float, principal: Principal) -> dict:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        result = await self._queries.stats(novel_id, boundary.ceiling)
        max_f = float(boundary.max_chapter) if boundary.max_chapter is not None else None
        pct = 0
        if max_f and max_f > 0:
            pct = round(min(100.0, (boundary.ceiling.value / max_f) * 100))
        return {
            "ceiling": boundary.ceiling.value,
            "requested_ceiling": boundary.requested_ceiling,
            "allowed_ceiling": boundary.allowed_ceiling,
            "effective_ceiling": boundary.ceiling.value,
            "ceiling_clamped": boundary.clamped,
            **result,
            "pct_read": pct,
            "max_chapter": max_f,
            "ceiling_chapter": boundary.ceiling_chapter,
            "ceiling_title": boundary.ceiling_title,
        }

    async def list_entities(
        self, novel_id: int, requested: float, principal: Principal,
        entity_type: str | None = None, name_query: str | None = None,
    ) -> list[dict]:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        return await self._queries.list_entities(
            novel_id, boundary.ceiling, entity_type, name_query
        )

    async def resolve_entity(
        self, novel_id: int, name: str, requested: float, principal: Principal
    ) -> list[dict]:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        return await self._queries.resolve_entity(novel_id, name, boundary.ceiling)

    async def relationships(
        self, novel_id: int, entity_id: int, requested: float,
        principal: Principal, other_id: int | None = None,
    ) -> list[dict]:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        return await self._queries.relationships(
            novel_id, entity_id, boundary.ceiling, other_id
        )

    async def timeline(
        self, novel_id: int, entity_id: int, requested: float, principal: Principal
    ) -> list[dict]:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        return await self._queries.timeline(novel_id, entity_id, boundary.ceiling)

    async def identities(
        self, novel_id: int, entity_id: int, requested: float, principal: Principal
    ) -> list[dict]:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        return await self._queries.identities(novel_id, entity_id, boundary.ceiling)

    async def entity_profile(
        self, novel_id: int, entity_id: int, requested: float, principal: Principal
    ) -> dict:
        boundary = await self._ceiling.resolve(novel_id, principal, requested)
        cached = await self._queries.cached_profile(novel_id, entity_id, boundary.ceiling)
        profile = await self._queries.entity_profile(novel_id, entity_id, boundary.ceiling)
        if profile is None:
            raise NotFound("Entity not found or not yet visible.")
        if cached is not None:
            profile["rendered_md"] = cached
            return profile

        if self._profile_requires_verified:
            self._costs.require_spend_allowed(principal)
        async with self._costs.concurrency_slot(principal, "profile"):
            await self._costs.consume_rate(principal, "profile")
            relationships = await self._queries.relationships(
                novel_id, entity_id, boundary.ceiling
            )
            rendered = await self._agent.synthesize_profile(
                profile, relationships, boundary.ceiling, self._profile_model
            )
            evidence = {
                "fact_ids": [fact["id"] for fact in profile["facts"]],
                "rel_ids": [rel["id"] for rel in relationships],
            }
            await self._queries.save_profile(
                novel_id, entity_id, boundary.ceiling, rendered,
                self._profile_model, evidence,
            )
        profile["rendered_md"] = rendered
        return profile

    async def ask(
        self, novel_id: int, question: str, requested: float, principal: Principal
    ) -> dict:
        # Preserve the provider-free validation order from the legacy endpoint.
        question = (question or "").strip()
        if not question:
            raise ValidationFailed("Question can't be empty.")
        if len(question) > self._ask_max_query_chars:
            raise ValidationFailed(
                f"Question is too long (max {self._ask_max_query_chars} characters)."
            )
        boundary = await self._ceiling.resolve(novel_id, principal, requested)

        def response(result: dict) -> dict:
            return {
                **result,
                "requested_ceiling": boundary.requested_ceiling,
                "allowed_ceiling": boundary.allowed_ceiling,
                "effective_ceiling": boundary.ceiling.value,
                "ceiling_clamped": boundary.clamped,
            }

        query_hash = self._agent.query_hash(question)
        cached = await self._agent.cached_answer(
            novel_id, query_hash, boundary.ceiling
        )
        if cached:
            citations = await self._agent.citations(
                novel_id, cached["answer_md"], boundary.ceiling
            )
            return response({
                "answer": cached["answer_md"], "citations": citations,
                "evidence_ids": cached["evidence_ids"],
            })

        if self._ask_requires_verified:
            self._costs.require_spend_allowed(principal)
        async with self._costs.concurrency_slot(principal, "ask"):
            await self._costs.consume_rate(principal, "ask")
            await self._agent.ensure_index(novel_id)
            result = await self._agent.answer(
                novel_id, question, boundary.ceiling
            )
        return response(result)


class CodexCommandService:
    def __init__(
        self, catalog: CatalogEditPort, backend: BackendResolutionPort,
        work: CodexWorkPort, quota: CodexQuotaPort, merger: EntityMergePort,
        agy_max_attempts: int,
    ):
        self._catalog = catalog
        self._backend = backend
        self._work = work
        self._quota = quota
        self._merger = merger
        self._agy_max_attempts = agy_max_attempts

    async def schedule_build(
        self, novel_id: int, principal: Principal, command: BuildCodex
    ) -> dict:
        await self._catalog.require_editable(novel_id, principal)
        if (
            command.from_chapter is not None and command.to_chapter is not None
            and command.from_chapter > command.to_chapter
        ):
            raise ValidationFailed(
                "from_chapter must be less than or equal to to_chapter."
            )
        idem = (
            f"codex:novel{novel_id}:{command.from_chapter}:"
            f"{command.to_chapter}:{int(command.force)}"
        )
        existing = await self._work.find_active(idem)
        if existing is not None:
            return {
                "status": "success",
                "message": "A codex build for this range is already running.",
                "job_id": existing.job_id, "deduped": True,
                "execution_backend": existing.execution_backend,
                "model": existing.model, "backend_reason": "already_active",
            }
        decision = await self._backend.resolve(principal, command.ai_backend)
        from novelwiki.workflows.schedule_ai_job import schedule_ai_job

        async def schedule():
            return await self._work.schedule(
                novel_id=novel_id, user_id=principal.user_id,
                options={
                    "force": command.force,
                    "from_chapter": command.from_chapter,
                    "to_chapter": command.to_chapter,
                },
                idempotency_key=idem, decision=decision,
                max_attempts=(
                    self._agy_max_attempts if decision.resolved == "agy" else None
                ),
            )

        async def refund():
            await self._quota.refund(principal.user_id)

        job_id, created = await schedule_ai_job(
            lambda: self._quota.reserve(principal), schedule, refund,
            lambda: self._catalog.enable_codex(novel_id),
        )
        return {
            "status": "success",
            "message": (
                "Codex build scheduled." if created
                else "A codex build for this range is already running."
            ),
            "job_id": job_id, "deduped": not created,
            "execution_backend": decision.resolved, "model": decision.model,
            "backend_reason": decision.reason,
        }

    async def merge_entities(
        self, novel_id: int, keep_id: int, drop_id: int, principal: Principal
    ) -> dict:
        await self._catalog.require_editable(novel_id, principal)
        await self._merger.merge(novel_id, keep_id, drop_id)
        return {
            "status": "success",
            "message": f"Entity {drop_id} merged into {keep_id}.",
        }


class CodexMigrationService:
    """Composition-facing facade for the native Codex HTTP adapter."""

    def __init__(self, queries: CodexQueryService, commands: CodexCommandService):
        self.queries = queries
        self.commands = commands
