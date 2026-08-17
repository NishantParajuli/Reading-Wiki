# Pipeline: codex build, retrieval & Ask

> From chapter text to a spoiler-safe knowledge base, and from a reader's question to a
> cited answer. Module reference: [../modules/codex.md](../modules/codex.md); the
> invariant: [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Build: chunk → embed → extract(+link) → index

Triggered by the UI **Build** button (`POST /api/novels/{id}/codex/build` → one durable
job, 1 × `codex_builds` quota) or stage-by-stage via CLI. All stages are idempotent and
range-limitable; a rebuild after new chapters only processes the new range.

### 1. Chunk

Readable narrative text (`chapter`/`interlude`, including unnumbered epilogues and side
stories; front/back matter is cleanup-only) →
sentence/paragraph-bounded passages of
~`CHUNK_TARGET_TOKENS` (500) with `CHUNK_OVERLAP` (80) token overlap (tiktoken-counted),
stored in `chunks` with `(novel_id, chapter, chunk_index)` identity. Chapter-bounded
chunks are what make `WHERE chapter <= ceiling` airtight for retrieval.
Rows whose content is null, empty, or whitespace-only are excluded from every Codex stage;
the range scheduler and chapter loader use the same nonblank-source contract.

Forced re-chunking upserts that identity instead of deleting/reinserting the chapter: an
unchanged passage keeps its row id and embedding, while changed passages clear only their
own embeddings. If a changed chapter already has an `extraction_state` checkpoint, re-chunk
refuses until the dependent extraction is explicitly invalidated; this prevents stored
citations from silently becoming orphaned.
Stale front/back-matter chunks are removed during a v2.1 build. If legacy structured
claims still depend on one of those sections, chunking fails closed and asks the operator
to run `reset-codex` before rebuilding. A bounded-memory checkpoint whose numeric range
passes over an excluded section is not by itself a dependency: ranges use the first and
last narrative chapter as endpoints and can contain front/back-matter gaps.

### 2. Embed

Every chunk with `embedding IS NULL` → `EMBED_MODEL` (batched) → pgvector column
(HNSW cosine index when `EMBED_DIM ≤ 2000`).

### 3. Extract — bounded memory v2.1, forward-only in strict chapter order

For each chapter ascending (never backwards — Invariant 2 of the pipeline):

1. `context.py` deterministically builds a spoiler-safe bundle from only data before the
   chapter: the last three chapter summaries (or their containing open-block children),
   the latest completed 25-chapter checkpoint
   and completed volume; folded entity and relationship state; relevant unresolved plot threads; and at
   most `CODEX_CONTEXT_MAX_ENTITIES` entities. Candidates combine exact chapter
   names/aliases, recent activity, unresolved-thread participants, graph neighbors,
   trigram title spans, and exact pgvector similarity. Identity, state, thread, and total
   token caps are independent. Literal current-chapter names are selected first and may
   not be silently dropped; at most 20 recent/vector/graph-only background entities are
   added. The full entity
   database remains available to deterministic linking but is never dumped into a prompt.
2. The selected backend returns strict artifact-schema 2.2 JSON (persisted pipeline rows remain
   version 2.1): entities, facts, relationships, events, aliases,
   identity reveals, entity/relationship **state transitions**, important plot-thread
   updates, and only the supplied hierarchical-memory targets. Every material item must
   cite a real current-chapter chunk and carry a short `evidence_text` span copied verbatim
   from one cited chunk. Empty/invalid provenance is rejected rather than replaced with every
   chapter chunk. Claims may use only supplied `eN` refs or declared
   `mN` refs; arbitrary IDs and undeclared references never reach linking. Each new
   mention's `surface_form` must also be a literal word-bounded current-chapter span—an
   inferred role such as “the hero's father” is rejected even when the inference is plausible.
   A newly spoken name for a supplied entity is an alias. Identity links connect two entities that
   existed before the reveal; an identity introduced and revealed in the current chapter may not
   become a duplicate persona row.
   Host normalization also removes generic nouns/roles and their dependent claims. Fact text
   must name its entity, relationship text both endpoints, and an event at least one participant;
   this catches wrong ref attachment before commit. A visible character's leading name
   may satisfy that check only when it is at least three characters, non-generic, and uniquely
   identifies one visible ref. Trusted entity types keep the exception character-only; ambiguous
   shared names and shortened place, organization, item, or concept names still fail closed.
   Declared concept and item names accept only mechanically derived regular plurals, so
   `Stone Treant` / `Stone Treants` is valid while prefix, stem, and fuzzy matches remain invalid.
   Organization, faction, and concept names also accept a whole-name regular
   singular-possessive/plural-possessive inflection such as `Adventurer's Guild` /
   `Adventurers' Guild`; Unicode apostrophe typography is normalized, but omitted possessive
   markers and unrelated lexical edits still fail.
   Trusted plural family factions also accept explicit singular group forms such as `Greyrat
   family` or `Greyrat household`; trusted geopolitical names accept unambiguous structural
   inversions such as `Asura Kingdom` / `Kingdom of Asura`. On transports with independent verification, isolated
   first-pass alignment issues become exact group/index/ref repair instructions for that verifier
   instead of aborting before review. The verifier output still passes the strict host checks;
   one isolated residual claim/ref mismatch is removed rather than committing an ambiguous
   attachment or failing the whole chapter. Broad mismatch (two or more items at 40% or more of
   claim output, or more than three items) still retries the chapter.
   A chapter may advance each plot-thread ref only once. On the two-pass OpenAI path, duplicate
   first-pass updates are supplied to the verifier as exact repair targets so it can combine their
   supported developments. The final host gate still enforces one update per ref. If the verifier
   leaves exactly one extra duplicate, the host retains the first grounded update and quarantines
   only the extra; more than one leftover duplicate retries the chapter rather than silently
   discarding broad thread progress.
   Stable thread-title/keyword matching remains the deterministic fast path, but topic relevance is
   ultimately semantic: a chapter may use aliases, personas, nicknames, or paraphrases. One lexical
   topic miss is sent to the independent verifier with its trusted title, keywords, participants,
   and exact item location. If the verifier retains it, the host requires continuity with two
   trusted participants (or the sole participant for a one-entity thread). Multiple retained misses
   or weaker continuity fail with `thread_relevance_broad_failure`; a dormant thread still requires
   `reopen`. Thus ordinary co-occurrence cannot update a thread, while chapter-135-style
   Fitz/Rudy wording can preserve a real Sylphiette/Rudeus reconnection development.
   The atomic commit boundary receives an explicit verified-topic flag and replays these same
   limits against the locked chapter snapshot and context manifest; unverified transports remain
   lexical-strict.
   The claim may paraphrase its evidence; deterministic validation proves that the literal anchor
   is local, while the independent
   verifier checks semantic entailment. Reader-facing text may not expose local
   `mN/eN/tN/pN` refs.
3. **Review/verification:** the direct API transport makes a best-effort second extraction
   call when `EXTRACTION_VERIFY=true` (default), retaining the valid first proposal if that
   verifier itself fails. The AGY extraction task must self-review before writing its
   artifacts; `AGY_SEPARATE_CODEX_VERIFY=true` adds a separate AGY verification child run
   but is off by default. OpenAI Codex runs a separate Luna/xhigh verification turn by default.
   Primary extraction stays within the 48k Codex context budget. Verification retains the same
   complete chapter and trusted memory, adds the complete draft in compact JSON, and has a separate
   64k ceiling for that unavoidable second-pass payload. This headroom changes neither stored RAG
   content nor primary context selection and never truncates claims to make a verifier fit.
   Draft anchor, claim-alignment, duplicate-thread, and semantic thread-topic findings are passed to the verifier as exact
   group/index repair targets. The
   verifier repairs or drops claims that are absent, contradictory, or merely topically related.
   Evidence locality compares exact, boundary-aware source-word sequences; punctuation, quote
   delimiters, and apostrophe typography cannot create false failures, while changed words or word
   order still fail. After semantic verification only, the host can canonicalize an exact ordered
   selection that omitted at most a bounded nearby source span, or relocate an exact anchor to the
   supplied overlapping chunk that contains it. The resulting anchor is one literal contiguous
   source slice. The repair cannot change/reorder words or join distant passages. One isolated
   residual anchor failure is quarantined without losing the chapter; broad failure
   (two or more items at 40% or more of material output, or more than three items) retries the
   chapter instead of hiding missing information. Worker-loss recovery obeys the verification
   policy: when separate verification is enabled, only a valid
   verifier artifact is resumable; a draft-only artifact is never committed as a shortcut.
   All paths still pass the 2.2 artifact proposal through trusted validation
   and the same atomic commit checks. Before the shared host schema validation, all
   transports apply the same narrow provider-neutral normalization: redundant
   supplied-roster `eN` records are removed from `mentions` (claims keep using those
   refs), generic/unnamed entity declarations plus dependent claims are removed, and optional
   temporal-transition items with state keys outside the closed pipeline-2.1
   vocabularies are discarded. The AGY stop hook may require the model to repair an
   invalid artifact before it reaches that host boundary. No references, provenance, or
   required groups are invented. A direct provider proposal that remains invalid receives
   one complete-regeneration retry containing compact trusted validation feedback and the
   exact ref/state-key rules; the second invalid proposal still fails closed. This behavior
   does not depend on a provider-specific JSON-schema feature.
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

- Chapter summaries use that chapter text only, target 80–220 tokens, and are rejected
  outside a dynamic minimum/300-token maximum. Summaries that expose chunks, numeric
  citations, or local candidate refs are rejected.
- Checkpoints are emitted only after 25 narrative chapters (`chapter`/`interlude`) inside
  one `part_label` boundary. A real labeled part ending also closes its final short block.
  Every reducer copies the trusted ordered `covered_chapters` and partitions each child
  chapter exactly once across substantive key beats of at most six chapters. The host renders
  the persisted summary from those beats and stores the beats/coverage in evidence, preventing
  an endpoint-only free-form summary. Each immutable completed row is recomputed from grounded
  child summaries plus the current chapter; partial/open checkpoint summaries are never generated or fed back
  into themselves. Up to 24 grounded summaries in the current open block remain available
  as bounded context, so chapters between checkpoint boundaries do not lose the active arc.
- A volume summary is generated only on the final narrative chapter of a non-empty,
  database-supplied `part_label`. AI never infers boundaries. The immutable row stores
  start/end/through chapters, label, source and checkpoint hashes, evidence, model/run,
  and pipeline version. Books without real labels simply have no volume summaries.
- Historical facts remain append-only. Mutable truth uses ordered `set`/`clear`/`add`/
  `remove`/`confirm`/`contradict` transitions with certainty, perspective, narrative
  scope, provenance, and supersession. Reads fold only transitions within the requested
  ceiling. Goals are single-valued; confirmed death clears living-only state. Unconfirmed
  conditions, custody, goals, occupations, and locations age out to unknown under separate
  configured windows instead of remaining falsely current forever.
- Existing thread updates require the stable title/keyword topic in the current chapter.
  Recency or a shared participant alone is insufficient. Threads older than the dormancy
  window are projected dormant and must be explicitly reopened; accumulated keywords and
  participants are bounded.

Subscription-worker retries repeat idempotent chunking and missing-embedding work, then resume only when
the saved context hash still matches. Force extraction invalidates all derived v2.1 state,
summaries, contexts, and memory from the changed chapter onward. Builds recreate the suffix
chronologically and prune omitted entities only when a completed v2.1 first-chapter extraction
exists and nothing references the entity. One active job key per novel/pipeline version and
the commit advisory lock prevent overlapping ranges from racing.
Starting in the middle of an unbuilt v2.1 checkpoint block fails closed: every prior child
summary and completed preceding checkpoint must exist before extraction continues. This is
why an initial or quality-contract rebuild starts at the book's first narrative chapter.

The three transports are semantically equivalent, not call-for-call identical. All use the
same deterministic bounded context, artifact-schema 2.2 proposal, reducer targets, provenance/ref
rules, temporal/thread semantics, linking constraints, source/context revalidation, and
`commit_codex_extraction` transaction. Direct API normally performs extraction → optional
verification → separate chapter summary, with individual gray-case linking calls when
needed. AGY normally performs extraction + self-review + chapter summary in one isolated
artifact run, then batches ambiguous mentions into one child run; its separate verifier is
optional. OpenAI Codex uses strict structured App Server turns, with a separate verifier by
default; the host materializes its result into the shared artifact contract. Subscription
workers batch ambiguous mentions into the same validated child-run path. For AGY, the
chapter chunks, bounded-memory JSON, exact source hash, and output shape are packed into
one `input/task.md` file.
Hash-pinned task instructions are inlined in the initial print prompt instead of activated as
a workspace skill. The model writes only `extraction.json`, `running-summary.md`, and
`audit.json`; the trusted stop hook creates `manifest.json`. Plugin `1.4.4` additionally
requires literal per-item evidence anchors and checks that each anchor occurs in a cited chunk.
It retains the `1.4.2` behavior that inlines and validates the exact batched-disambiguation
decision shape before exit; malformed
or incomplete case decisions receive the bounded hook repair turn instead of becoming failed
child runs. The underlying plugin `1.3.1` was qualified with a real Lord of the Mysteries
chapter-1 v2 run that passed trusted validation and committed atomically in a disposable
database under an eight-request ceiling. That is an early canary, not evidence that the
`1.4.4` hardening or late/checkpoint/final-volume chapters have passed a provider canary;
those remain required rollout gates. The dated evidence is recorded in
[../testing.md](../testing.md).

During extraction, progress uses the committed durable position and the actual source chapter,
for example `source chapter 15 (13/320)`. Whole-job retries therefore keep the same overall total
and cannot reset the visible label to `chapter 1/N`; the stage stored in progress is updated with
the database job stage so the frontend does not remain on `chunking` while a model turn is active.

### 4. Index

`BM25Manager.rebuild()` — the per-novel bm25s lexical index, persisted under
`data/bm25_index/<novel_id>/`, staleness-fingerprinted against the chunk set, lazily
loaded on first query, blocking work offloaded to a thread. Partial reader ceilings build a
bounded LRU of exact eligible-corpus indexes, so future documents affect neither results nor IDF.

## Read side: everything ceiling-bounded

The Codex screen always reports completed build coverage as the highest chapter in
`extraction_state` plus the number of completed chapter checkpoints. This operational
metadata is distinct from the reader's spoiler ceiling: preprocessing stages such as
chunking and embedding do not advance it, and it can safely report a later chapter number
without exposing any story content.

Resolution first, always: `CeilingPort.resolve(novel_id, principal, requested)` clamps
the *requested* ceiling (the UI slider) to the server-trusted `max_chapter_read`
(owners/admins may range over the full span). The resulting `CeilingContext` is threaded
into **every** query; all SQL filters by it (`first_seen_chapter`,
`revealed_at_chapter`, fact/relationship/event `chapter`, chunk `chapter`).

Surfaces: stats, entity browse/search, entity profile (per-chapter description history +
bounded recent facts + folded current/relationship state + relevant open threads +
relationships/timeline/identity banners — profiles synthesize via LLM on
first view, pass an independent Flash grounding check plus Pro repair when needed, and
cache only a machine-valid result in `wiki_cache` per `(entity, ceiling)`. Profile cache
hits must match both `MODEL_PRO` and `CODEX_PROFILE_CACHE_VERSION`), timelines, and Ask.

## Ask (agentic Q&A)

`POST /api/novels/{id}/ask` → `CodexQueryService.ask` in this exact order:

1. **Trusted ceiling** resolution.
2. **Cache** — md5 of `CODEX_QA_CACHE_VERSION`, both configured read-side model ids, and
   the normalized question + ceiling → `query_cache` hit returns instantly, free, no
   gates. A model or grounding-contract change therefore cannot reuse an older answer.
3. **Cost gates** (uncached only): verified email (`ASK_REQUIRE_VERIFIED`) → hourly
   uncached cap (`ASK_MAX_UNIQUE_PER_USER_HOUR` 30) → concurrency slot
   (`ASK_MAX_CONCURRENT_PER_USER` 2, self-expiring lease). Question length is bounded
   first (`ASK_MAX_QUERY_CHARS` 1000 → 422).
4. **Agent loop** (`agent.py::answer_question`, ≤ `MAX_ITERATIONS` 5): **Pro plans**
   tool calls → tools execute — `novel_id` and `ceiling` are injected server-side
   (never model-controlled) and every model-chosen argument is clamped
   (`ASK_TOOL_MAX_*`) — → **Flash distills** the retrieved evidence → **Pro reasons**
   toward an answer or another round. Toolset: `hybrid_search`
   (BM25 ⊕ dense → RRF `RRF_K`=60 over `RETRIEVE_K`=50 → automatic OpenRouter
   rerank to `RERANK_TOP_N`=8, with fused candidates retained if reranking is
   unavailable), `get_chunk` (None beyond ceiling), `resolve_entity`,
   `get_entity_profile`, `get_relationships`, `get_timeline`, and `list_entities`.
   Entity/profile/relationship reads recursively fold personas only across identity
   links revealed within the ceiling.
5. **Hard read budgets** — facts, relationships, timelines, and entity browse have SQL
   limits; raw retrieval evidence and distilled evidence have separate total token budgets.
   Exhaustion stops tool expansion and synthesizes only when citeable evidence was gathered.
6. **Grounding and citations** — Flash checks factual story claims against the same digests
   and Pro repairs flagged claims. Faithful paraphrases and explicitly framed interpretations
   may synthesize cited premises without requiring the evidence to state the conclusion
   word-for-word. Deterministic validation remains fail-closed for invented/unretrieved ids,
   answers with no request-grounded citation, and citations that do not resolve inside the
   trusted ceiling; citation placement in every individual Markdown block is not a whole-answer
   failure. A verifier/repair failure or hard citation failure returns the fixed, uncached
   insufficient-evidence answer. Only the validated answer + evidence ids enter `query_cache`.
7. **Long-request transport** — the SPA requests `application/x-ndjson`, receives an immediate
   `started` frame and 15-second `heartbeat` frames, then the final `result` or `error`. This
   keeps uncached Ask runs alive through the 120-second proxy read timeout. Plain JSON clients
   retain the synchronous response. Closing the stream cancels request-owned provider work and
   releases the concurrency slot.

The same negotiated transport wraps first-view entity profile synthesis. Cached Ask answers and
cached profiles still complete immediately, inside the same compatible stream envelope used by the
SPA.

## Recap

`POST /api/novels/{id}/recap` (mounted by Experience, executed by Codex): the same
trusted ceiling, a story-so-far synthesis with citations, cached per
`(novel, ceiling)` — the model never sees a chapter beyond the reader's ceiling. It uses the same
negotiated NDJSON keepalive transport as Ask and entity profiles; ordinary JSON clients retain the
synchronous response shape. Closing the stream cancels the provider work.

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
