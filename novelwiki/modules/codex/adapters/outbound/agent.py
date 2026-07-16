import re
import json
import hashlib
import logging
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.modules.codex.adapters.outbound.retrieval.tools import (
    hybrid_search, rerank, get_chunk, resolve_entity,
    get_entity_profile, get_relationships, get_timeline, list_entities
)
from novelwiki.modules.codex.domain.prompts import (
    PLAN_SYSTEM, DISTILL_SYSTEM, DISTILL_USER,
    SYNTHESIS_SYSTEM, SYNTHESIS_USER, VERIFY_SYSTEM, VERIFY_USER,
    REPAIR_SYSTEM, REPAIR_USER
)
from novelwiki.modules.codex.adapters.outbound.ingest.chunk import get_encoder

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _truncate_tokens(text: str, maximum: int) -> tuple[str, int]:
    encoder = get_encoder()
    tokens = encoder.encode(text or "")
    if len(tokens) <= maximum:
        return text, len(tokens)
    return encoder.decode(tokens[:maximum]) + "\n[truncated at evidence token budget]", maximum

# Matches inline citations in two shapes the models actually produce:
#   keyword-first  → [Chunk 12, Chapter 5] / [Fact 29] / [Event 7, Chapter 3]   (group 1 = kind, 2 = id)
#   chapter-first  → [Ch.1, id 3] / [Chapter 2, id10]                            (group 3 = id, kind defaults to chunk)
# The digests are chunk-keyed (DISTILL cites chunk_id), so a keyword-less `id N` is a chunk ref.
_CITATION_RE = re.compile(
    r"\[(?:(chunk|fact|rel|relationship|event)s?\s+(\d+)|[^\]]*?\bid\s*(\d+))",
    re.IGNORECASE,
)


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    """Clamp a model-supplied numeric arg into [lo, hi], tolerating bad/missing values."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(hi, n))


def _tool_query(args: dict) -> tuple[str | None, str | None]:
    """Normalize and validate a model-supplied tool query.

    Returns (query, error). Long queries are rejected instead of truncated because truncation
    can silently change retrieval meaning while still spending provider work.
    """
    query = (args.get("query") or "").strip()
    if not query:
        return None, "requires a non-empty query."
    if len(query) > settings.ASK_TOOL_MAX_QUERY_CHARS:
        return None, f"query exceeds {settings.ASK_TOOL_MAX_QUERY_CHARS} characters."
    return query, None


async def execute_tool(
    novel_id: int, tool: str, args: dict, chapter_ceiling: float, *, runtime=None
) -> str:
    """Safely dispatches tool calls from the LLM, strictly injecting novel_id + chapter_ceiling.
    Model-supplied fan-out args (`k`, `top_n`, query length, rerank hits) are hard-limited
    so the planner can't be steered into runaway/expensive retrieval."""
    try:
        if tool == "hybrid_search":
            query, err = _tool_query(args)
            if err:
                return f"Error: hybrid_search {err}"
            k = _clamp_int(args.get("k"), settings.RETRIEVE_K, 1, settings.ASK_TOOL_MAX_K)
            import inspect
            if "runtime" in inspect.signature(hybrid_search).parameters:
                if runtime is None:
                    raise RuntimeError("Codex runtime was not supplied")
                res = await hybrid_search(
                    novel_id, query, chapter_ceiling, k, runtime=runtime
                )
            else:
                res = await hybrid_search(novel_id, query, chapter_ceiling, k)
            return json.dumps(res, default=str)

        elif tool == "rerank":
            query, err = _tool_query(args)
            if err:
                return f"Error: rerank {err}"
            hits = args.get("hits", [])
            if not isinstance(hits, list):
                hits = []
            hits = hits[: settings.ASK_TOOL_MAX_RERANK_HITS]
            top_n = _clamp_int(args.get("top_n"), settings.RERANK_TOP_N, 1, settings.ASK_TOOL_MAX_TOP_N)
            import inspect
            if "runtime" in inspect.signature(rerank).parameters:
                if runtime is None:
                    raise RuntimeError("Codex runtime was not supplied")
                res = await rerank(query, hits, top_n, runtime=runtime)
            else:
                res = await rerank(query, hits, top_n)
            return json.dumps(res, default=str)

        elif tool == "get_chunk":
            chunk_id = int(args.get("chunk_id", 0))
            res = await get_chunk(novel_id, chunk_id, chapter_ceiling)
            return json.dumps(res, default=str)

        elif tool == "resolve_entity":
            name = args.get("name", "")
            res = await resolve_entity(novel_id, name, chapter_ceiling)
            return json.dumps(res, default=str)

        elif tool == "get_entity_profile":
            entity_id = int(args.get("entity_id", 0))
            res = await get_entity_profile(novel_id, entity_id, chapter_ceiling)
            return json.dumps(res, default=str)

        elif tool == "get_relationships":
            entity_id = int(args.get("entity_id", 0))
            other_id = args.get("other_id")
            other_id = int(other_id) if other_id is not None else None
            res = await get_relationships(novel_id, entity_id, chapter_ceiling, other_id)
            return json.dumps(res, default=str)

        elif tool == "get_timeline":
            entity_id = int(args.get("entity_id", 0))
            res = await get_timeline(novel_id, entity_id, chapter_ceiling)
            return json.dumps(res, default=str)

        elif tool == "list_entities":
            etype = args.get("type")
            q = args.get("name_query")
            res = await list_entities(novel_id, chapter_ceiling, etype, q)
            return json.dumps(res, default=str)

        else:
            return f"Error: Tool '{tool}' is not recognized."
    except Exception as e:
        logger.error(f"Error executing tool {tool} with args {args}: {e}")
        return f"Error: {e}"


def _accumulate_evidence(tool: str, raw_result: str, evidence: dict):
    """Tracks the provenance ids surfaced by a tool call, for query_cache.evidence_ids."""
    try:
        data = json.loads(raw_result)
    except Exception:
        return
    items = data if isinstance(data, list) else [data]
    for it in items:
        if not isinstance(it, dict):
            continue
        if tool in ("hybrid_search", "get_chunk") and "id" in it:
            evidence["chunk_ids"].add(int(it["id"]))
        elif tool == "get_entity_profile":
            for f in it.get("facts", []) or []:
                if isinstance(f, dict) and "id" in f:
                    evidence["fact_ids"].add(int(f["id"]))
        elif tool == "get_timeline":
            if it.get("type") == "fact" and "id" in it:
                evidence["fact_ids"].add(int(it["id"]))
            elif it.get("type") == "event" and "id" in it:
                evidence["event_ids"].add(int(it["id"]))
        elif tool == "get_relationships" and "id" in it:
            evidence["rel_ids"].add(int(it["id"]))


async def build_citations(novel_id: int, answer: str, chapter_ceiling: float) -> list[dict]:
    """Resolves inline citations in the answer to structured {kind,id,chapter,snippet}.
    Every snippet lookup is bounded by the ceiling, so a citation that points past the
    ceiling is dropped rather than leaked."""
    seen = set()
    refs = []
    for m in _CITATION_RE.finditer(answer or ""):
        kind = (m.group(1) or "chunk").lower()
        if kind == "relationship":
            kind = "rel"
        rid = int(m.group(2) or m.group(3))
        if (kind, rid) not in seen:
            seen.add((kind, rid))
            refs.append((kind, rid))
    if not refs:
        return []

    table_map = {
        "chunk": ("chunks", "text"),
        "fact": ("entity_facts", "content"),
        "rel": ("relationships", "content"),
        "event": ("events", "description"),
    }

    citations = []
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        for kind, rid in refs:
            tbl_col = table_map.get(kind)
            if not tbl_col:
                continue
            table, col = tbl_col
            row = await conn.fetchrow(
                f"SELECT chapter, {col} AS snippet FROM {table} WHERE id = $1 AND chapter <= $2 AND novel_id = $3;",
                rid, chapter_ceiling, novel_id
            )
            if not row:
                continue  # not found, or beyond ceiling -> never surface
            snippet = (row["snippet"] or "")[:200]
            citations.append({
                "kind": kind,
                "id": rid,
                "chapter": float(row["chapter"]),
                "snippet": snippet,
            })
    return citations


def compute_query_hash(question: str) -> str:
    """MD5 of a normalized question for cache keying. Normalization (lowercase + collapse
    all runs of whitespace to a single space) maximizes cache hits so trivially-varied
    phrasings of the same question don't each incur a fresh uncached spend."""
    norm = re.sub(r"\s+", " ", (question or "").strip().lower())
    return hashlib.md5(norm.encode("utf-8")).hexdigest()


async def get_cached_answer(novel_id: int, query_hash: str, ceiling: float):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT answer_md, evidence_ids FROM query_cache WHERE query_hash = $1 AND chapter_ceiling = $2 AND novel_id = $3;",
            query_hash, ceiling, novel_id
        )
        if not row:
            return None
        evidence = row["evidence_ids"]
        if isinstance(evidence, str):
            try:
                evidence = json.loads(evidence)
            except Exception:
                evidence = {}
        return {"answer_md": row["answer_md"], "evidence_ids": evidence or {}}


async def save_cached_answer(novel_id: int, query_hash: str, ceiling: float, answer: str, evidence_ids: dict):
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO query_cache (novel_id, query_hash, chapter_ceiling, answer_md, evidence_ids, created_at)
            VALUES ($1, $2, $3, $4, $5, now())
            ON CONFLICT (novel_id, query_hash, chapter_ceiling) DO UPDATE
            SET answer_md = EXCLUDED.answer_md, evidence_ids = EXCLUDED.evidence_ids, created_at = now();
            """,
            novel_id, query_hash, ceiling, answer, json.dumps(evidence_ids)
        )


def _is_done(decision_clean: str) -> bool:
    return decision_clean.strip().strip('"').strip("'").upper() == "DONE"


async def answer_question(
    novel_id: int, question: str, chapter_ceiling: float, *, runtime
) -> dict:
    """
    Full Pro/Flash agentic orchestrator: Pro plans -> (Flash distills) -> Pro reasons
    -> Pro synthesizes -> Flash verifies -> (Pro repairs) -> grounded, cited answer.

    Returns {"answer": str, "citations": list[dict], "evidence_ids": dict}.
    """
    query_hash = compute_query_hash(question)

    # 0. Cache
    cached = await get_cached_answer(novel_id, query_hash, chapter_ceiling)
    if cached:
        logger.info(f"Returning cached answer for {query_hash} at ceiling {chapter_ceiling}")
        citations = await build_citations(novel_id, cached["answer_md"], chapter_ceiling)
        return {"answer": cached["answer_md"], "citations": citations, "evidence_ids": cached["evidence_ids"]}

    logger.info(f"Agent orchestrator start: '{question}' (ceiling {chapter_ceiling})")

    digests: list[str] = []
    evidence = {"chunk_ids": set(), "fact_ids": set(), "rel_ids": set(), "event_ids": set()}
    evidence_input_tokens = 0
    digest_tokens = 0
    budget_exhausted = False

    # 1. Pro produces an initial plan (subgoals + entities to resolve)
    try:
        plan = await runtime.ai.call_chat_completion(
            model=settings.MODEL_PRO,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
                {"role": "user", "content":
                    f"Question: {question}\n\nBriefly outline the retrieval subgoals and which "
                    f"entities/queries you will need. Then we will execute tools iteratively."},
            ],
            temperature=0.0,
        )
    except Exception as e:
        logger.warning(f"Planning step failed: {e}. Proceeding without an explicit plan.")
        plan = ""

    # 2. Iterative tool loop
    for iteration in range(settings.MAX_ITERATIONS):
        logger.info(f"Orchestrator Iteration {iteration + 1}...")

        decide_prompt = (
            f"Question: {question}\n\n"
            f"Plan:\n{plan or 'No explicit plan.'}\n\n"
            f"Compressed digests gathered so far:\n"
            + ("\n---\n".join(digests) if digests else "None yet.")
            + "\n\nDecide the next tool calls as a JSON array, or output exactly \"DONE\" "
              "if you already have sufficient evidence to answer."
        )

        try:
            decision = await runtime.ai.call_chat_completion(
                model=settings.MODEL_PRO,
                messages=[
                    {"role": "system", "content": PLAN_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
                    {"role": "user", "content": decide_prompt},
                ],
                temperature=0.0,
            )
            decision_clean = decision.strip().replace("```json", "").replace("```", "").strip()

            if _is_done(decision_clean):
                logger.info("Pro concluded: DONE.")
                break

            import json_repair
            try:
                tool_calls = json.loads(decision_clean)
            except Exception as json_err:
                logger.warning(f"Standard JSON decoding failed for planning decisions: {json_err}. Attempting json-repair...")
                tool_calls = json_repair.loads(decision_clean)
            if not isinstance(tool_calls, list):
                logger.warning(f"Unexpected non-list decision: {decision_clean}")
                break
        except Exception as e:
            logger.warning(f"Error deciding next steps: {e}. Proceeding to synthesis.")
            break

        if not tool_calls:
            logger.info("No tool calls planned. Ending loop.")
            break

        # Cap fan-out per iteration so one planner step can't schedule an unbounded batch
        # of tool calls (each of which triggers retrieval + a distill model call). Combined
        # with MAX_ITERATIONS this bounds total tool calls per answer.
        if len(tool_calls) > settings.ASK_MAX_TOOL_CALLS_PER_ITER:
            logger.info(
                f"Planner requested {len(tool_calls)} tool calls; capping to "
                f"{settings.ASK_MAX_TOOL_CALLS_PER_ITER}."
            )
            tool_calls = tool_calls[: settings.ASK_MAX_TOOL_CALLS_PER_ITER]

        for call in tool_calls:
            if not isinstance(call, dict):
                continue
            tool_name = call.get("tool")
            args = call.get("args", {}) or {}
            logger.info(f"Executing Agent Tool: {tool_name} with args {args}")
            raw_result = await execute_tool(
                novel_id, tool_name, args, chapter_ceiling, runtime=runtime
            )

            remaining_evidence = settings.CODEX_ASK_TOTAL_EVIDENCE_TOKENS - evidence_input_tokens
            if remaining_evidence <= 0:
                budget_exhausted = True
                break
            raw_result, used_input = _truncate_tokens(raw_result, remaining_evidence)
            evidence_input_tokens += used_input
            _accumulate_evidence(tool_name, raw_result, evidence)

            distill = await runtime.ai.call_chat_completion(
                model=settings.MODEL_FLASH,
                messages=[
                    {"role": "system", "content": DISTILL_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
                    {"role": "user", "content": DISTILL_USER.format(question=question, passages=raw_result)},
                ],
                temperature=0.0,
            )
            remaining_digest = settings.CODEX_ASK_MAX_DIGEST_TOKENS - digest_tokens
            if remaining_digest <= 0:
                budget_exhausted = True
                break
            digest_entry, used_digest = _truncate_tokens(
                f"Source Tool: {tool_name}({args})\nDigest:\n{distill}", remaining_digest
            )
            digests.append(digest_entry)
            digest_tokens += used_digest
        if budget_exhausted:
            logger.info("Ask retrieval stopped at the configured evidence token budget.")
            break

    # 3. Pro synthesizes from the cited digests
    logger.info("Synthesizing final answer via Pro...")
    digests_str = "\n\n=============\n\n".join(digests) if digests else "No retrieval evidence gathered."

    draft = await runtime.ai.call_chat_completion(
        model=settings.MODEL_PRO,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
            {"role": "user", "content": SYNTHESIS_USER.format(question=question, digests=digests_str)},
        ],
        temperature=0.0,
    )

    # 4. Flash verifies grounding against the SAME cited digests Pro saw
    logger.info("Running grounding verification pass via Flash...")
    try:
        verdict_str = await runtime.ai.call_chat_completion(
            model=settings.MODEL_FLASH,
            messages=[
                {"role": "system", "content": VERIFY_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
                {"role": "user", "content": VERIFY_USER.format(draft=draft, evidence=digests_str)},
            ],
            temperature=0.0,
        )
        verdict_clean = verdict_str.strip().replace("```json", "").replace("```", "").strip()
        import json_repair
        try:
            verdict = json.loads(verdict_clean)
        except Exception as json_err:
            logger.warning(f"Standard JSON decoding failed for verification: {json_err}. Attempting json-repair...")
            verdict = json_repair.loads(verdict_clean)

        if verdict.get("unsupported", False):
            flags = verdict.get("flags", [])
            logger.warning(f"Verification flagged {len(flags)} unsupported/future claim(s); repairing...")
            flags_str = "\n".join(
                f"- {f.get('sentence', '')} (reason: {f.get('reason', '')})" for f in flags
            ) or "(none specified)"
            draft = await runtime.ai.call_chat_completion(
                model=settings.MODEL_PRO,
                messages=[
                    {"role": "system", "content": REPAIR_SYSTEM.format(chapter_ceiling=chapter_ceiling)},
                    {"role": "user", "content": REPAIR_USER.format(
                        question=question, digests=digests_str, flags=flags_str, draft=draft)},
                ],
                temperature=0.0,
            )
            logger.info("Repair pass complete.")
    except Exception as e:
        logger.error(f"Grounding verification error: {e}. Returning unrepaired draft.")

    # 5. Structured citations + evidence, then cache
    citations = await build_citations(novel_id, draft, chapter_ceiling)
    evidence_ids = {k: sorted(v) for k, v in evidence.items()}
    await save_cached_answer(novel_id, query_hash, chapter_ceiling, draft, evidence_ids)

    return {"answer": draft, "citations": citations, "evidence_ids": evidence_ids}
