# Chapter illustrations and character sheets

Chapter illustrations are an optional Codex feature. An eligible owner or administrator
can request **one to three scene images for a chapter**, with up to four new character
reference sheets when the chosen scenes need them. This is a per-chapter image count,
not a restriction to chapters 1–3. Reading, importing, and opening the illustration
gallery do not start image generation.

## Reader workflow

After the chapter prose, open **Illustrate this chapter**. Choose the number of scenes
and one of three styles, then select **Generate illustrations**:

| Style | Direction |
|---|---|
| `luminous` (default) | expressive anime linework, warm gold light, cobalt shadows, painterly settings |
| `celestial` | pearlescent pastel light, lavender/peach atmosphere, delicate linework |
| `ink` | refined ink linework, navy shadows, amber light, dramatic contrast |

The default request is one Luminous scene. The gallery has full-size scene links,
expandable character sheets, and design notes. Generated artwork is an interpretation:
unspecified visual details are artistic choices, not new canonical story facts.
**Generate again** explicitly requests another set. Running work reports its real stage
and links to the Jobs center; the reader can continue reading while it runs.

Generation requires editable novel access, an active account (verified email for
non-admins), the existing
admin-granted OpenAI Codex `codex_extract` workload, both
`OPENAI_CODEX_ENABLED` and `OPENAI_CODEX_CODEX_ENABLED`, and an available host worker.
The grant is rechecked before execution. An administrator role alone does not enable
the subscription backend. Existing artwork remains readable without generation access,
subject to the novel and chapter permissions below.

## Source and spoiler boundary

Codex owns the application service, prompt plan, character reference records, and scene
gallery. Bootstrap injects Catalog/Reading access, a Reading chapter snapshot, Work
scheduling, and the AI Execution renderer. Planning reads the shared chapter's stored
text through Reading's gateway. It does not use a personal translation overlay and does
not call the chapter HTTP endpoint, so generation does not advance reading progress.
A chapter without shared text cannot be illustrated.

Both gallery and image requests enforce novel readability and the server's allowed
chapter ceiling. Every account, including owners/admins, uses the same trusted-progress
ceiling, with the first stored chapter as the fallback when no progress exists. The requested
chapter bounds the planner's story text, earlier summaries, character facts, and reusable
reference sheets. Future character designs are excluded even if already generated.
The reference catalog keeps the latest story-chapter revision per character key, using
creation time to break ties within a chapter. It prioritizes names, saved aliases, or
keys mentioned in the current chapter before its 100-identity cap. Matching is
case-insensitive literal text matching, not semantic search. Historical sheet revisions
do not crowd the same recurring character out of that catalog. Only previous references
used by the selected scenes or a proposed name update are pinned into the saved plan.

During an explicitly requested illustration job, the planner can propose up to four
name or alias updates for existing character keys. Each requires an exact quotation
from the current chapter establishing the identity/name connection; every new preferred
name or proposed alias must appear in that chapter. The host checks the quotation and name
occurrences, while the planner judges whether the quotation establishes the identity.
The update retains the stable key and existing image bytes, records the old name and
new aliases for future matching, and saves the preferred name as a new chapter-scoped
reference revision. It does not redraw the character. Earlier chapters keep their
earlier names, and illustrating an earlier chapter later cannot supersede a later
chapter's name revision. Alias-only updates retain the existing preferred name, even
when that unchanged name is absent from the current chapter. This is illustration planning,
not a background rename scan or synchronization with Codex entity edits.

Each image records a SHA-256 of its source chapter title and content. Changed source
text makes old artwork unavailable instead of displaying an outdated interpretation.
Reference sheets keep stable per-novel character keys and a style; a scene records the
exact reference image IDs used for its characters. Reuse respects chapter boundaries and
source validity. Changing an upstream reference's source also hides scenes that used
that reference. Name revisions retain the source hashes of the original sheet and
intervening name revisions; edits to those chapters invalidate the revised sheet and
scenes that depend on it. A later chapter can reuse an earlier sheet without rewriting
that earlier visual identity. Renumbering is blocked while chapter art or a saved art plan
exists; import replacement invalidates art/plans from the replaced chapter onward.

## Durable execution

`POST /api/novels/{id}/chapters/{chapter}/illustrations` schedules a Work
`codex_illustrate` job explicitly on `openai_codex`. The request contains
`{count: 1..3, style: "luminous"|"celestial"|"ink", force: false}`. The active-job
identity includes requester, novel, chapter, style, scene count, and source hash. The OpenAI Codex host worker
claims the job; API and AGY workers do not execute it.

The pipeline runs:

1. Verify the chapter source and check cancellation.
2. Ask **`gpt-6-luna` at `max` reasoning** for a strict JSON art plan. Inputs include
   the chapter text, bounded existing Codex context, and prior reference descriptions.
   The renderer checks that the account exposes `gpt-6-luna` and advertises `max`
   reasoning before starting a turn. This planning turn has no tools. The host validates the requested scene count,
   character keys, exact scene evidence quotations, and proposed name-update evidence
   and name occurrences from this chapter.
3. Persist the plan and its chosen reference revisions. A retry resumes that plan
   instead of inventing a different set of scenes.
4. Checkpoint name revisions using the existing sheet bytes, then render missing new
   character sheets and the scenes with the selected
   character images attached. Native image generation runs through a separate App
   Server turn; it does not relax the tool-free translation/extraction runner.
   The host accepts the first completed image event and closes that session, preventing
   a follow-up redraw from turning one requested image into additional work.
5. Check source freshness/cancellation around rendering and persist validated PNG bytes
   with prompts, discretionary design notes, evidence, reference IDs, model/effort, and
   job-slot provenance. Unique `(job_id, slot)` records keep completed work reusable on
   retry. A deleted/invalidated plan prevents late image writes from recreating its art.

For each style, the reader gallery selects the newest **complete** scene batch in scene
order. Partial replacement work does not displace the previous complete set. Character
sheets are checkpointed separately and can remain available when a later scene fails.
The Art style selector changes both the visible gallery and the next generation request.

The scene count is bounded to three, new character designs to four, distinct referenced
characters across the whole set to four, shared source text to 150,000 characters, and each stored PNG
to 16 MiB and 24 million pixels, with a host PNG decode/verification check. Normal
host-worker leases, heartbeat, cancellation, and provider-wait handling
apply. There is no image-generation API fallback and no automatic generation during a
gallery refresh. These jobs use subscription access/concurrency and provider limits;
they do not reserve a monthly `codex_builds` unit.

The UI polls every five seconds while work is active. Transient read errors retry
without starting another job. Empty or unfinished provider image results enter provider-wait handling; corrupt or
out-of-workspace image artifacts are rejected. Provider exhaustion or unavailability is shown through
the durable job state; see the [OpenAI Codex operator runbook](../openai-codex-operator-runbook.md)
for worker health, waiting jobs, and the separately authorized subscription setup.

## Storage and HTTP

Codex owns `codex_art` (reference/scene metadata and PNG `BYTEA`) and `codex_art_plans`
(durable job plan). Image bytes live in PostgreSQL, not `ASSET_DIR` or a public static
directory. Include them in normal database backup sizing. Novel deletion cascades its
art rows; plan lifetime follows the corresponding durable job. `reset-codex` also
clears the novel's generated art and saved art plans while keeping chunks/embeddings.

| Route | Result |
|---|---|
| `GET /api/novels/{id}/chapters/{chapter}/illustrations` | `items`, `can_generate`, `unavailable_reason`, and `active_job` |
| `POST /api/novels/{id}/chapters/{chapter}/illustrations` | durable `job_id`; reuse/deduplication may avoid a new job |
| `GET /api/novels/{id}/illustrations/{art_id}/image` | authenticated `image/png`, `Cache-Control: private, no-store` |

Gallery items expose ID, kind, title, caption, style, source chapter, prompt, design
notes, and image URL. Despite its name, `active_job` can also contain the latest failed
or canceled job for the requester; completed work returns `null` there. The image route
rechecks access and source validity on every fetch, including direct full-size links.
Gallery polling and source validation load metadata only; image bytes are fetched when
needed for rendering or an authenticated image response.

Implementation: `modules/codex/application/illustrations.py`,
`application/illustration_worker.py`, `domain/illustrations.py`,
`adapters/outbound/illustration_store.py`, and `bootstrap/illustrations.py`. AI Execution
owns `openai_codex/illustration_runner.py` and `images.py`; the frontend owns
`codex/ChapterIllustrations.jsx` and its scoped stylesheet.
