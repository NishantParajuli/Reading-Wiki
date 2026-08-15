# Codex module (`novelwiki/modules/codex/`)

**Responsibility:** the opt-in, spoiler-safe knowledge base for a novel: the build
pipeline (chunk → embed → extract → link → index), hybrid retrieval, the agentic **Ask**
Q&A, entity browsing/profiles/timelines/identity reveals, the no-spoiler **recap**, and
the caches that make repeat reads free. Every read is bounded by the server-trusted
chapter ceiling — see [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).
Pipeline walkthrough: [../pipelines/codex-build-and-ask.md](../pipelines/codex-build-and-ask.md).

**Owned tables (19):** `chunks`, `entities`, `entity_descriptions`, `entity_aliases`,
`identity_links`, `entity_facts`, `relationships`, `events`, `chapter_summaries`,
`memory_segments`, `entity_activity`, `entity_state_transitions`,
`relationship_state_transitions`, `plot_threads`, `plot_thread_updates`,
`extraction_contexts`, `extraction_state`, `wiki_cache`, `query_cache`.
**Owned filesystem root:** `BM25_INDEX_PATH` (`./data/bm25_index/<novel_id>/`).

---

## Public contract (`public.py`)

- **`ChapterCeiling(value: float)`** — the boundary type every capability takes.
- **`CodexTransactionApi` / `CodexArtifacts`** — `has_chapter_artifacts` (guards source
  renumbering) and `invalidate_chapter_range` (import commits clear stale artifacts);
  bound in the `update_source_offset` and `commit_import` workflows.
- **`CodexExtractionTransactionApi`** — the Codex half of the atomic extraction commit
  (`commit_codex_extraction` workflow): writes entities/facts/relationships/events/
  aliases/identity links/descriptions, activity, temporal state, threads, hierarchical
  memory, context manifest, and `extraction_state` against a row-locked, source/context-
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
    cache. Entity profiles use `wiki_cache` with Pro synthesis, independent Flash
    verification, conditional Pro repair, and fail-closed machine citation validation on miss.
  - `CodexCommandService` — `schedule_build` (editable check → backend resolution →
    quota reserve (`codex_builds`) → durable job create/dedupe → refund-on-failure;
    enables `novels.codex_enabled` on first build) and `merge_entities`.
- **`commands.py::CodexCommands`** — the CLI/worker command bundle (chunk/embed/extract/
  rebuild/merge/reset) built by Bootstrap with the runtime injected.

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
3. **`context.py` + `extract.py`** — **forward-only** v2.1 extraction, strictly ascending.
   The shared direct/AGY context builder scores exact names/aliases, recent activity,
   unresolved threads, graph neighbors, trigram spans, and exact vector matches; packs at
   all literal current-chapter entities (hard cap 120) plus at most 20 background entities,
   current state, three recent summaries, completed memory, and ten threads under hard
   section/total token limits; and emits a reproducible context hash. The backend returns
   strict, provenance-required entities/facts/relationships/events/aliases/reveals plus state
   transitions, topic-grounded thread updates, and distributed-coverage reducer targets. Host
   validation rejects generic or determiner-led descriptive entities, wrong subject attachment,
   nonlocal citations, internal refs, stale thread drift, undersized/meta summaries, and
   endpoint-only memory. Plot-thread relevance tokenization indexes hyphenated compounds as both
   the full compound and its component words, strips possessive suffixes, and folds explicit
   negative forms such as “no longer” and “wasn't … anymore” into one polarity token. Citation
   locality instead preserves exact normalized word order after Unicode, case, apostrophe, and
   punctuation normalization; it does not apply those thread-topic variants. Same-chapter proposed
   aliases are valid subject terms for attachment checks. Concept and item attachment checks accept
   a conservative mechanically derived regular plural (`Stone Treant` / `Stone Treants`), but never
   fuzzy or stem matches.
   Organization/category terms accept the equally bounded possessive-number variant
   (`Adventurer's Guild` / `Adventurers' Guild`) and normalized apostrophe typography.
   A separate verifier may lose one residual misaligned claim without losing the chapter; broad
   claim/ref misalignment still retries. Canonical-name aliases are omitted, extracted aliases are
   case-insensitively deduplicated, and a same-chapter introduced/revealed identity must be an alias
   rather than a second entity. Commit
   takes a per-novel advisory lock and verifies both source and freshly recomputed context
   hashes before the entire chapter artifact set lands atomically.
4. **`link.py`** — entity resolution for every mention: exact → trigram fuzzy
   (`FUZZY_MATCH_THRESHOLD` 0.35 to consider, single candidate ≥ `FUZZY_AUTO_ACCEPT`
   0.6 auto-accepts) → embedding similarity (`SEMANTIC_MATCH_THRESHOLD` 0.85) → LLM
   disambiguation for gray cases → create new entity. `merge_entities` repairs
   duplicates after the fact (re-pointing historical and temporal references, aggregating
   activity, folding descriptions/aliases/identity links, preserving the dropped canonical
   name as an alias at its original reveal ceiling, and clearing caches).
5. **BM25 index** — `retrieval/bm25.py::BM25Manager`: per-novel bm25s index persisted
   under `data/bm25_index/`, staleness-checked against a cheap DB signature, lazily
   loaded, rebuilt by the job/CLI; blocking tokenize/search offloaded to a thread
   (`BM25_THREAD_OFFLOAD`). Reader ceilings use bounded cached prefix indexes so future
   documents are absent from both results and IDF.

## Retrieval & the agent (outbound `retrieval/`, `agent.py`)

- **`tools.py`** — the ceiling-enforced toolset: `hybrid_search` (BM25 ⊕ pgvector dense →
  `reciprocal_rank_fusion` with `RRF_K`=60 over `RETRIEVE_K`=50 and a 40% per-source
  candidate reservation so dense-only evidence reaches automatic `RERANK_MODEL`
  reranking, top `RERANK_TOP_N`=8, with fused-result fallback), `get_chunk` (returns `None` beyond the
  ceiling — hard refusal), `resolve_entity`, `get_entity_profile`, `get_relationships`,
  `get_identity_links`, `get_timeline`, `list_entities`, `get_connected_personas`
  (recursive CTE over revealed identity links, so "Mysterious Swordsman" and the
  protagonist unify only after the reveal chapter is within the ceiling).
- **`agent.py::answer_question`** — the Pro/Flash orchestrator: Pro plans tool calls →
  tools execute (novel_id + ceiling **injected server-side**, never model-supplied;
  every model-chosen arg clamped by the `ASK_TOOL_MAX_*` settings) → Flash distills
  evidence → Pro reasons; loops up to `MAX_ITERATIONS` (5) with
  `ASK_MAX_TOOL_CALLS_PER_ITER` (4), a total raw-evidence token budget, and a separate
  digest budget. Structured tools also enforce SQL row ceilings. Flash verifies the draft,
  Pro repairs findings, allowing faithful paraphrases and explicitly framed interpretations
  of cited premises. Deterministic checks reject citations outside the request's retrieved
  evidence, answers with no request-grounded citation, or citations that do not resolve in the
  ceiling-bounded database; they do not reject the entire answer solely because a Markdown block
  does not repeat a citation. Verification/repair failures and hard citation failures return a
  fixed safe answer without caching. Valid answers carry structured
  `{kind, id, chapter, snippet}` citations and are cached in `query_cache` under a model- and
  `CODEX_QA_CACHE_VERSION`-namespaced question hash.
- **Long read transport** — Ask and entity-profile endpoints retain ordinary JSON responses for
  compatible clients and negotiate `application/x-ndjson` for the SPA. Streamed responses send
  an immediate start frame and 15-second heartbeats until the result, preventing proxy read
  timeouts; disconnecting cancels the request-owned task.
- **`agent_bridge.py::CodexAgentGateway`** — the `CodexAgentPort` implementation
  ("retains the established orchestration/cache byte contract").

## Other adapters

- **Inbound `http.py`** (all under `/api`, auth required): meta, stats, entities list,
  entity resolve/profile/relationships/timeline/identities, `POST …/ask`,
  `POST …/codex/build`, `POST …/merge-entities`. (`POST …/recap` is mounted by
  Experience's product router but executes `CodexRecapApi` — recap execution is
  Codex-owned.)
- **Inbound `cli.py`**: `chunk`, `embed`, `extract`, `rebuild-bm25`, `merge`,
  `reset-codex` (derived structured data only; chunks/embeddings remain).
- **Inbound `jobs.py`**: `execute_codex_job` (API backend) and `execute_agy_codex_job`.
  The AGY executor repeats idempotent chunking and missing-embedding passes on retries,
  then resumes extraction; unchanged vectors are retained, while interrupted preprocessing
  is completed before extraction requires its chunks.
- **Outbound `postgres_queries.py`** — all bounded read SQL (`WHERE … <= ceiling` on
  every statement) + `wiki_cache` read/write + `PostgresEntityMerger`.
- **Outbound `agy.py`** — the AGY extraction job: one per-chapter `task.md` bundle
  (chunks, bounded memory, exact artifact-schema 2.2 output shape) plus sealed workspace manifests,
  strict output validation (`validate_extraction_output` — schema, refs, exact reducer
  targets/coverage beats, summary token/notation limits, literal named mention spans,
  claim-subject alignment (including only unambiguous, non-generic leading-name shorthand for
  character refs with trusted type metadata), literal evidence-anchor locality, and chunk provenance),
  required self-review inside the primary run, an optional separate verification child when
  `AGY_SEPARATE_CODEX_VERIFY=true`, one batched disambiguation child for ambiguous
  mentions with exact case coverage and supplied-candidate validation in both the stop hook
  and host, conservative `NEW` fallback if that child still fails, `_resume_ready_commits`
  after worker loss, and same-job chapter checkpoint skipping on whole-job retry. Draft
  JSON is compacted without removing fields, and verification has a 64k input ceiling distinct
  from primary extraction's 48k ceiling so long chapters can carry the complete proposal.
  A remaining overflow is classified as `codex_context_budget_exceeded`. Draft
  anchor failures become targeted verifier instructions; isolated final failures are
  quarantined, while broad failure retries the chapter. Before that quarantine, a verifier-only
  bounded canonicalizer restores nearby omitted source words or relocates an exact anchor to the
  supplied overlapping chunk that contains it. Evidence anchors remain contiguous exact
  boundary-aware source-word sequences, so punctuation and quote typography do not create false
  failures but changed/reordered words and distant stitching still do. Progress reports the actual source
  chapter and overall committed position rather than a retry-local index.
  First-pass claim-alignment findings are also supplied to an enabled independent verifier as
  targeted repair instructions; final verifier artifacts remain subject to the strict alignment gate.
  First-pass duplicate updates for one plot-thread ref follow the same verifier route. The final
  artifact still permits one update per ref and chapter; one isolated leftover duplicate is
  quarantined, while multiple leftovers retry instead of hiding broad thread loss.
  First-pass lexical thread-topic misses also reach verification so aliases, personas, nicknames,
  and paraphrases can be judged semantically. One verifier-retained miss requires strong trusted
  participant continuity; multiple misses or weak continuity retry, and dormant-thread reopening
  remains an unconditional host rule. The transaction-bound writer reapplies that exact policy only
  when the caller proves the artifact came from `codex_verify`.
  Trusted alignment terms include unambiguous geopolitical word-order inversions without creating
  or persisting a new alias.
- **Outbound `artifacts.py` / `cache.py` / `maintenance.py` / `postgres_terms.py`** —
  workflow capability, suffix-aware invalidation, structured reset/orphan pruning,
  established terms.

## Collaboration notes

- Chapter text always arrives through `CodexReadingPort` / the workflow's row-locked
  snapshot — Codex never reads `chapters` directly.
- Builds are durable Work jobs (`kind='codex_build'`, quota kind `codex_builds`,
  default 20/month); Ask/profile-synthesis are *read-side* spends guarded by
  AI Execution's cost controls instead of monthly quota.
- Caches (`wiki_cache`, `query_cache`) are keyed by ceiling — a reader advancing
  chapters naturally repopulates; extraction/merges clear affected ranges. Ask hashes include
  `CODEX_QA_CACHE_VERSION` plus both read-side model ids; profile hits require the stored model
  and `CODEX_PROFILE_CACHE_VERSION`, so prompt/model contract upgrades miss old prose safely.
- `CODEX_PIPELINE_VERSION` isolates generated v2.1 rows. Older checkpoints are not
  considered complete by a v2.1 build; the quality rebuild starts at the first narrative
  chapter so every entity/thread/state/memory artifact shares the new contract.
