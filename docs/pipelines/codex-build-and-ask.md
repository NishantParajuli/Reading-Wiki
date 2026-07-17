# Pipeline: codex build, retrieval & Ask

> From chapter text to a spoiler-safe knowledge base, and from a reader's question to a
> cited answer. Module reference: [../modules/codex.md](../modules/codex.md); the
> invariant: [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Build: chunk → embed → extract(+link) → index

Triggered by the UI **Build** button (`POST /api/novels/{id}/codex/build` → one durable
job, 1 × `codex_builds` quota) or stage-by-stage via CLI. All stages are idempotent and
range-limitable; a rebuild after new chapters only processes the new range.

### 1. Chunk

Readable narrative text (`chapter`/`interlude`; front/back matter is cleanup-only) →
sentence/paragraph-bounded passages of
~`CHUNK_TARGET_TOKENS` (500) with `CHUNK_OVERLAP` (80) token overlap (tiktoken-counted),
stored in `chunks` with `(novel_id, chapter, chunk_index)` identity. Chapter-bounded
chunks are what make `WHERE chapter <= ceiling` airtight for retrieval.

Forced re-chunking upserts that identity instead of deleting/reinserting the chapter: an
unchanged passage keeps its row id and embedding, while changed passages clear only their
own embeddings. If a changed chapter already has an `extraction_state` checkpoint, re-chunk
refuses until the dependent extraction is explicitly invalidated; this prevents stored
citations from silently becoming orphaned.
Stale front/back-matter chunks are removed during a v2 build. If legacy structured
claims still depend on one of those sections, chunking fails closed and asks the operator
to run `reset-codex` before rebuilding.

### 2. Embed

Every chunk with `embedding IS NULL` → `EMBED_MODEL` (batched) → pgvector column
(HNSW cosine index when `EMBED_DIM ≤ 2000`).

### 3. Extract — bounded memory v2, forward-only in strict chapter order

For each chapter ascending (never backwards — Invariant 2 of the pipeline):

1. `context.py` deterministically builds a spoiler-safe bundle from only data before the
   chapter: the last three chapter summaries (or their containing open-block children),
   the latest completed 25-chapter checkpoint
   and completed volume; folded entity and relationship state; relevant unresolved plot threads; and at
   most `CODEX_CONTEXT_MAX_ENTITIES` entities. Candidates combine exact chapter
   names/aliases, recent activity, unresolved-thread participants, graph neighbors,
   trigram title spans, and exact pgvector similarity. Identity, state, thread, and total
   token caps are independent; low-ranked entities are dropped first. The full entity
   database remains available to deterministic linking but is never dumped into a prompt.
2. `MODEL_FLASH` returns strict v2 JSON: entities, facts, relationships, events, aliases,
   identity reveals, entity/relationship **state transitions**, important plot-thread
   updates, and only the supplied hierarchical-memory targets. Every material item must
   cite a real current-chapter chunk. Empty/invalid provenance is rejected rather than
   replaced with every chapter chunk. Claims may use only supplied `eN` refs or declared
   `mN` refs; arbitrary IDs and undeclared references never reach linking. Each new
   mention's `surface_form` must also be a literal word-bounded current-chapter span—an
   inferred role such as “the hero's father” is rejected even when the inference is plausible.
3. **Review/verification:** the direct API transport makes a best-effort second extraction
   call when `EXTRACTION_VERIFY=true` (default), retaining the valid first proposal if that
   verifier itself fails. The AGY extraction task must self-review before writing its
   artifacts; `AGY_SEPARATE_CODEX_VERIFY=true` adds a separate AGY verification child run
   but is off by default. Both paths still pass the v2 proposal through trusted validation
   and the same atomic commit checks.
4. **Entity linking** (`link.py`) per declared mention: type-compatible exact name/alias
   match → trigram fuzzy (`FUZZY_MATCH_THRESHOLD`; one candidate auto-accepts only above
   `FUZZY_AUTO_ACCEPT`) → name-embedding similarity → validated gray-case decision → new
   entity. A model can select only a supplied candidate.
5. **Atomic commit** — `commit_codex_extraction` takes a per-novel advisory lock, re-reads
   the chapter with a row lock, verifies `sha256(content)`, recomputes the deterministic
   context and verifies its hash, then writes historical claims, temporal transitions,
   activity, threads, the chapter summary, memory reducers, the context manifest, and
   `extraction_state` together. A changed source aborts as `source_changed`; changed
   context aborts as `stale_extraction_context` rather than reinterpreting `eN` refs.

#### Hierarchical summaries and current state

- Chapter summaries use that chapter text only, target 150–250 tokens, and are rejected
  above `CODEX_CHAPTER_SUMMARY_MAX_TOKENS` (300 by default).
- Checkpoints are emitted only after 25 narrative chapters (`chapter`/`interlude`) inside
  one `part_label` boundary. A real labeled part ending also closes its final short block.
  Each immutable completed row is recomputed from grounded child summaries plus the
  current chapter; partial/open checkpoint summaries are never generated or fed back
  into themselves. Up to 24 grounded summaries in the current open block remain available
  as bounded context, so chapters between checkpoint boundaries do not lose the active arc.
- A volume summary is generated only on the final narrative chapter of a non-empty,
  database-supplied `part_label`. AI never infers boundaries. The immutable row stores
  start/end/through chapters, label, source and checkpoint hashes, evidence, model/run,
  and pipeline version. Books without real labels simply have no volume summaries.
- Historical facts remain append-only. Mutable truth uses ordered `set`/`clear`/`add`/
  `remove`/`confirm`/`contradict` transitions with certainty, perspective, narrative
  scope, provenance, and supersession. Reads fold only transitions within the requested
  ceiling, so an old location is not equally current after a move.

AGY retries repeat idempotent chunking and missing-embedding work, then resume only when
the saved context hash still matches. Force extraction invalidates all derived v2 state,
summaries, contexts, and memory from the changed chapter onward. Builds recreate the suffix
chronologically and prune omitted entities only when a completed v2 first-chapter extraction
exists and nothing references the entity. One active job key per novel/pipeline version and
the commit advisory lock prevent overlapping ranges from racing.
Starting in the middle of an unbuilt v2 checkpoint block fails closed: every prior child
summary and completed preceding checkpoint must exist before extraction continues. This is
why the initial v1→v2 rollout starts at the book's first narrative chapter.

The two transports are semantically equivalent, not call-for-call identical. Both use the
same deterministic bounded context, v2 proposal schema, reducer targets, provenance/ref
rules, temporal/thread semantics, linking constraints, source/context revalidation, and
`commit_codex_extraction` transaction. Direct API normally performs extraction → optional
verification → separate chapter summary, with individual gray-case linking calls when
needed. AGY normally performs extraction + self-review + chapter summary in one isolated
artifact run, then batches ambiguous mentions into one child run; its separate verifier is
optional. For AGY, the chapter chunks, bounded-memory JSON, exact source hash, and output
shape are packed into one `input/task.md` file.
Hash-pinned task instructions are inlined in the initial print prompt instead of activated as
a workspace skill. The model writes only `extraction.json`, `running-summary.md`, and
`audit.json`; the trusted stop hook creates `manifest.json`. Plugin `1.3.2` additionally
inlines and validates the exact batched-disambiguation decision shape before exit; malformed
or incomplete case decisions receive the bounded hook repair turn instead of becoming failed
child runs. The underlying plugin `1.3.1` was qualified with a real Lord of the Mysteries
chapter-1 v2 run that passed trusted validation and committed atomically in a disposable
database under an eight-request ceiling. That is an early canary, not evidence that the
`1.3.2` hardening or late/checkpoint/final-volume chapters have passed a provider canary;
those remain required rollout gates. The dated evidence is recorded in
[../testing.md](../testing.md).

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
bounded recent facts + folded current/relationship state + relevant open threads +
relationships/timeline/identity banners — profiles synthesize via LLM on
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
5. **Hard read budgets** — facts, relationships, timelines, and entity browse have SQL
   limits; raw retrieval evidence and distilled evidence have separate total token budgets.
   Exhaustion stops tool expansion and synthesizes from what was gathered.
6. **Citations** — inline markers resolved to structured
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
- **Full structured rebuild** ⇒ `reset-codex NOVEL_ID` (confirmation required unless
  `--force`). It refuses while a Codex job is active and deletes derived knowledge/caches
  while preserving chunks and embeddings; then run the full Build (or `chunk` before
  `extract`) so stale non-narrative chunks are cleaned before indexing.
- Spoiler regression suites: `eval/spoiler_tests.py`,
  `eval/spoiler_boundary_tests.py`; cost-control suite:
  `eval/ai_cost_controls_tests.py`.
