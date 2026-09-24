# Frontend overview (`novelwiki/frontend/`)

**Stack:** React 18 + React Router 6 + TanStack Query 5, built by **Vite 6**, tested with
Vitest (+ Testing Library) and **Playwright** e2e. No UI framework — hand-rolled
components and CSS custom properties. Self-hosted fonts (Newsreader for prose, Hanken
Grotesk for UI, Spline Sans Mono for code/numbers). The build output
(`novelwiki/frontend/dist`) is served **same-origin by FastAPI**, so production browsing
does not need a separate frontend server or cross-origin API requests. The backend still
configures CORS for the explicitly allowed origins.

```bash
cd novelwiki/frontend
npm ci             # install the locked dependencies
npm run dev        # Vite :5173; proxies /api, /assets/_users, /health to backend :8001
npm test           # Vitest unit/contract tests
npm run build      # production bundle → dist/
npx playwright install chromium  # first browser-test run
npm run test:e2e   # Playwright (see e2e/*.spec.js)
```

When the development backend runs on port 8000, use
`VITE_API_PROXY=http://localhost:8000 npm run dev`. Browser tests start their own Vite
server on port 4173. See [testing](../testing.md) for the disposable real-backend run.

## Structure — vertical slices mirroring the backend

```
src/
├── main.jsx                 # fonts, global styles, ReactDOM root
├── App.jsx                  # stable compat re-export; composition lives in app/Root.jsx
├── app/Root.jsx             # providers (query client, toasts, citations, auth, theme)
│                            # + the route table + auth gate + hash-URL shim
├── layouts/                 # Shell.jsx (nav chrome), NovelLayout.jsx (novel tabs),
│                            # CommandPalette.jsx (library/shared/Codex search)
├── modules/                 # ← one slice per backend module
│   ├── identity/            #    AuthScreen, Profile, Account(+Sections), api.js
│   ├── experience/          #    Home (continue reading/listening, activity), queries
│   ├── catalog/             #    Library, Discover, Overview, Manage(+Panels),
│   │                        #    AddNovelDialog, NovelHeader, tags
│   ├── reading/             #    Reader(+Parts/Toolbar), Chapters, toc, queries
│   ├── acquisition/         #    ImportView(+Parts/History) — upload/plan-review/commit
│   ├── translation/         #    glossary + translate API bindings
│   ├── codex/               #    Browser, Entity, Ask, CeilingControl, presentation
│   ├── narration/           #    audio transport components + queries
│   ├── work/                #    Jobs page, JobRow
│   └── admin/               #    Admin dashboard (+Panels)
├── shared/
│   ├── api/http.js          # THE fetch wrapper (see below)
│   └── query/useInvalidate.js
├── components/              # ui.jsx primitives, Icon, VirtualList, overlay, toast,
│                            # ProvenanceBadges
├── lib/                     # hooks, utils, constants, markdown(+citation popovers), diff
└── styles/                  # tokens.css (design tokens) → base/components/shell/screens/reader
```

**Slice rule:** each `modules/<name>/api.js` owns that frontend slice's backend calls.
The endpoint inventory is contract-frozen in
`tests/contracts/snapshots/frontend_inventory.json`. The architecture checker
mechanically bans the deleted global API/query facades and internal cross-slice imports;
endpoint-to-owner semantics remain a required snapshot/code-review check. Cross-slice
needs go through props/shared hooks or another slice's public `api.js`/`queries.js`/
`index.js`, never its implementation files.

## Routing (`app/Root.jsx`)

Signed-out: `/login`, `/register`, `/forgot`, `/reset`, `/verify`, `/verify-failed` (an auth gate
resolves the session before anything renders; a mid-session 401 re-gates and returns the
user to the interrupted URL after sign-in; a shim redirects legacy `#/…` hash URLs).

Signed-in, inside `Shell` (desktop sidebar, breadcrumb bar, mobile bottom tabs, toasts):

| Route | Screen |
|---|---|
| `/` | Reading room: featured continue-reading book with a listening shortcut when audio exists, other current books, fresh chapters, active jobs, newest shared books |
| `/library` · `/discover` · `/import` · `/jobs` | Library grid · shared-library browser · import center · unified job center |
| `/u/:username` · `/account(/:section)` · `/admin(/:tab)` | profile · account/quota settings · admin dashboard |
| `/n/:novelId` (NovelLayout tabs) | `index` Overview · `chapters` · `manage` · `codex` · `codex/e/:entityId` · `ask` |
| `/n/:novelId/read/:number` | the Reader — **full-bleed, outside Shell** |

## Reading room and library

The shell uses a forest-colored navigation rail beside a paper-colored content area.
Desktop navigation can collapse; on narrow screens primary destinations move to bottom
tabs. A skip link moves keyboard users to the main content. The reader has its own
full-screen controls and does not render the shell.

Home gives the most recent story the primary resume action. Its first-use welcome only
appears after the library, home, and activity queries succeed and there are no books, reading
activity, active jobs, or recent imports. A failed fetch displays an error and retry,
so an unavailable server does not masquerade as an empty library. Background work has
distinct loading, failed-with-retry, and empty states. Fresh-chapter links
open the actual table of contents, which supports fractional and non-contiguous numbering.

Library offers shelf tabs, title/author search, sort choices, and saved grid/list views.
Book, resume, and shelf-menu actions are separate interactive controls. Result counts,
empty-filter recovery, and request errors are explicit; shelf changes update optimistically
with rollback and an undo action.

**Add novel** and **Manage → Add source** load website choices from `GET /api/adapters`.
They show a loading state or retryable error and prevent submission until a website is
available. Choosing a website applies its language default and enables **Raw (needs
translation)** for a non-English default; both remain editable. The selected adapter's
`start_url_hint` explains whether to paste a novel page or a chapter page. Raw FuckNovelpia
also requires a **ZIP password**, sent in `source.config.archive_password` for a new
novel or `config.archive_password` for an additional source. It is not sent when a different
adapter is selected. Continuation sources validate finite chapter numbers and compute
`chapter_offset = global starting chapter − source-local starting chapter` (local defaults
to 1). **Manage → Edit source** lets an archive owner replace its ZIP password; the old
password is never read or prefilled, and leaving it blank preserves the stored value.
A password-only update does not renumber chapters. Offset edits reject invalid or
non-finite numbers. The shared setup logic lives in `catalog/useSourceAdapter.js`; the additional-source
form is `catalog/AddSourceForm.jsx`.

The search button and **Ctrl/Cmd+K** open the same focus-trapped command palette. It
searches the local library, shared books, and (inside a novel) Codex entities within the
current ceiling. Arrow keys select results, Enter opens them, and Escape closes search.
Remote results are tied to query, novel, and ceiling; changing any of these hides the old
results immediately. Partial search failures preserve available local results and show
a status message.

## Data layer

- **`shared/api/http.js`** — the single fetch wrapper: same-origin `/api` calls with
  `credentials`, the CSRF header from the `tg_csrf` cookie (and
  `x-tideglass-request: 1` on pre-auth mutations), JSON envelope/error normalization
  (`{detail}` strings and FastAPI validation arrays → readable errors with status), and
  a registered **unauthorized handler** (401 → auth re-gate, including multipart uploads).
  A malformed encoded CSRF cookie is treated as missing. Its streaming JSON transport supports both GET and POST, requests
  NDJSON, and ignores start/heartbeat frames until the final result. Recap, Ask, and first-view
  entity synthesis use it so long cache misses remain active through the proxy.
- **TanStack Query** — `staleTime` 30 s, `retry` 1, no refetch-on-focus. Slices keep
  their query definitions in `queries.js`; invalidation goes through
  `shared/query/useInvalidate.js` so mutations refresh exactly the affected keys
  (e.g. a translate job start invalidates activity + chapter lists).
- Job-progress surfaces (Jobs page, import view, audiobook status) poll their endpoints
  while a job is active.
- The Import screen accepts multi-file EPUB/PDF selection. Each file remains an
  independently reviewable job; ready jobs can be folded into a new series or appended
  as an ordered volume batch. The review exposes title, author, description, language,
  series, volume number/label, and per-section group labels; saving makes those values
  authoritative for commit. A later file with detected or user-supplied series metadata
  preselects the matching editable novel and defaults to automatic volume grouping/
  numbering.
- Import polling restarts after OCR approval and commit; failed job reads show an error
  and retry after five seconds. Switching jobs hides the previous job's review until the
  selected job loads. A series commit waits for the selected volume's own review before
  saving its edits, so retained data cannot be written to a different import.
  Upload selection and history rows support keyboard interaction,
  and segmentation controls have accessible labels. Deleting an import requires confirmation
  and removes its review data/artifacts; books already committed to the library remain.
- Codex lists and profiles hide stale data as soon as the novel, entity, or ceiling
  changes, including the ceiling's debounce interval. Ask and recap also discard their
  old text and ignore late responses after a boundary change. Loading copy describes the
  pending request without simulated processing stages. Failed browse/profile requests
  expose retry actions.

## Reader specifics

The Reader is the product's core surface: themes + accent hue (persisted, `data-theme`
on the root, CSS token-driven), column width, auto-scroll, scroll-position recovery,
volume-grouped TOC (`toc.jsx`), bookmarks, per-chapter translation editing (overlay
editor + base-vs-mine diff via `lib/diff.jsx`), provenance badges, the audiobook
transport (narration slice), and codex citation popovers (`lib/markdown.jsx` renders
answer markdown with `CiteProvider` so `[c:…]` markers open evidence popovers). Shared
anchored popovers, including the narrator picker, preserve their preferred alignment when
space permits and shift inside a 12px viewport gutter when it does not. During
audiobook playback, the reader selects the active paragraph from its actual
generation-time boundaries by comparing the player clock directly with manifest
milliseconds. It estimates the active one-or-two-sentence group only within that
paragraph, highlights it with the configured accent, and scrolls at group
transitions when needed to keep it visible. Legacy cached audio without a timing
manifest remains playable with highlighting disabled. Timed highlighting works for both
plain and imported rich chapters.
Forced regeneration remains associated with its durable job across reloads even though
the previous audio cache is still playable. The transport marks that state as updating,
polls with one in-flight request and bounded retry backoff, then replaces the stream with
the cache-busted timed audio. A transient browser fetch failure therefore no longer turns
a still-running narration job into a client-side failure.
The reader footer provides previous/next chapter buttons alongside reading position.
Arrow-key navigation is disabled inside form controls, links, editable content, dialogs,
and open reader settings/tools/contents. Focus restores the hidden reader controls.
Saved typography, width, spacing, and auto-scroll preferences are validated before use;
unavailable browser storage does not prevent the reader from opening. Bookmark mutation
failures show a message, and failed table-of-contents requests offer retry.
Auto-scroll pauses while reader settings, translation tools, or contents are open.

The reader fetches a chapter when the reader navigates to it. It does not prefetch the
next chapter's authenticated content endpoint, because that endpoint records a trusted
read and would unlock future Codex information before navigation. This is separate from
server-side translation prefetch, which prepares text without recording it as read.
Scroll saves are throttled during movement, with a final 500 ms debounce, and run only
after the current chapter has loaded. These `PUT /progress` calls update
`last_chapter`/`scroll_pct` only. The trusted spoiler ceiling advances separately when
the authenticated `GET /chapter/{number}` response is served, so a fabricated progress
PUT cannot unlock future codex data.

## Styling

[DESIGN.md](../../DESIGN.md) records the implemented visual system; its
[design sidecar](../../.impeccable/design.json) contains component samples, shadow and
motion values, and responsive breakpoints. Keep those references aligned with shared
style changes.

`styles/tokens.css` defines shared colors, dark-theme values, accent hue, spacing, type,
focus, and motion tokens; screen-specific styles build on those values. The default
accent hue is 165 (forest green), while a saved reader choice remains authoritative.
Theme toggling sets `data-theme` and persists to localStorage (`nw-theme`, `nw-accent-h`).

The Codex ceiling popover accepts an exact chapter number (including fractional chapter
numbers) and validates it against the reader's available range. Its range slider remains
available for coarse browsing, while “Follow my reading” restores the trusted latest-read
ceiling. The number field uses the mobile decimal keyboard so long books do not require
precise slider dragging. The Codex header separately shows the latest chapter with a
completed extraction checkpoint and the number of chapters built, so build coverage is not
confused with the reader's spoiler ceiling. Chunking or embedding alone does not count as a
completed build.

## Testing

- `src/app-contract.test.js` + `src/lib/api.test.js` — Vitest suites asserting the app's
  route table and API bindings match the frozen contracts.
- `src/modules/reading/narrationGuide.test.js` — sentence grouping, rich-markup
  preservation, timed-paragraph mapping, and the legacy-audio fallback.
- `src/modules/reading/narrationPolling.test.js` +
  `src/modules/reading/AudioPlayer.test.jsx` — single-flight retry/cancellation and
  reload recovery while cached audio and forced regeneration coexist.
- `src/modules/codex/spoilerBoundary.test.jsx` — stale browse/profile/Ask results are
  hidden across ceiling changes, including delayed responses.
- `src/modules/acquisition/ImportView.test.jsx` — commit/OCR polling resumes, previous
  reviews stay hidden while a selected job loads, and a series commit cannot save retained
  edits under a newly selected volume; `src/modules/reading/readerPrefs.test.js`
  exercises malformed and out-of-range persisted reader settings.
- `src/modules/catalog/sourceForms.test.jsx` — adapter loading/retry, language and raw
  defaults with explicit overrides, archive password scoping and replacement/retry,
  and finite continuation/edit offsets.
- `e2e/critical-paths.spec.js` — mocked Playwright scenarios for register→read→
  codex journeys, including mobile narration highlighting and reveal behavior.
  `e2e/real-backend.spec.js` uses the disposable fixture prepared by
  `scripts/test_real_browser.py` for the corresponding real-stack path.
- The production build itself is a release gate (`npm run build`).
