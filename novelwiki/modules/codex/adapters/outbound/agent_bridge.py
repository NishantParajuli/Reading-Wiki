from __future__ import annotations

import json

from novelwiki.platform.config import settings
from .ingest.chunk import get_encoder

from ...domain.prompts import (
    WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER,
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
        self, novel_id: int, answer: str, ceiling: ChapterCeiling
    ) -> list[dict]:
        from .agent import build_citations
        return await build_citations(novel_id, answer, ceiling.value)

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
            f"- [Fact {fact['id']}, Ch {fact['chapter']}] "
            f"({fact['fact_type']}): {fact['content']}"
            for fact in profile["facts"]
        ) if profile["facts"] else "No facts recorded."
        rels = "\n".join(
            f"- [Rel {rel['id']}, Ch {rel['chapter']}] "
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
        return await self._runtime.ai.call_chat_completion(
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
    def __init__(self, runtime):
        self._runtime = runtime
