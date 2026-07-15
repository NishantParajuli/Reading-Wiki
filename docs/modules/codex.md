# Codex module (`novelwiki/modules/codex/`)

**Responsibility:** the opt-in, spoiler-safe knowledge base for a novel: the build
pipeline (chunk → embed → extract → link → index), hybrid retrieval, the agentic **Ask**
Q&A, entity browsing/profiles/timelines/identity reveals, the no-spoiler **recap**, and
the caches that make repeat reads free. Every read is bounded by the server-trusted
chapter ceiling — see [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).
Pipeline walkthrough: [../pipelines/codex-build-and-ask.md](../pipelines/codex-build-and-ask.md).

**Owned tables (11):** `chunks`, `entities`, `entity_descriptions`, `entity_aliases`,
`identity_links`, `entity_facts`, `relationships`, `events`, `extraction_state`,
`wiki_cache`, `query_cache`.
**Owned filesystem root:** `BM25_INDEX_PATH` (`./data/bm25_index/<novel_id>/`).

---

## Public contract (`public.py`)

- **`ChapterCeiling(value: float)`** — the boundary type every capability takes.
- **`CodexTransactionApi` / `CodexArtifacts`** — `has_chapter_artifacts` (guards source
  renumbering) and `invalidate_chapter_range` (import commits clear stale artifacts);
  bound in the `update_source_offset` and `commit_import` workflows.
- **`CodexExtractionTransactionApi`** — the Codex half of the atomic extraction commit
  (`commit_codex_extraction` workflow): writes entities/facts/relationships/events/
  aliases/identity links/descriptions + `extraction_state` against a row-locked,
  hash-verified Reading snapshot.
- **`EstablishedTermsApi`** — canonical `(name, type)` pairs for glossary seeding.
- **`GetCodexMeta`, `Ask`, `ResolveEntity`, `MergeEntities`, `CodexRecapApi`** — the
  query capabilities Experience/others consume.

## Application layer

- **`dto.py::CeilingContext`** — "the server-trusted reading boundary used by every
  spoiler-sensitive use case": effective ceiling + what was requested + whether the
  reader may see the full span (owners/admins can slide up to the last chapter; ordinary
  readers are clamped to `max_chapter_read`).
- **`ports.py`** — the widest port set in the codebase: `CeilingPort`, `CodexQueryPort`
  (all bounded reads + profile cache), `CodexAgentPort` (ask/citations/synthesis),
  `AiCostControlPort` (verified-email/rate/concurrency guards), `CatalogEditPort`,
  `BackendResolutionPort`, `CodexWorkPort`, `CodexQuotaPort`, `EntityMergePort`,
  `CodexReadingPort` (chapter text via Reading), `ResumableAiRunPort`, plus the
  `CodexRuntime` capability bundle for commands/workers.
- **`services.py`**:
  - `CodexQueryService` — every read surface. Order of operations for `ask()`:
    resolve trusted ceiling → normalize/hash question → **cache lookup (free, ungated)**
    → cost gates (verified email, hourly uncached cap, concurrency slot) → agent →
    cache store. `recap()` follows the same trusted ceiling + per-`(novel, ceiling)`
    cache. Entity profiles use `wiki_cache` the same way with LLM synthesis on miss.
  - `CodexCommandService` — `schedule_build` (editable check → backend resolution →
    quota reserve (`codex_builds`) → durable job create/dedupe → refund-on-failure;
    enables `novels.codex_enabled` on first build) and `merge_entities`.
- **`commands.py::CodexCommands`** — the CLI/worker command bundle (chunk/embed/extract/
  rebuild/merge) built by Bootstrap with the runtime injected.

## Build pipeline (outbound `ingest/`)

Stages, each idempotent and range-limitable, run in order by the `codex_build` job
handler (or individually from the CLI):

1. **`chunk.py`** — sentence/paragraph-aware splitting within chapters:
   `CHUNK_TARGET_TOKENS` (500) with `CHUNK_OVERLAP` (80), tokenized with tiktoken; rows
   into `chunks` keyed `(novel_id, chapter, chunk_index)`. Force mode upserts by that
   stable identity, preserving row ids and embeddings for unchanged text; changed text
   clears its embedding and is rejected while a dependent extraction checkpoint exists.
2. **`embed.py`** — batch-embeds every chunk with `embedding IS NULL`
   (`EMBED_MODEL`, `EMBED_DIM`-sized pgvector column; HNSW index when dim ≤ 2000).
3. **`extract.py`** — **forward-only** structured extraction, strictly ascending by
   chapter (the running story-so-far summary from `extraction_state` feeds each next
   chapter, capped at `SUMMARY_INPUT_MAX_CHARS`): Flash reads the chunk-marked chapter +
   known-entity roster → JSON of entities/facts/relationships/events/aliases/reveals
   (json-repair-tolerant parsing, one temperature-bumped re-ask on malformed output);
   optional second verification pass (`EXTRACTION_VERIFY`, on by default) catches missed
   facts and identity reveals; model-supplied provenance chunk ids are validated against
   the chapter's real ids. Commit is atomic + source-hash-guarded via the
   `commit_codex_extraction` workflow.
4. **`link.py`** — entity resolution for every mention: exact → trigram fuzzy
   (`FUZZY_MATCH_THRESHOLD` 0.35 to consider, single candidate ≥ `FUZZY_AUTO_ACCEPT`
   0.6 auto-accepts) → embedding similarity (`SEMANTIC_MATCH_THRESHOLD` 0.85) → LLM
   disambiguation for gray cases → create new entity. `merge_entities` repairs
   duplicates after the fact (re-pointing facts/relationships/aliases/events, folding
   descriptions, clearing caches).
5. **BM25 index** — `retrieval/bm25.py::BM25Manager`: per-novel bm25s index persisted
   under `data/bm25_index/`, staleness-checked against a cheap DB signature, lazily
   loaded, rebuilt by the job/CLI; blocking tokenize/search offloaded to a thread
   (`BM25_THREAD_OFFLOAD`).

## Retrieval & the agent (outbound `retrieval/`, `agent.py`)

- **`tools.py`** — the ceiling-enforced toolset: `hybrid_search` (BM25 ⊕ pgvector dense →
  `reciprocal_rank_fusion` with `RRF_K`=60 over `RETRIEVE_K`=50), `rerank`
  (`RERANK_MODEL`, top `RERANK_TOP_N`=8), `get_chunk` (returns `None` beyond the
  ceiling — hard refusal), `resolve_entity`, `get_entity_profile`, `get_relationships`,
  `get_identity_links`, `get_timeline`, `list_entities`, `get_connected_personas`
  (recursive CTE over revealed identity links, so "Mysterious Swordsman" and the
  protagonist unify only after the reveal chapter is within the ceiling).
- **`agent.py::answer_question`** — the Pro/Flash orchestrator: Pro plans tool calls →
  tools execute (novel_id + ceiling **injected server-side**, never model-supplied;
  every model-chosen arg clamped by the `ASK_TOOL_MAX_*` settings) → Flash distills
  evidence → Pro reasons; loops up to `MAX_ITERATIONS` (5) with
  `ASK_MAX_TOOL_CALLS_PER_ITER` (4). Answers carry inline citations resolved to
  structured `{kind, id, chapter, snippet}` (`build_citations`); evidence provenance and
  the answer are cached in `query_cache` keyed `(novel_id, md5(normalized question),
  ceiling)`.
- **`agent_bridge.py::CodexAgentGateway`** — the `CodexAgentPort` implementation
  ("retains the established orchestration/cache byte contract").

## Other adapters

- **Inbound `http.py`** (all under `/api`, auth required): meta, stats, entities list,
  entity resolve/profile/relationships/timeline/identities, `POST …/ask`,
  `POST …/codex/build`, `POST …/merge-entities`. (`POST …/recap` is mounted by
  Experience's product router but executes `CodexRecapApi` — recap execution is
  Codex-owned.)
- **Inbound `cli.py`**: `chunk`, `embed`, `extract`, `rebuild-bm25`, `merge`.
- **Inbound `jobs.py`**: `execute_codex_job` (API backend) and `execute_agy_codex_job`.
  For the AGY executor, attempt 1 performs chunk/embed/extract/index; retries reuse
  preprocessing and resume at extraction so already-purchased chunk embeddings are not
  bought again.
- **Outbound `postgres_queries.py`** — all bounded read SQL (`WHERE … <= ceiling` on
  every statement) + `wiki_cache` read/write + `PostgresEntityMerger`.
- **Outbound `agy.py`** — the AGY extraction job: one per-chapter `task.md` bundle
  (chunks, roster, prior summary, exact output shape) plus sealed workspace manifests,
  strict output validation (`validate_extraction_output` — schema, chunk-id provenance,
  ceiling-safe content), separate verification/disambiguation child runs,
  `_resume_ready_commits` after worker loss, plus same-job chapter checkpoint skipping on
  whole-job retry.
- **Outbound `artifacts.py` / `cache.py` / `postgres_terms.py`** — workflow capability,
  cache invalidation, established terms.

## Collaboration notes

- Chapter text always arrives through `CodexReadingPort` / the workflow's row-locked
  snapshot — Codex never reads `chapters` directly.
- Builds are durable Work jobs (`kind='codex_build'`, quota kind `codex_builds`,
  default 20/month); Ask/profile-synthesis are *read-side* spends guarded by
  AI Execution's cost controls instead of monthly quota.
- Caches (`wiki_cache`, `query_cache`) are keyed by ceiling — a reader advancing
  chapters naturally repopulates; extraction/merges clear affected ranges.
