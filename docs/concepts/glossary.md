# Glossary

Project-specific terms, A–Z. General CS concepts are in [primer.md](primer.md).

**Adapter (architecture)** — code translating between the outside world and a module's
application layer. *Inbound*: HTTP/CLI/worker transports. *Outbound*: Postgres,
providers, filesystem, bridges. See [module anatomy](../architecture/module-anatomy.md).

**Adapter (scraper)** — a per-site scraping strategy class (`fenrirealm`, `readhive`,
`boti-translations`, `69shuba`, `wetriedtls`) registered in `ADAPTERS`.

**AGY / Antigravity** — the external CLI used as an alternative AI execution backend
(subscription capacity instead of metered API). Dormant unless globally enabled *and*
admin-granted per user/workload. See [ai-backends](../pipelines/ai-backends.md).

**Application layer** — a module's use cases (services/commands) + ports + DTOs; no SQL,
no HTTP, no provider SDKs.

**Asset** — an extracted image (cover/illustration/page scan): bytes on disk under
`ASSET_DIR/<novel_id>/`, pointer row in `assets`, content-addressed by SHA-256.

**Base content** — the shared text of a chapter (`chapters.content`), as opposed to a
reader's personal *overlay*.

**Block-stream IR** — the normalized intermediate representation every import parser
emits (headings/paragraphs/images/page markers), segmented into the plan.

**Bootstrap** — `novelwiki/bootstrap/`, the composition root: all wiring, no business
logic.

**Bridge** — a small outbound adapter turning another module's public capability into
this module's port (e.g. `IdentityNarrationQuota`).

**Capability** — an executable interface exposed in a module's `public.py`; consumed
only via injection, never by import of the implementation.

**Ceiling (spoiler ceiling)** — the highest chapter whose information a reader may see;
trusted value = server-observed `max_chapter_read`. See
[spoiler-safety](spoiler-safety.md).

**Chunk** — a ~500-token, chapter-bounded passage; the retrieval unit (`chunks`).

**Claim/lease** — the worker-safety pattern: atomic claim (`FOR UPDATE SKIP LOCKED`) +
`claim_token`/`claimed_at` heartbeat + reclaim only after lease expiry.

**Composition root** — see Bootstrap.

**Contract snapshot** — a frozen JSON artifact of an external surface (routes, OpenAPI,
CLI, schema, job states…) under `tests/contracts/snapshots/`; diffs must be intentional.

**Contribution** — a contribute-back offer: a reader's overlay proposed to the novel
owner for merging into the base (`contributions`, statuses
pending/accepted/rejected/auto_merged).

**DTO** — frozen dataclass carrying data across a boundary (`NovelAccess`, `Progress`,
`GlossaryTerm`…).

**Entity** — a codex knowledge node (character/location/faction/item/concept/
organization) with aliases, per-chapter descriptions, facts, relationships, events.

**Experience projection** — a registered, read-only cross-owner SQL view (the only
sanctioned cross-module SQL), living in Experience's two projection repositories.

**Flash / Pro** — the two-model cost split: cheap model reads/distills
(`MODEL_FLASH`), strong model plans/reasons (`MODEL_PRO`).

**Global (visibility)** — the admin-curated shared library tier (above `public`).

**Global chapter number** — a chapter's position in the novel's single reading sequence:
`source-local number + source.chapter_offset`; may be fractional.

**Glossary (translation)** — per-novel source-term → rendering map keeping names
consistent; `locked` rows are user-pinned and never auto-overwritten.

**Identity link / reveal** — "persona A is persona B", effective only from
`revealed_at_chapter` — powers reveal banners and persona folding.

**Idempotency key** — the dedupe string on generic jobs; repeated scheduling attaches to
the existing active job.

**Kernel** — `novelwiki/kernel/`: shared error types + opaque transaction contracts.

**Module** — one of the ten business slices under `novelwiki/modules/`, with enforced
table ownership and a `public.py` contract.

**Overlay** — a reader's personal per-chapter text override on a shared novel
(`chapter_overlays`), anchored to the `base_version` it forked from; `conflict` when the
base moved.

**Owner (novel)** — `novels.owner_id`, the uploader; NULL = system/global stock.

**Platform** — `novelwiki/platform/`: technical substrate (config, DB pool/UoW, web
factory, static, audit, CLI runtime, architecture checks).

**Port** — a Protocol a module's application layer *needs*; implemented by an outbound
adapter or an injected capability.

**Principal** — the frozen identity object (`user_id`, role, status, verified, quota
limits) passed into permission checks; `SystemPrincipal` for CLI/system actors.

**Provenance** — where content came from (scraped/imported/OCR'd/translated/edited/
owner-approved) — badges in the UI; chunk-id citations in the codex.

**Public / `public.py`** — a module's only importable surface for other modules: DTOs,
protocols, stable errors.

**Quota kinds** — `translated_chapters`, `ocr_pages`, `codex_builds`, `tts_chapters`;
monthly, per user, admin-overridable per row.

**Raw (source/chapter)** — foreign-language content needing translation
(`sources.is_raw`; `original_text` preserved).

**Recap** — the spoiler-safe "story so far" summary, cached per `(novel, ceiling)`.

**RRF** — Reciprocal Rank Fusion, the tuning-free merge of BM25 + dense rankings.

**Running summary** — the story-so-far text through chapter K
(`extraction_state.running_summary`), feeding chapter K+1's extraction.

**Shelf** — per-user reading status (`to_read`/`reading`/`completed`) in
`library_entries`.

**Sidecar** — a separate GPU HTTP service (PaddleOCR `:8077`, OmniVoice TTS `:8078`),
token-authenticated, on a private bridge.

**Source** — one ingestion origin of a novel (site+adapter or imported file), with
language/raw flags and a chapter offset.

**Stable compatibility entrypoint** — a historical import path kept as a passive alias
for external consumers; forbidden for internal module communication. List:
[stable-compatibility-entrypoints](../architecture/stable-compatibility-entrypoints.md).

**Tideglass / NovelWiki** — product name / historical code name (package, DB, container
names).

**Transaction API (`…TransactionApi`)** — a public capability obtainable only inside a
unit of work via `transaction.bind(...)`; the mechanism of cross-module atomicity.

**Trigger status** — a job status a worker claims from (vs. the distinct in-progress
*marker* status it claims into).

**Unit of Work (UoW)** — one connection + one transaction per business operation;
participants get connection-bound capabilities; commit/rollback decided once.

**Vertical slice** — organizing code by business capability, not technical layer.

**`waiting_provider`** — the parked-for-capacity job status (AGY subscription
exhausted): no lease, no retries burned, still dedupes, auto-released at `not_before`.

**Workflow** — a named cross-module atomic operation in `novelwiki/workflows/` (8 of
them). See [workflows-and-transactions](../architecture/workflows-and-transactions.md).

**Workload (AI)** — a grantable AGY work category: `translate_batch`, `codex_extract`,
`segment_import`, `ocr_pages`, `ask`, `profile_synthesis`.
