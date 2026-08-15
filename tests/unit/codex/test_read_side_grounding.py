from __future__ import annotations

import contextlib
import json
from types import SimpleNamespace

import pytest

from novelwiki.modules.codex.adapters.outbound import agent
from novelwiki.modules.codex.adapters.outbound.agent_bridge import CodexAgentGateway
from novelwiki.modules.codex.adapters.outbound.grounding import citation_refs, grounding_issues
from novelwiki.modules.codex.adapters.outbound.postgres_queries import PostgresCodexQueries
from novelwiki.modules.codex.public import ChapterCeiling
from novelwiki.platform.config import settings


@pytest.mark.asyncio
async def test_hybrid_search_is_automatically_reranked(monkeypatch):
    calls = {}

    async def fake_hybrid(novel_id, query, ceiling, k, *, runtime):
        calls["hybrid"] = (novel_id, query, ceiling, k, runtime)
        return [{"id": 1, "text": "first"}, {"id": 2, "text": "second"}]

    async def fake_rerank(query, hits, top_n, *, runtime):
        calls["rerank"] = (query, [hit["id"] for hit in hits], top_n, runtime)
        return [hits[1]]

    monkeypatch.setattr(agent, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(agent, "rerank", fake_rerank)
    runtime = object()

    result = json.loads(await agent.execute_tool(
        7, "hybrid_search", {"query": "arrival", "k": 50}, 12,
        runtime=runtime,
    ))

    assert result == [{"id": 2, "text": "second"}]
    assert calls["rerank"] == ("arrival", [1, 2], 2, runtime)


@pytest.mark.asyncio
async def test_hybrid_search_keeps_fused_results_when_reranker_is_down(monkeypatch):
    hits = [{"id": 1, "text": "fallback"}]

    async def fake_hybrid(*args, **kwargs):
        return hits

    async def broken_rerank(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(agent, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(agent, "rerank", broken_rerank)

    result = json.loads(await agent.execute_tool(
        7, "hybrid_search", {"query": "arrival"}, 12, runtime=object()
    ))

    assert result == hits


@pytest.mark.asyncio
async def test_planner_cannot_submit_its_own_rerank_documents(monkeypatch):
    async def unexpected_rerank(*args, **kwargs):
        raise AssertionError("untrusted planner documents reached reranking")

    monkeypatch.setattr(agent, "rerank", unexpected_rerank)

    result = await agent.execute_tool(
        7,
        "rerank",
        {"query": "arrival", "hits": [{"id": 999, "text": "invented"}]},
        12,
        runtime=object(),
    )

    assert "not recognized" in result


def test_grounding_rejects_unretrieved_and_uncited_claims():
    issues = grounding_issues(
        "Supported claim. [Chunk 4, Chapter 2]\n\n"
        "Uncited claim.\n\n"
        "Wrong source. [Fact 99, Chapter 2]",
        {"chunk_ids": [4], "fact_ids": [3]},
        require_each_block=True,
    )

    assert any("fact:99" in issue for issue in issues)
    assert any("2 prose/list block" in issue for issue in issues)


def test_question_cache_namespace_changes_with_contract_or_model(monkeypatch):
    baseline = agent.compute_query_hash("  Who   is RUDEUS? ")
    assert baseline == agent.compute_query_hash("who is rudeus?")

    monkeypatch.setattr(settings, "CODEX_QA_CACHE_VERSION", "next")
    assert agent.compute_query_hash("who is rudeus?") != baseline


class _ScriptedAi:
    def __init__(self, responses):
        self.responses = iter(responses)

    async def call_chat_completion(self, **kwargs):
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.asyncio
async def test_qna_verifier_failure_returns_safe_answer_without_cache(monkeypatch):
    runtime = SimpleNamespace(ai=_ScriptedAi([
        "retrieve the arrival",
        '[{"tool":"hybrid_search","args":{"query":"arrival"}}]',
        "The passage says the hero arrived. [Chunk 4, Chapter 2]",
        "DONE",
        "The hero arrived. [Chunk 4, Chapter 2]",
        RuntimeError("verifier unavailable"),
    ]))

    async def no_cache(*args):
        return None

    async def fake_tool(*args, **kwargs):
        return json.dumps([{"id": 4, "chapter": 2, "text": "The hero arrived."}])

    saved = []

    async def capture_save(*args):
        saved.append(args)

    monkeypatch.setattr(agent, "get_cached_answer", no_cache)
    monkeypatch.setattr(agent, "execute_tool", fake_tool)
    monkeypatch.setattr(agent, "save_cached_answer", capture_save)

    result = await agent.answer_question(
        1, "Who arrived?", 2, runtime=runtime
    )

    assert result["citations"] == []
    assert "couldn't find enough grounded evidence" in result["answer"]
    assert saved == []


@pytest.mark.asyncio
async def test_qna_repairs_unretrieved_citation_before_caching(monkeypatch):
    runtime = SimpleNamespace(ai=_ScriptedAi([
        "retrieve the arrival",
        '[{"tool":"hybrid_search","args":{"query":"arrival"}}]',
        "The passage says the hero arrived. [Chunk 4, Chapter 2]",
        "DONE",
        "The hero arrived. [Chunk 999, Chapter 2]",
        '{"unsupported":false,"flags":[]}',
        "The hero arrived. [Chunk 4, Chapter 2]",
    ]))

    async def no_cache(*args):
        return None

    async def fake_tool(*args, **kwargs):
        return json.dumps([{"id": 4, "chapter": 2, "text": "The hero arrived."}])

    async def fake_citations(novel_id, answer, ceiling, evidence_ids):
        assert "Chunk 999" not in answer
        assert evidence_ids["chunk_ids"] == [4]
        return [{"kind": "chunk", "id": 4, "chapter": 2, "snippet": "arrival"}]

    saved = []

    async def capture_save(*args):
        saved.append(args)

    monkeypatch.setattr(agent, "get_cached_answer", no_cache)
    monkeypatch.setattr(agent, "execute_tool", fake_tool)
    monkeypatch.setattr(agent, "build_citations", fake_citations)
    monkeypatch.setattr(agent, "save_cached_answer", capture_save)

    result = await agent.answer_question(
        1, "Who arrived?", 2, runtime=runtime
    )

    assert result["citations"][0]["id"] == 4
    assert "Chunk 4" in result["answer"]
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_qna_keeps_repaired_answer_with_uncited_interpretive_block(monkeypatch):
    runtime = SimpleNamespace(ai=_ScriptedAi([
        "retrieve the arrival",
        '[{"tool":"hybrid_search","args":{"query":"arrival"}}]',
        "The passage says the hero arrived. [Chunk 4, Chapter 2]",
        "DONE",
        "The hero arrived. [Chunk 4, Chapter 2]\n\nTherefore, the hero seems central so far.",
        json.dumps({
            "unsupported": True,
            "flags": [{
                "sentence": "Therefore, the hero seems central so far.",
                "reason": "Frame this as an interpretation of the cited premise.",
                "action": "modify",
            }],
        }),
        "The hero arrived. [Chunk 4, Chapter 2]\n\n"
        "Based on the available chapters, the hero seems central so far.",
    ]))

    async def no_cache(*args):
        return None

    async def fake_tool(*args, **kwargs):
        return json.dumps([{"id": 4, "chapter": 2, "text": "The hero arrived."}])

    async def fake_citations(novel_id, answer, ceiling, evidence_ids):
        assert citation_refs(answer) == [("chunk", 4)]
        return [{"kind": "chunk", "id": 4, "chapter": 2, "snippet": "arrival"}]

    saved = []

    async def capture_save(*args):
        saved.append(args)

    monkeypatch.setattr(agent, "get_cached_answer", no_cache)
    monkeypatch.setattr(agent, "execute_tool", fake_tool)
    monkeypatch.setattr(agent, "build_citations", fake_citations)
    monkeypatch.setattr(agent, "save_cached_answer", capture_save)

    result = await agent.answer_question(
        1, "Who seems most important?", 2, runtime=runtime
    )

    assert "seems central" in result["answer"]
    assert result["citations"][0]["id"] == 4
    assert len(saved) == 1


@pytest.mark.asyncio
async def test_qna_still_rejects_unretrieved_citation_after_repair(monkeypatch):
    runtime = SimpleNamespace(ai=_ScriptedAi([
        "retrieve the arrival",
        '[{"tool":"hybrid_search","args":{"query":"arrival"}}]',
        "The passage says the hero arrived. [Chunk 4, Chapter 2]",
        "DONE",
        "The hero arrived. [Chunk 999, Chapter 2]",
        '{"unsupported":false,"flags":[]}',
        "The hero arrived. [Chunk 998, Chapter 2]",
    ]))

    async def no_cache(*args):
        return None

    async def fake_tool(*args, **kwargs):
        return json.dumps([{"id": 4, "chapter": 2, "text": "The hero arrived."}])

    saved = []

    async def capture_save(*args):
        saved.append(args)

    monkeypatch.setattr(agent, "get_cached_answer", no_cache)
    monkeypatch.setattr(agent, "execute_tool", fake_tool)
    monkeypatch.setattr(agent, "save_cached_answer", capture_save)

    result = await agent.answer_question(
        1, "Who arrived?", 2, runtime=runtime
    )

    assert result["citations"] == []
    assert "couldn't find enough grounded evidence" in result["answer"]
    assert saved == []


@pytest.mark.asyncio
async def test_profile_synthesis_repairs_unretrieved_citation():
    runtime = SimpleNamespace(ai=_ScriptedAi([
        "# Hero\n\nHero arrived. [Fact 999, Chapter 2]",
        '{"unsupported":false,"flags":[]}',
        "# Hero\n\nHero arrived. [Fact 3, Chapter 2]",
    ]))
    gateway = CodexAgentGateway(runtime)

    rendered = await gateway.synthesize_profile(
        {
            "canonical_name": "Hero",
            "type": "character",
            "aliases": [],
            "facts": [{
                "id": 3, "chapter": 2, "fact_type": "action",
                "content": "Hero arrived.",
            }],
            "current_state": {},
            "relationship_state": [],
            "open_threads": [],
        },
        [],
        ChapterCeiling(2),
        "pro",
    )

    assert "Fact 3" in rendered
    assert "Fact 999" not in rendered


class _ProfileConnection:
    def __init__(self, row):
        self.row = row

    async def fetchrow(self, *args):
        return self.row


class _ProfilePool:
    def __init__(self, row):
        self.connection = _ProfileConnection(row)

    @contextlib.asynccontextmanager
    async def acquire(self):
        yield self.connection


@pytest.mark.asyncio
async def test_profile_cache_requires_current_model_and_contract():
    row = {
        "rendered_md": "current",
        "model": "pro",
        "evidence_ids": {"cache_version": "profiles-v2"},
    }
    queries = PostgresCodexQueries(_ProfilePool(row))

    assert await queries.cached_profile(
        1, 2, ChapterCeiling(3), "pro", "profiles-v2"
    ) == "current"
    assert await queries.cached_profile(
        1, 2, ChapterCeiling(3), "new-pro", "profiles-v2"
    ) is None
    assert await queries.cached_profile(
        1, 2, ChapterCeiling(3), "pro", "profiles-v3"
    ) is None
