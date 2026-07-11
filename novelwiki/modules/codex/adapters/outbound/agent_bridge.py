from __future__ import annotations

from ...domain.prompts import (
    WIKI_PROFILE_SYNTHESIS_SYSTEM, WIKI_PROFILE_SYNTHESIS_USER,
)
from ...public import ChapterCeiling


class LegacyCodexAgentBridge:
    """Compatibility bridge retaining the established orchestration/cache byte contract."""

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
        return await answer_question(novel_id, question, ceiling.value)

    async def ensure_index(self, novel_id: int) -> None:
        from .retrieval.bm25 import get_bm25_manager
        await get_bm25_manager(novel_id).ensure_loaded()

    async def synthesize_profile(
        self, profile: dict, relationships: list[dict], ceiling: ChapterCeiling,
        model: str,
    ) -> str:
        from novelwiki.agent.llm_client import call_chat_completion

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
        return await call_chat_completion(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": WIKI_PROFILE_SYNTHESIS_SYSTEM.format(
                        chapter_ceiling=ceiling.value
                    ),
                },
                {
                    "role": "user",
                    "content": WIKI_PROFILE_SYNTHESIS_USER.format(
                        canonical_name=profile["canonical_name"],
                        type=profile["type"], chapter_ceiling=ceiling.value,
                        aliases=aliases, facts=facts, relationships=rels,
                    ),
                },
            ],
            temperature=0.0,
        )

