# Chapter illustrations and character sheets

Chapter illustrations are an optional Codex feature. An eligible owner or administrator
can request illustrations for one chapter or prepare a chapter range from Manage.
**The AI chooses one to three scene images per chapter**, with up to four new character
reference sheets when the chosen scenes need them. Reading, importing, and opening the
illustration gallery do not start image generation.

## Reader workflow

Open **Illustrate this chapter**, choose an art style, then select
**Generate illustrations**. The current chapter is already selected; there is no image-count
control. Luna chooses how many distinct moments warrant an image:

| Style | Direction |
|---|---|
| `luminous` (default) | Luminous anime: clean colored outlines, simplified expressive anime faces, smooth skin, broad cel shadows with selective soft edges, and airy luminous light |
| `painterly` | Painterly: more realistic anatomy and facial rendering, textured brushwork, detailed materials, and cinematic light |

Only these two styles can be selected for new requests. Luminous anime uses soft-cel
rendering and is the default. Its character rendering explicitly excludes realistic skin texture and painterly
surface detail; character sheets follow the same direction as scenes. Scene images
appear within the chapter at their planned narrative beats: before the opening prose, after an anchored passage, or at the end.
Placement after a quotation uses the containing paragraph/block boundary rather than
splitting prose. If an anchor is missing or ambiguous in the displayed text, the reader
omits that inline image instead of guessing its location. Older images without placement
metadata appear at the end. Character sheets and design notes remain in the illustration
controls; scenes have full-size image links. Generated artwork is an interpretation:
unspecified visual details are artistic choices, not new canonical story facts.
**Generate again** explicitly requests another set. Running work reports its real stage
and links to the Jobs center; the reader can continue reading while it runs.

## Prepare a chapter range

In **Manage → Illustrate ahead**, enter **From chapter** and **Through chapter**, choose
an art style, then select **Illustrate chapters**. For example, 25 through 100 prepares
the translated story chapters in that inclusive range. It includes interludes and
fractional chapter numbers, skips missing/untranslated chapters and non-story material,
and accepts at most 1,000 eligible chapters per request. Every included chapter must
contain no more than 150,000 characters of shared text.

The request schedules one durable job. Chapters run in order, allowing later scenes to
reuse character sheets and chapter-scoped name revisions established earlier in the
batch. Existing complete, current art in the selected style is skipped by default;
**Generate again for chapters that already have this art style** opts into replacements.
Leaving Manage does not stop generation. Progress and cancellation are available in Jobs;
completed art is retained if later work fails or is canceled. Range progress shows chapter
numbers and generic phases, avoiding future character names or scene titles.

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
chapter bounds the planner's story text, requested earlier context, and reusable
reference sheets. Manage may schedule future chapters before they are read, but doing so
does not advance reading progress or grant access to the resulting gallery/PNG bytes.
Future character designs are excluded even if already generated.
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
Selected prior-context chapters also retain their source hashes; edits to those chapters
invalidate dependent scenes and character sheets, including on a resumed job.
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
`{count: null, style: "luminous"|"painterly", force: false}`. Omitted or
`null` count lets the AI choose one to three scenes; explicit integers 1–3 remain
supported for legacy clients and saved jobs. The active-job
identity includes requester, novel, chapter, style and its revision, scene count, and source hash. The
OpenAI Codex host worker claims the job; API and AGY workers do not execute it.

`POST /api/novels/{id}/illustrations` schedules one range job with
`{from_chapter: 25, to_chapter: 100, style: "luminous", force: false}`. Its options
snapshot the actual eligible chapter numbers and source hashes. A resume checks those
sources before continuing; changed/deleted chapter text requires a fresh request. Each
chapter has its own saved art-plan row and prefixed image slots under the parent job.
The small parent record identifies the range; child plans are loaded individually so
each render does not read or rewrite every earlier chapter's plan.

For each chapter, the pipeline runs:

1. Verify the shared chapter source and check cancellation.
2. Ask **`gpt-6-luna` at `max` reasoning** whether preceding context is needed. This
   tool-free turn sees only the current chapter, its title/number, and character/word
   counts. It chooses **zero to three previous chapters** and a total text budget of
   **zero to 9,000 characters**. Zero chapters requires a zero budget. The prompt favors
   no history for long, self-contained chapters and a small budget for direct continuations.
3. Only after that decision, retrieve the selected number of preceding translated story
   chapters. Prefer their Codex summaries; where absent, use bounded tails of their shared
   prose. Divide the budget across those chapters and send them in story order. The budget
   limits context text; short chapter titles and JSON metadata are additional. This replaces
   the previous fixed summary/fact bundle: no broad character-fact dump is loaded.
4. Ask Luna/MAX for the art plan using the current chapter, the selected context, and
   eligible character-reference descriptions. It chooses one to three scenes unless a
   legacy request fixes the count. The host validates character keys, exact scene evidence,
   name-update evidence/name occurrences, and placement. An `after` placement must quote
   a unique exact 12–600 character passage; `start`/`end` placements have no anchor. The
   prompt forbids placing a revelation before the prose establishes it.
5. Persist the plan, context decision, supplied context, and exact chosen reference revisions.
   Retries reuse this checkpoint rather than choosing different scenes or context. The
   renderer checks Luna/MAX availability before each turn; neither planning turn has tools.
6. Checkpoint name revisions using existing sheet bytes, then render missing new character
   sheets and scenes with only their selected character images attached. Native image
   generation runs through a separate App Server turn and stops at the first completed
   image event; translation/extraction retain their tool-free runner.
7. Check freshness/cancellation around rendering and persist validated PNG bytes with
   prompts, design notes, evidence, placement, reference IDs, model/effort, and job-slot
   provenance. Unique `(job_id, slot)` records keep completed work reusable on retry. A
   deleted/invalidated plan prevents late image writes from recreating its art.

New saved plans, character references, and scenes also record a style revision:
`soft-cel-anime-v2` for `luminous` and `painterly-v1` for `painterly`. Generation reuse
and range skipping require the current revision. Older Luminous art stays readable,
but cannot seed new character references or make a new anime request appear already
complete. An old saved Luminous plan requires a fresh request rather than resuming
with a mixture of render directions. Historical `celestial`/`ink` records remain
readable and existing jobs can resume internally; new API requests reject those styles.

For each style, the reader gallery selects the newest **complete** scene batch in scene
order. Partial replacement work does not displace the previous complete set. Character
sheets are checkpointed separately and can remain available when a later scene fails.
The Art style selector changes both the visible gallery and the next generation request.

Per chapter, the scene count is bounded to three, new character designs to four, distinct
referenced characters across its whole set to four, shared source text to 150,000
characters, and each stored PNG to 16 MiB and 24 million pixels, with a host PNG decode/verification check. Normal
host-worker leases, heartbeat, cancellation, and provider-wait handling
apply. There is no image-generation API fallback and no automatic generation during a
gallery refresh. These jobs use subscription access/concurrency and provider limits;
they do not reserve a monthly `codex_builds` unit.

The UI polls every five seconds while work is active. Transient read errors retry
without starting another job. Empty or unfinished provider image results enter provider-wait handling; corrupt or
out-of-workspace image artifacts are rejected. Provider exhaustion or unavailability is shown through
the durable job state; see the [OpenAI Codex operator runbook](../openai-codex-operator-runbook.md)
for worker health, waiting jobs, and the separately authorized subscription setup.

## Understanding generation time

A chapter is a sequence of provider turns: one context decision, one scene/design plan,
then one image turn for each missing character sheet and each chosen scene. These image
turns run sequentially, and a range processes one chapter at a time. A first chapter can
therefore require up to nine turns (two planning turns, four sheets, three scenes).
Later chapters reuse eligible same-style, same-revision sheets, but newly introduced
characters still need their own images. The one-to-three scene count does not include
character sheets. Both planning turns use Luna/MAX.

Each turn creates an `ai_execution_runs` record with `created_at`, `started_at`,
`finished_at`, attempt, status, and failure code. For historical records without stage
metrics, correlate their order with saved chapter-plan timestamps and image creation
times; label that stage mapping as inferred. A run's elapsed interval includes app-server
initialization/model checks and the entire provider turn. It cannot by itself distinguish
provider-side queueing, reasoning, image-tool processing, and network transfer. Job
creation-to-first-run time measures initial queue plus worker setup; gaps between runs
include checkpointing and application work. Check failures/attempts before attributing
slow generation to retries, and distinguish canceled partial chapters from completed ones.

## Storage and HTTP

Codex owns `codex_art` (reference/scene metadata and PNG `BYTEA`), `codex_art_plans`
(single-chapter plan or small range header), and `codex_art_chapter_plans` (individual
chapter plans belonging to a range). Image bytes live in PostgreSQL, not `ASSET_DIR` or a public static
directory. Include them in normal database backup sizing. Novel deletion cascades its
art rows; plan lifetime follows the corresponding durable job. `reset-codex` also
clears the novel's generated art and saved art plans while keeping chunks/embeddings.

| Route | Result |
|---|---|
| `GET /api/novels/{id}/chapters/{chapter}/illustrations` | `items`, `can_generate`, `unavailable_reason`, and `active_job` |
| `POST /api/novels/{id}/chapters/{chapter}/illustrations` | durable `job_id`; reuse/deduplication may avoid a new job |
| `GET /api/novels/{id}/illustrations` | Manage generation availability and latest requester range job, including completed jobs; no art or chapter text |
| `POST /api/novels/{id}/illustrations` | queue one range job; returns `job_id`, `created`, and eligible `chapter_count` |
| `GET /api/novels/{id}/illustrations/{art_id}/image` | authenticated `image/png`, `Cache-Control: private, no-store` |

Gallery items expose ID, kind, title, caption, style, source chapter, prompt, design
notes, evidence, placement (`position`, `anchor`, character `offset`), and image URL.
Placement may be `null` on older records. Despite its name, `active_job` can contain the
latest failed or canceled job for the requester. The chapter gallery returns `null` for
completed work; Manage's range endpoint retains the latest completed job so its UI can
show completion. The image route
rechecks access and source validity on every fetch, including direct full-size links.
Gallery polling and source validation load metadata only; image bytes are fetched when
needed for rendering or an authenticated image response.

Implementation: `modules/codex/application/illustrations.py`,
`application/illustration_worker.py`, `application/illustration_batch.py`,
`domain/illustrations.py`, `adapters/outbound/illustration_store.py`,
`adapters/outbound/illustration_range_store.py`, and `bootstrap/illustrations.py`. AI Execution
owns `openai_codex/illustration_runner.py` and `images.py`; the frontend owns
`codex/ChapterIllustrations.jsx` and its scoped stylesheet.
