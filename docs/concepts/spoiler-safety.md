# Spoiler safety: the one invariant

> The product's defining rule and the machinery that makes it *structural* rather than
> hopeful. Read this before touching anything in Codex, Reading progress, or Experience
> recap.

## The rule

> When a reader's ceiling is chapter **N**, no information from any chapter **> N** may
> appear in any codex entry, stat, Q&A answer, or recap — ever.

Two design commitments follow:

1. **Never trust the model.** An LLM asked to "avoid spoilers" will eventually fail.
   Instead, the model simply *never receives* out-of-bounds text: retrieval, prompts,
   and evidence are filtered before anything reaches it.
2. **Never trust the client.** The browser can request any ceiling it likes; the server
   clamps it to what it has *observed* the reader read.

## Where the ceiling comes from

`reading_progress.max_chapter_read` — per `(user, novel)`, **monotonic** (only ever
rises), advanced server-side when chapter reads are recorded. The resume position
(`last_chapter`, `scroll_pct`) is separate and client-driven — moving your scrollbar
can move where you *resume*, but cannot unlock codex data.

Resolution: every spoiler-sensitive use case starts with
`CeilingPort.resolve(novel_id, principal, requested)` →
`CeilingContext` (`modules/codex/application/dto.py`):
`effective = min(requested slider value, trusted max_chapter_read)`, with owners/admins
allowed the full chapter span (it's their text). The UI slider is a convenience to look
*backwards*; it can never look forward.

## The enforcement points (defense in depth)

| Layer | Mechanism |
|---|---|
| **Schema** | every codex-owned row carries a chapter key: `entity_facts.chapter`, `relationships.chapter`, `events.chapter`, `chunks.chapter`, `entities.first_seen_chapter`, `entity_aliases.revealed_at_chapter`, `identity_links.revealed_at_chapter`, `entity_descriptions.chapter` |
| **SQL** | every read in `postgres_queries.py` / `retrieval/tools.py` filters `<= ceiling` — entities you haven't met don't exist; aliases/identities resolve only past their reveal chapter; profiles show the description *as of* your ceiling |
| **Retrieval** | BM25 and dense search both take the ceiling; fusion/rerank operate only on already-filtered candidates; `get_chunk` returns `None` beyond the bound (hard refusal, not a filtered result) |
| **Agent** | `novel_id` and `ceiling` are injected server-side into every tool call — the model's own arguments cannot name a different novel or a higher ceiling |
| **Identity folding** | `get_connected_personas` walks identity links *revealed within the ceiling* only, so "the masked swordsman" and the protagonist unify exactly when the story says so |
| **Caches** | `wiki_cache` and `query_cache` are **keyed by ceiling** — an answer computed for ceiling 40 can never be served to a ceiling-20 reader |
| **Forward-only extraction** | chapters are extracted in ascending order; each chapter's facts are stamped with that chapter; the running summary through chapter K contains only chapters ≤ K |
| **Recap** | same trusted ceiling, same cache keying (`(novel, ceiling)`), same filtered evidence |

## Adjacent integrity guards (same philosophy)

- **Source-hash commits** — translation and extraction commits verify the chapter text
  still hashes to what the model actually read (`commit_translation`'s optimistic check;
  `commit_codex_extraction`'s row-locked verify) — stale model output can't land on
  changed text.
- **Renumbering guard** — changing a source's `chapter_offset` (which redefines what
  "chapter 12" means) is refused while any chapter-keyed codex artifact exists.
- **Import invalidation** — committing chapters over an existing range invalidates that
  range's codex artifacts.

## Rules when you change code

1. Adding a codex read? It must take a `ChapterCeiling`/`CeilingContext` and filter in
   SQL. No post-filtering in Python of an unfiltered fetch.
2. Adding a cache? Key it by ceiling.
3. Adding an agent tool? Register it in the dispatcher where the ceiling is injected;
   clamp every model-supplied argument.
4. Adding a chapter-derived table? Include the chapter key; add it to the
   `has_chapter_artifacts` guard and the invalidation path.
5. Never write an endpoint that trusts a client-supplied ceiling upward.

Regression suites: `novelwiki/eval/spoiler_tests.py` and
`eval/spoiler_boundary_tests.py` — extend them with any new surface.
