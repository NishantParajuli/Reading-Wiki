# Pipeline: codex build, retrieval & Ask

> From chapter text to a spoiler-safe knowledge base, and from a reader's question to a
> cited answer. Module reference: [../modules/codex.md](../modules/codex.md); the
> invariant: [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Build: chunk → embed → extract(+link) → index

Triggered by the UI **Build** button (`POST /api/novels/{id}/codex/build` → one durable
job, 1 × `codex_builds` quota) or stage-by-stage via CLI. All stages are idempotent and
range-limitable; a rebuild after new chapters only processes the new range.

### 1. Chunk

Readable chapter text (Reading port) → sentence/paragraph-bounded passages of
~`CHUNK_TARGET_TOKENS` (500) with `CHUNK_OVERLAP` (80) token overlap (tiktoken-counted),
stored in `chunks` with `(novel_id, chapter, chunk_index)` identity. Chapter-bounded
chunks are what make `WHERE chapter <= ceiling` airtight for retrieval.

Forced re-chunking upserts that identity instead of deleting/reinserting the chapter: an
unchanged passage keeps its row id and embedding, while changed passages clear only their
own embeddings. If a changed chapter already has an `extraction_state` checkpoint, re-chunk
refuses until the dependent extraction is explicitly invalidated; this prevents stored
citations from silently becoming orphaned.

### 2. Embed

Every chunk with `embedding IS NULL` → `EMBED_MODEL` (batched) → pgvector column
(HNSW cosine index when `EMBED_DIM ≤ 2000`).

### 3. Extract — forward-only, in strict chapter order

For each chapter ascending (never backwards — Invariant 2 of the pipeline):

1. Inputs: the chapter's chunks (id-marked so the model can cite them), the **running
   story-so-far summary** through the previous chapter (`extraction_state`), and a
   compact **roster of already-known entities** (so the model links "the young master"
   to an existing entity instead of minting a duplicate).
2. `MODEL_FLASH` returns JSON: new/updated entities (+ per-chapter descriptions),
   facts (typed, chunk-cited), relationships, events, aliases, and **identity reveals**
   with the chapter they're revealed in. Parsing is fence/`json-repair`-tolerant with
   one temperature-bumped re-ask on malformed output; model-supplied provenance chunk
   ids are filtered to the chapter's real ids.
3. **Verification pass** (`EXTRACTION_VERIFY`, default on): a second call over the same
   chapter catches missed facts and — critically — missed identity reveals. (+1 call
   per chapter.)
4. **Entity linking** (`link.py`) per mention: exact name/alias match → trigram fuzzy
   (considered ≥ `FUZZY_MATCH_THRESHOLD` 0.35; a *single* candidate auto-accepts only
   ≥ `FUZZY_AUTO_ACCEPT` 0.6) → name-embedding similarity
   (≥ `SEMANTIC_MATCH_THRESHOLD` 0.85) → LLM disambiguation for the gray zone → create
   a new entity. Wrong merges are repairable later (`merge-entities`).
5. **Atomic commit** — the `commit_codex_extraction` workflow: re-read the chapter *with
   a row lock*, verify `sha256(content)` equals what the model actually read (abort
   `source_changed` otherwise), then write all artifacts + the new running summary +
   `extraction_state` (run id, model label, source hash) in one transaction.
   Ceiling-relevant caches for the range are cleared.

AGY durable-job retries repeat the idempotent chunking and missing-embedding passes before
they resume extraction. Unchanged chunks retain their embeddings, so only still-missing
vectors are purchased; a retry can therefore finish preprocessing interrupted by worker or
database failure. Extraction skips chapters already checkpointed by that same job and commits
complete-but-uncommitted artifacts when available. A force extraction replaces the chapter
being committed and invalidates its checkpoint plus the downstream checkpoint suffix, whose
running summaries depend on it. Later builds replace any orphaned chapter artifacts while
recreating those checkpoints in chronological order.

For the AGY transport, the same chapter chunks, prior summary, roster, exact source hash, and
output shape are packed into one `input/task.md` file, eliminating the old sequence of
separate chapter, roster, schema, and summary reads.
Hash-pinned task instructions are inlined in the initial print prompt instead of activated as
a workspace skill. The model writes only `extraction.json`, `running-summary.md`, and
`audit.json`; the trusted stop hook creates `manifest.json`. This reduced the pinned
Lord of the Mysteries chapter 1–5 canaries to 6–7 model requests each, versus historical
34–45-request failing runs, without committing canary output to the database.

### 4. Index

`BM25Manager.rebuild()` — the per-novel bm25s lexical index, persisted under
`data/bm25_index/<novel_id>/`, staleness-fingerprinted against the chunk set, lazily
loaded on first query, blocking work offloaded to a thread.

## Read side: everything ceiling-bounded

Resolution first, always: `CeilingPort.resolve(novel_id, principal, requested)` clamps
the *requested* ceiling (the UI slider) to the server-trusted `max_chapter_read`
(owners/admins may range over the full span). The resulting `CeilingContext` is threaded
into **every** query; all SQL filters by it (`first_seen_chapter`,
`revealed_at_chapter`, fact/relationship/event `chapter`, chunk `chapter`).

Surfaces: stats, entity browse/search, entity profile (per-chapter description history +
facts + relationships + timeline + identity banners — profiles synthesize via LLM on
first view and cache in `wiki_cache` per `(entity, ceiling)`), timelines, and Ask.

## Ask (agentic Q&A)

`POST /api/novels/{id}/ask` → `CodexQueryService.ask` in this exact order:

1. **Trusted ceiling** resolution.
2. **Cache** — md5 of the normalized question + ceiling → `query_cache` hit returns
   instantly, free, no gates.
3. **Cost gates** (uncached only): verified email (`ASK_REQUIRE_VERIFIED`) → hourly
   uncached cap (`ASK_MAX_UNIQUE_PER_USER_HOUR` 30) → concurrency slot
   (`ASK_MAX_CONCURRENT_PER_USER` 2, self-expiring lease). Question length is bounded
   first (`ASK_MAX_QUERY_CHARS` 1000 → 422).
4. **Agent loop** (`agent.py::answer_question`, ≤ `MAX_ITERATIONS` 5): **Pro plans**
   tool calls → tools execute — `novel_id` and `ceiling` are injected server-side
   (never model-controlled) and every model-chosen argument is clamped
   (`ASK_TOOL_MAX_*`) — → **Flash distills** the retrieved evidence → **Pro reasons**
   toward an answer or another round. Toolset: `hybrid_search`
   (BM25 ⊕ dense → RRF `RRF_K`=60 over `RETRIEVE_K`=50), `rerank` (top
   `RERANK_TOP_N`=8), `get_chunk` (None beyond ceiling), `resolve_entity`,
   `get_entity_profile`, `get_relationships`, `get_identity_links`, `get_timeline`,
   `list_entities`, `get_connected_personas` (recursive persona folding across
   *revealed* identity links only).
5. **Citations** — inline markers resolved to structured
   `{kind, id, chapter, snippet}` (popover-backed in the UI); evidence ids + answer
   cached in `query_cache`.

## Recap

`POST /api/novels/{id}/recap` (mounted by Experience, executed by Codex): the same
trusted ceiling, a story-so-far synthesis with citations, cached per
`(novel, ceiling)` — the model never sees a chapter beyond the reader's ceiling.

## Maintenance

- **New chapters** ⇒ codex stale (health panel shows it); next build extends forward.
- **Source renumbering** is blocked while artifacts exist (`update_source_offset`
  guard); import commits invalidate affected ranges.
- **Duplicate entities** ⇒ `POST …/merge-entities` / CLI `merge` (re-points everything,
  clears caches).
- Spoiler regression suites: `eval/spoiler_tests.py`,
  `eval/spoiler_boundary_tests.py`; cost-control suite:
  `eval/ai_cost_controls_tests.py`.
