from __future__ import annotations

import json

from novelwiki.platform.config import settings
from .ingest.chunk import get_encoder
from .grounding import evidence_refs, grounding_issues

from ...domain.prompts import (
    WIKI_PROFILE_REPAIR_SYSTEM, WIKI_PROFILE_REPAIR_USER,
    WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER,
    WIKI_PROFILE_VERIFY_SYSTEM, WIKI_PROFILE_VERIFY_USER,
)
from ...public import ChapterCeiling


class CodexAgentGateway:
    """Adapter retaining the established orchestration/cache byte contract."""

    def query_hash(self, question: str) -> str:
        from .agent import compute_query_hash
        return compute_query_hash(question)

    async def cached_answer(
        self, novel_id: int, query_hash: str, ceiling: ChapterCeiling
    ) -> dict | None:
        from .agent import get_cached_answer
        return await get_cached_answer(novel_id, query_hash, ceiling.value)

    async def citations(
        self, novel_id: int, answer: str, ceiling: ChapterCeiling,
        evidence_ids: dict | None = None,
    ) -> list[dict]:
        from .agent import build_citations
        return await build_citations(
            novel_id, answer, ceiling.value, evidence_ids
        )

    async def answer(
        self, novel_id: int, question: str, ceiling: ChapterCeiling
    ) -> dict:
        from .agent import answer_question
        return await answer_question(
            novel_id, question, ceiling.value, runtime=self._runtime
        )

    async def ensure_index(self, novel_id: int) -> None:
        from .retrieval.bm25 import get_bm25_manager
        await get_bm25_manager(novel_id).ensure_loaded()

    async def synthesize_profile(
        self, profile: dict, relationships: list[dict], ceiling: ChapterCeiling,
        model: str,
    ) -> str:
        aliases = ", ".join(profile["aliases"]) if profile["aliases"] else "None"
        facts = "\n".join(
            f"- [Fact {fact['id']}, Chapter {fact['chapter']}] "
            f"({fact['fact_type']}): {fact['content']}"
            for fact in profile["facts"]
        ) if profile["facts"] else "No facts recorded."
        rels = "\n".join(
            f"- [Rel {rel['id']}, Chapter {rel['chapter']}] "
            f"{rel['source_name']} ({rel['relation_type']}) "
            f"{rel['target_name']}: {rel['content'] or ''}"
            for rel in relationships
        ) if relationships else "No relationships recorded."
        state = json.dumps(profile.get("current_state") or {}, ensure_ascii=False)
        relationship_state = json.dumps(
            profile.get("relationship_state") or [], ensure_ascii=False, default=str
        )
        threads = json.dumps(profile.get("open_threads") or [], ensure_ascii=False, default=str)
        system_prompt = WIKI_PROFILE_SYNTHESIS_SYSTEM.format(
            chapter_ceiling=ceiling.value
        )
        user_prompt = WIKI_PROFILE_SYNTHESIS_USER.format(
            canonical_name=profile["canonical_name"],
            type=profile["type"], chapter_ceiling=ceiling.value,
            aliases=aliases, facts=facts, relationships=rels,
            current_state=state, relationship_state=relationship_state,
            open_threads=threads,
        )
        encoder = get_encoder()
        system_tokens = len(encoder.encode(system_prompt))
        maximum_user_tokens = max(1, settings.CODEX_CONTEXT_MAX_TOKENS - system_tokens)
        user_tokens = encoder.encode(user_prompt)
        if len(user_tokens) > maximum_user_tokens:
            user_prompt = encoder.decode(user_tokens[:maximum_user_tokens]) + "\n[bounded profile input]"
        evidence_ids = {
            "fact_ids": [fact["id"] for fact in profile.get("facts") or []],
            "rel_ids": [rel["id"] for rel in relationships],
            "event_ids": [],
            "chunk_ids": sorted(self._source_chunk_ids(profile)),
        }
        if not evidence_refs(evidence_ids):
            return (
                f"# {profile['canonical_name']}\n\n"
                "No grounded profile details are available at this chapter yet."
            )

        draft = await self._runtime.ai.call_chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            temperature=0.0,
        )

        verify_system = WIKI_PROFILE_VERIFY_SYSTEM.format(
            chapter_ceiling=ceiling.value
        )
        verify_shell = WIKI_PROFILE_VERIFY_USER.format(
            evidence="", draft=draft
        )
        maximum_verify_evidence_tokens = max(
            1,
            settings.CODEX_CONTEXT_MAX_TOKENS
            - len(encoder.encode(verify_system))
            - len(encoder.encode(verify_shell)),
        )
        verify_evidence_tokens = encoder.encode(user_prompt)
        if len(verify_evidence_tokens) > maximum_verify_evidence_tokens:
            verification_evidence = (
                encoder.decode(
                    verify_evidence_tokens[:maximum_verify_evidence_tokens]
                )
                + "\n[bounded profile evidence]"
            )
        else:
            verification_evidence = user_prompt
        verify_user = WIKI_PROFILE_VERIFY_USER.format(
            evidence=verification_evidence, draft=draft
        )

        verdict_raw = await self._runtime.ai.call_chat_completion(
            model=settings.MODEL_FLASH,
            messages=[
                {"role": "system", "content": verify_system},
                {"role": "user", "content": verify_user},
            ],
            temperature=0.0,
        )
        verdict_clean = verdict_raw.strip().replace("```json", "").replace("```", "").strip()
        import json_repair
        try:
            verdict = json.loads(verdict_clean)
        except Exception:
            verdict = json_repair.loads(verdict_clean)
        if not isinstance(verdict, dict):
            raise RuntimeError("Profile grounding verification returned an invalid result.")

        flags = []
        raw_flags = verdict.get("flags", [])
        if isinstance(raw_flags, list):
            flags.extend(flag for flag in raw_flags if isinstance(flag, dict))
        if verdict.get("unsupported") and not flags:
            flags.append({
                "sentence": "Profile draft",
                "reason": "The profile verifier marked the draft unsupported.",
            })
        flags.extend(
            {"sentence": "Machine grounding check", "reason": issue}
            for issue in grounding_issues(
                draft, evidence_ids, require_each_block=False
            )
        )

        if flags:
            flags_text = "\n".join(
                f"- {flag.get('sentence', '')} (reason: {flag.get('reason', '')})"
                for flag in flags
            )
            repair_system = WIKI_PROFILE_REPAIR_SYSTEM.format(
                chapter_ceiling=ceiling.value
            )
            repair_shell = WIKI_PROFILE_REPAIR_USER.format(
                evidence="", flags=flags_text, draft=draft
            )
            maximum_repair_evidence_tokens = max(
                1,
                settings.CODEX_CONTEXT_MAX_TOKENS
                - len(encoder.encode(repair_system))
                - len(encoder.encode(repair_shell)),
            )
            repair_evidence_tokens = encoder.encode(user_prompt)
            repair_evidence = (
                encoder.decode(
                    repair_evidence_tokens[:maximum_repair_evidence_tokens]
                )
                + "\n[bounded profile evidence]"
                if len(repair_evidence_tokens) > maximum_repair_evidence_tokens
                else user_prompt
            )
            draft = await self._runtime.ai.call_chat_completion(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": repair_system,
                    },
                    {
                        "role": "user",
                        "content": WIKI_PROFILE_REPAIR_USER.format(
                            evidence=repair_evidence,
                            flags=flags_text,
                            draft=draft,
                        ),
                    },
                ],
                temperature=0.0,
            )

        final_issues = grounding_issues(
            draft, evidence_ids, require_each_block=False
        )
        if final_issues:
            raise RuntimeError("Profile grounding validation failed after repair.")
        return draft

    @staticmethod
    def _source_chunk_ids(value) -> set[int]:
        chunk_ids: set[int] = set()
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "source_chunk_ids" and isinstance(child, list):
                    for chunk_id in child:
                        try:
                            chunk_ids.add(int(chunk_id))
                        except (TypeError, ValueError):
                            continue
                else:
                    chunk_ids.update(CodexAgentGateway._source_chunk_ids(child))
        elif isinstance(value, list):
            for child in value:
                chunk_ids.update(CodexAgentGateway._source_chunk_ids(child))
        return chunk_ids

    def __init__(self, runtime):
        self._runtime = runtime
