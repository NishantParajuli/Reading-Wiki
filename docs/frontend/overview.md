# Frontend overview (`novelwiki/frontend/`)

**Stack:** React 18 + React Router 6 + TanStack Query 5, built by **Vite 6**, tested with
Vitest (+ Testing Library) and **Playwright** e2e. No UI framework — hand-rolled
components and CSS custom properties, with [Motion](https://motion.dev) (`motion/react`)
for layout/presence animation. Self-hosted variable fonts: Fraunces (display),
Geist (interface), Literata (reading; Atkinson Hyperlegible Next and Fraunces are
reader options), Geist Mono (figures). The visual system is documented in
[DESIGN.md](../../DESIGN.md). The build output
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
├── app/Root.jsx             # providers (query client, motion config, toasts, citations,
│                            # auth, theme) + the route table + auth gate + hash-URL shim
├── app/lazyScreens.js       # route screens as lazy chunks (+ idle preloading)
├── app/RouteBoundary.jsx    # Suspense + recoverable error boundary per screen
├── layouts/                 # Shell.jsx (island, novel capsule, dock, ambient),
│                            # NovelLayout.jsx (novel context), CommandPalette.jsx
├── motion/                  # animation vocabulary: springs/variants (index.js),
│                            # navigation.js (view-transition history, readiness,
│                            # cover morph, theme ripple), pointerFX.js (tilt,
│                            # spotlight, ripple), TextReveal.jsx, NumberTicker.jsx
├── atmosphere/              # the living background: TideCanvas (WebGL), Ambient
│                            # (water + cover aura + grain), cover palettes, store,
│                            # OceanScene (the sign-in sea)
├── modules/                 # ← one slice per backend module
│   ├── identity/            #    AuthScreen(+Parts), Profile(+Parts), Account (+Nav/
│   │                        #    Parts/Sections/Appearance/Reading/Usage), api.js
│   ├── experience/          #    Home (+MoonPhase), NotFound, queries
│   ├── catalog/             #    Library, Discover, Overview, Manage(+Sections/Kit/
│   │                        #    Panels), AddNovelDialog, NovelHeader(+HeroParts), tags
│   ├── reading/             #    Reader(+Parts/Toolbar/Settings), TranslationTools, Chapters,
│   │                        #    toc, queries
│   ├── acquisition/         #    ImportView(+Basin/Detail/Review/Parts/History),
│   │                        #    importStatus, NovelpiaCookies
│   ├── translation/         #    glossary + translate API bindings
│   ├── codex/               #    Browser, Entity(+Parts), Ask, CeilingControl, parts,
│   │                        #    typeReveal, ChapterIllustrations
│   ├── narration/           #    audio transport components + queries
│   ├── work/                #    Jobs page, JobRow
│   └── admin/               #    Admin (+Panels/Users/Workers/Parts)
├── shared/
│   ├── api/http.js          # THE fetch wrapper (see below)
│   └── query/useInvalidate.js
├── components/              # ui.jsx primitives, Icon, GeneratedCover, VirtualList,
│                            # overlay, toast, ProvenanceBadges
├── lib/                     # hooks, utils, constants, markdown(+citation popovers), diff
└── styles/                  # tokens → base → ambient → components → shell → transitions,
                             # surfaces/<area>.css per screen area, reader.css
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

Screens are lazy chunks (`app/lazyScreens.js`) warmed while the browser is idle after
sign-in; a chunk that has arrived resolves synchronously, so its screen renders without
suspending. Each renders inside `RouteBoundary`: a quiet loading orb while its chunk
arrives, and a recovery card if it fails — a missing chunk after a deploy offers
**Reload** into the new version; a render error offers **Reload** or **Try again**.

The router is `unstable_HistoryRouter` over a transition-aware history
(`motion/navigation.js`). Every push, replace or back/forward that changes the path
runs inside a View Transition; query-only changes (filters, search) and the first
paint never animate, and reduced motion or unsupported browsers navigate instantly.
`<html data-vt>` names the kind of move for `styles/transitions.css`: `page`, `pop`
(back/forward), `tab` (account/admin sections), `novel-tab`, `enter-reader`,
`exit-reader`, `chapter-next`/`chapter-prev` (a wave-edged tide wash) and `theme`.
A destination can hold the previous frame briefly until its data is on screen:
`NovelLayout` signals `novel:<id>`, the reader `chapter:<id>:<number>`, Home `home`
(`useReadySignal`; at most ~0.5–0.9s), and every transition also waits while a
`RouteBoundary` loading orb is on screen, so a first visit morphs into the page rather
than the orb. Clicking a book link names that jacket `hero-cover`, and the novel hero
carries the same name, so the cover flies into place; when a hero is already on
screen it keeps the name itself and morphs into the next one.

Signed-in, inside `Shell` (island header, novel capsule, mobile dock, toasts):

| Route | Screen |
|---|---|
| `/` | Reading room: featured continue-reading book with a listening shortcut when audio exists, other current books, books with unread chapters waiting, active jobs, newest shared books |
| `/library` · `/discover` · `/import` · `/jobs` | Library grid · shared-library browser · import center · unified job center |
| `/u/:username` · `/account(/:section)` · `/admin(/:tab)` | profile · account/quota settings · admin dashboard |
| `/n/:novelId` (NovelLayout tabs) | `index` Overview · `chapters` · `manage` · `codex` · `codex/e/:entityId` · `ask` |
| `/n/:novelId/read/:number` | the Reader — **full-bleed, outside Shell** |
| any other path | "Lost at sea" (`experience/NotFound.jsx`): the unknown path, a bobbing bottle, and links home, to the library, and to search |

A signed-in visit to `/login`, `/register`, `/forgot`, `/reset` or `/verify-failed`
redirects home; `/verify` still opens so an email link can be confirmed while signed in.

**Settings → Source accounts** (`/account/sources`) renders the Acquisition slice's
`NovelpiaCookies` through its public export. Users paste an EditThisCookie JSON array,
save or replace their own login cookies, and remove a saved connection (after confirming
in a dialog; chapters already imported are kept). The field is
never populated from stored values, clears after successful saving/removal, and is not
persisted in browser storage. The screen shows cookie names/expiry dates and the last
update, with loading/retry and save-error feedback. Replacement and removal remain
available when saved status cannot be read, including after an encryption-key change.
“Cookies saved” reports local storage status, not a live Novelpia login check; the page
explains that the site's plan and ad requirements still apply. Expiry dates are storage deadlines, not guaranteed
session lifetimes. The account API returns metadata only. Choosing Novelpia Global in
Add novel or Add source also shows a Source accounts link; it opens in a new tab so the
unfinished novel/source form is preserved. During automatic ad completion, Jobs shows
**Watching Novelpia ad** or **Waiting for Novelpia browser**. Recognized Novelpia errors
in expanded failed Jobs details and Manage health offer **Open chapter on Novelpia**
for an official numeric viewer URL, or **Update Novelpia cookies** for login errors.
These links open in a new tab, preserving the current screen. Arbitrary error URLs are
not converted into links.


## Reading room and library

The shell floats its chrome over a living background (`atmosphere/Ambient.jsx`): a
WebGL tide (`TideCanvas` — aurora over water, thin caustic light, a faint star field
after dark in the Tide theme) in the accent's or current book's hues, the focused
book's jacket as a blurred aura, and film grain. Screens claim the room with
`useBookAtmosphere(novel)` (Home for the book you're in, every `/n/:id` route through
`NovelLayout`, and the reader). The water renders at reduced resolution, caps at
~30fps, pauses when the tab is hidden, and paints one still frame under reduced
motion or the **Ambient motion** preference (`localStorage` `nw-ambient`:
`living`/`still`/`off`; Account → Appearance). Without WebGL it falls back to CSS
gradients.

A floating glass **island** header holds the brand, the primary destinations (Home,
Library, Discover, Import, Jobs with an active-job badge) with a sliding active pill,
search (Ctrl/Cmd+K; its button is labelled "Search (Ctrl+K)"), the theme switch —
the new theme spreads from the button as a circular reveal — and the account menu
(profile, settings, admin, sign out, quota meters; "Usage is unavailable right now."
when quotas fail to load). It condenses as the page scrolls, and a frosted band then
blurs content sliding beneath the islands (it sits under the novel capsule and sticky
toolbars, which stay crisp). Between 768 and 880px the island shows icons with
tooltips, keeping each label for assistive technology; below 1320px the search pill
drops its shortcut hint. Inside a book, a sticky **novel capsule** shows the cover and
title with Overview, Chapters, Codex/Ask (when the Codex is enabled) and Manage
(owners/admins, with a badge for pending contributions and tag suggestions). On phones
only the active section keeps its visible label, the capsule scrolls it into view, and
below 480px the cover alone stands for the book. Below 768px the destinations move to
a floating bottom **dock** (Home, Library, Discover, Jobs, You) and the top bar hides
while scrolling down. The offline banner sits beneath the capsule. A skip link moves
keyboard users to the main content. The reader has its own full-screen controls and
does not render the shell.

Dialogs and drawers portal to the page root (`components/overlay.jsx`), so a glass or
animated ancestor can never trap or clip them; the reader provides its own host
(`OverlayHostProvider`) so they keep its tone. Popovers (menus, the Codex gauge, the
narrator picker) open toward the larger room between the header and the phone dock,
scroll within the height they get, and hand focus back to their trigger when Escape or a
choice closes them. Loading buttons stay focusable (`aria-busy`, `aria-disabled`) and
ignore repeat presses; tabs follow the ARIA pattern (one Tab stop; arrows, Home and End
move and select). Keyboard focus draws a glowing ring that outranks component shadows
and follows each control's shape. Books without art get generated jackets whose title
size follows the longest word, so words wrap whole.

A novel route that can't load says so: a missing or private book (404/403) shows "This
book isn't here" with links to the library and Discover; any other failure shows
"Couldn't open this book" with **Try again**. The novel capsule is hidden in both cases.
The capsule's cover link is a pointer shortcut outside the tab order; its navigation is
named after the book. On short landscape screens the header tucks away while scrolling
down, as on phones.

Home greets the reader by time of day under a drawing of the moon at its current
phase, then gives the most recent story a spotlight: the jacket floats with a
reflection in a card tinted by the cover, with a progress ring, the resume chapter
and its title, Continue reading, and Listen when audio exists. Beside it are
shortcuts (collection count, Discover, Import) and live background work. Rails show
the rest of the nightstand and the newest shared books, each ending in a glass tile
onward (the library, Discover). **Chapters waiting** lists books with chapters beyond
the reader's furthest read (the API's `new_chapters`, an unread count rather than a
count of recently added chapters), most recently updated first; each row shows that
count and opens the actual table of contents, which supports fractional and
non-contiguous numbering.
On phones the spotlight sets the jacket beside the title with the resume action across
the card, so it stays above the dock. Its first-use welcome only appears after the
library, home, and activity queries succeed and there are no books, reading activity,
active jobs, or recent imports. If the home query fails, the spotlight slot says so
with a retry while the shortcuts and background work (separate queries) stay, so an
unavailable server does not masquerade as an empty library. Background work has
distinct loading, failed-with-retry, and empty states.

Library is the reader's shelf of book covers. Shelf tabs (All, Reading, To read,
Completed) carry live counts; title/author search highlights matches (`/` focuses it,
Escape clears); four sorts and a grid/list toggle are remembered in `localStorage`
(`nw-lib-tab`, `nw-lib-view`, `nw-lib-sort`). On desktop the toolbar docks under the
island while scrolling. The header summarises real figures only: the number of books
and chapters read (the sum of `max_chapter_read`). Covers tilt toward the pointer;
Resume/Start and the shelf menu rise on hover or focus and stay visible on touch — the
cover link, resume link and shelf menu are separate controls. Reading state is a slim
progress line with the resume chapter and last-read time, a gold "N unread" tab when
`new_chapters` > 0, and "Finished" on the Completed shelf. Changing shelf, search or
sort re-flows the books with layout animation (the first 48 animate) and switching
grid/list flies each cover to its new place. Lingering on a book with a mouse tints the
room with its cover (`useBookAtmosphere`; off under reduced motion). Loading shows
skeleton covers and signals route readiness; a failed load shows "Your library couldn't
load" with Try again; an empty library offers three ways in (add from the web, import a
file, browse Discover); empty shelves and searches offer a way back. Shelf moves and
removals update optimistically with rollback and Undo.

Discover presents the shared library as a front page. Search is debounced into `?q=`;
filter pills with menus (language, translation, genre/status tag, freshness), toggles
(has Codex, has audio) and the sort live in the URL (`lang`, `tr`, `tag`, `fresh`,
`codex`, `audio`, `sort`). On phones the filters open in a bottom sheet showing the live
result count. While browsing — no search or filter, sorted by recency or freshness — the
first three results form a featured strip (large cover, blurb and feature tags over the
book's own light, which also tints the room); the rest of the shelf follows. Searching or
filtering shows a results grid; new results replace the old in place while the previous
shelf stays visible, dimmed, until the response arrives. **Load more** fetches 60 at a
time behind a "Showing N of M" meter. Adding is optimistic: the button turns to "In
library", a copy of the cover flies into the Library link in the island (desktop) or
dock (phones) — skipped under reduced motion and never delaying the request — and a
toast offers Open; failures roll back with the server's message. A failed request shows
an error with Try again rather than an empty shelf.

Profiles show a glowing avatar orb, name, handle, join date and bio, the book being
read, four real reading figures and shelves (currently reading, recently finished,
published) whose books rise in as they scroll into view, or are simply there under
reduced motion; the room takes the colours of the current book. Account settings use a
grouped side nav (a scrolling pill row on phones); section changes only swap the panel.
**Appearance** offers Tide/Pearl preview cards (the theme spreads from the chosen card),
accent hues as sea-glass pebbles — Sea glass 192 (default), Lagoon 165, Abyss 245,
Amethyst 295, Coral 22, Lantern 75, Kelp 140 — which glide across the interface and are
saved to `prefs.appearance.accent_h` (applied at sign-in on every device), and **Ambient
motion** (Living water / Still / Off). **Reading** has a live page preview; **Usage**
shows ring gauges with the remaining quota and reset date, and a failed usage request
says so with Try again. Each gauge's progressbar carries its real value from the start;
with motion allowed only the ring's stroke waits empty until the gauge is on screen and
then fills, and under reduced motion it is drawn full at once. Admin keeps its tabs
(a row that scrolls sideways below 1024px, with a fade at its right edge on phones):
users with quota and AI-access editors and guarded role/status/delete actions —
**Make admin**/**Demote** and a change to *banned* ask for confirmation in a dialog, and
deleting needs the username typed — usage with a chart of the months on record (up to
six, "Last N months"; a picture for pointers, hidden from assistive technology, with the
table beneath as the accessible version), moderation, global jobs, and worker health
with live status. List failures show Try again instead of an empty list; **Run consuming
smoke test** asks first (it spends subscription quota), and smoke-test/retry results
confirm with a toast.

Novel pages share one hero (`catalog/NovelHeader.jsx` + `NovelHeroParts.jsx`): full
on Overview, compact on Chapters and Manage, with the jacket morphing between the two on
tab switches. It shows the title in large display type scaled to its length, the author,
a fact strip (chapters, range, language, edition, visibility), the synopsis (clamped, with
More/Less), the shelf control and the ⋯ menu (type-to-confirm delete), and actions:
**Continue · Ch. N** with a progress ring and that chapter's title, or **Start reading**;
**Listen** only when audio exists; **Codex**; **Narrate book**. A tideline spans the whole
book with the read part lit, a "You are here" marker, bookmarks as gold pins and volume
ticks, and reads "N% read · N unread" ("caught up" when nothing is left; "Not started
yet" before the first chapter); it is a progressbar with a spoken summary. Section navigation lives in
the shell's novel capsule. Overview lists the latest chapters (unread dots, a "Reading"
tag on the current one) and bookmarks (removal is optimistic with rollback and an error
toast), beside a column with Codex counts (shown only when stats for the current
boundary have loaded), tags with **Suggest tags**, and sources with provenance.
Chapters has a sticky glass bar with search ("Search chapters") and sort, a **You're on
Ch. N** locator that opens the right volume and centres and focuses the current chapter,
and **Go to #** ("Jump to chapter number"), which says "No chapter X in this book" when
the number is missing. Volumes open with a height animation and a read meter, and the
open volume's header pins under the bar where CSS scroll-state queries are supported.
The reader's contents drawer opens on the current chapter the same way. Manage is a
sequence of numbered sections with jump links: **Inbox** (only when something is
waiting), Content, Processing (a three-step pipeline: fetch, translate raws, build the
Codex), Illustrations, Sharing & details (radio cards for visibility and reader edits),
Activity & health, Glossary and Danger zone. Jobs, health and glossary each show
loading, empty, and failed-with-retry states, and accepting or rejecting an inbox item
refreshes the capsule's Manage badge. Add novel is a glass sheet; Add and Edit source
open inline beneath the source list.

Import (`/import`) puts a glass drop basin and the **Recent imports** shelf in a left
column and the selected import on the right (one column below 960px, where choosing an
import scrolls it into view). The selected import lives in the URL (`/import?job=<id>`,
replaced rather than pushed as you choose), so a link or a reload opens it. Dragging
files over the window lights the basin's rim and lifts the water a little; over the
basin it rises further — still below the prompt, which reads "Release to add your
books" — and while uploading the water level is the upload percentage with "Book 2 of
3 · filename". A filename standing in for a title drops its `.epub`/`.pdf` extension,
and truncated titles in the shelf show the full title on hover.
Files dropped outside the basin are ignored instead of opening in the browser. A
tideline stepper marks each step as done, in progress, waiting for you, or failed
(announced to screen readers). The detail header shows the jacket, metadata, status,
stats, failing quality checks and a quality ring, and the room takes the book's colours.
OCR approval shows the estimate and **Run OCR**; failures show the error with **Delete
import**, even without a server reason. The review keeps a ruled segment list (inline
titles, kind and number pills, merge/split with focus handed to the surviving row) and a
sticky commit bar that collapses to "Destination + Commit" on phones; keyboard focus
scrolls clear of the sticky segment header and the commit bar (a scroll padding while
the review is open). **Replace chapters** asks for confirmation in a dialog naming the
source and novel, since it deletes that source's current chapters. Jobs (`/jobs`) has
live counters (Running, Queued, Waiting, Needs you) and Active/History tabs with counts
(no Active count until the list has arrived, so a slow or failed load never reads "0"),
groups jobs by novel beside its cover, and gives each row a status orb, live progress,
the AI backend by name (API, Antigravity, OpenAI Codex, and "OpenAI Codex → API" after a
fallback) and cancel. An import that needs you links to its step: **Review** or
**Approve OCR** opens `/import?job=<id>`. Failed rows open a keyboard-accessible **Show
error** disclosure (`aria-controls` names the panel) with **Copy** (a failed copy is
reported) and the Novelpia recovery links. A failed list reads "Couldn't load jobs" with
**Try again**, never "No active jobs"; empty states link to history, Import and the
library, and finished rows show only real progress.

Signing in opens on a real-time WebGL sea (`atmosphere/OceanScene.jsx`): a moonlit
night in Tide and a dawn in Pearl, coloured from the accent hue. The "Tideglass"
wordmark rises letter by letter out of the waterline with a swaying reflection, and the
form floats on a glass card whose height morphs between sign-in, registration and
recovery; these modes do not cross-fade the page, so the sea keeps moving. The canvas
and wordmark share `--ocean-horizon`, `--ocean-moon-*` and `--ocean-sun-*` so the
wordmark's baseline sits on the horizon. The sea renders at most 0.64 MP (less on
touch and software renderers), caps its frame rate, pauses when hidden or scrolled
away, paints one still frame under reduced motion, falls back to a CSS gradient if
WebGL fails, and releases its context on unmount. On short phones the sea is shallower
(360×740 keeps **Sign in** on the first screen) and on phones held sideways the sea and
wordmark shrink so the form starts within the first screen. Each field's label names
only its input; a validation note below it is the input's description
(`aria-describedby`) and marks it `aria-invalid`. The password's eye is a toggle
reachable by keyboard ("Show password", pressed while the password is visible). An
`?error=oauth` message stays visible until the mode changes.

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
a status message. Outside a book the placeholder offers stories only, and on touch
screens the keyboard hints give way to "Tap a result to open it." Screens can open the
palette with a `tg-open-palette` window event (the not-found page's Search button does).

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
- Job-progress surfaces (Jobs page, import view, audiobook status, chapter illustrations) poll their endpoints
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
on the root, CSS token-driven), reading tones, typefaces, column width, auto-scroll,
scroll-position recovery, volume-grouped TOC (`toc.jsx`), bookmarks, per-chapter
translation editing (overlay and shared-text editing), provenance badges, the audiobook
transport (narration slice), and codex citation popovers (`lib/markdown.jsx` renders
answer markdown with `CiteProvider` so `[c:…]` markers open evidence popovers).

Its chrome is two floating glass capsules. The top capsule holds back, contents, the
book and chapter titles, the position (`119 / 240`), bookmark, the **Aa** reading
settings and translation editing (with a conflict badge); the bottom capsule holds
previous/next and a progress ring with percent read and minutes left. Both recede on
scroll-down and return on scroll-up, a tap on the page, or keyboard focus; only
keyboard focus (`:focus-visible`) holds them, so a mouse or touch press on Play still
lets them recede. Restoring a saved scroll position does not hide them. The capsules
themselves carry the view-transition names (`reader-top`, `reader-bottom`), so their
glass blurs the page beneath. If a chapter fails to load, the top capsule still names
"Chapter N" and the error says the reader's place is saved. A 3px tideline across the
top edge shows progress. Each chapter opens with an engraved numeral, the title, a drawn ornament and
reading time; the first paragraph has a drop cap and small-caps first line. The first
chapter of a visit settles in with a short entrance (prose readable within ~0.8s);
moving between chapters uses the tide wash transition instead.

Reading settings (`ReaderSettings.jsx`, a "Reading settings" dialog rendered at the
reader root) open as a popover under **Aa** on desktop and tablet — kept inside the
viewport and re-placed on resize — and as a bottom sheet on phones, where the width
control is hidden. Opening moves focus to the panel's title; Tab cycles within it;
Escape or × close it and return focus to **Aa**. Tone and font are radio groups with
one Tab stop (arrows, Home and End move and select). The body fades at an edge while
more remains to scroll. Five tones — **Theme** (follows the app theme; its swatch shows
the app theme), **Paper**, **Sepia**, **Dusk** and **Night** (true black) — re-map the
theme tokens on `.reader`, including status colours, gold, atmosphere, scrim, the focus
ring and the page behind the reader, so the chrome follows the page (light tones take
Pearl's status set, dark tones Tide's). Four typefaces (Literata, Fraunces, Geist,
Atkinson Hyperlegible Next); size, line height, width, justify/indent switches and
auto-scroll, with a live preview. Saved values are validated (`loadReaderPrefs`) before
use; unknown tones or fonts fall back to the defaults, and unavailable browser storage
does not prevent the reader from opening.

Narration lives in a floating dock above the bottom capsule: a compact pill (voice,
**Narrate chapter**) until audio exists, then a player with ±15s skips, play/pause
ringed by progress, a tide-line seek bar (an even swell that drifts while playing and
settles when paused; it carries no audio data), speed, voice and regenerate. While the
chrome is hidden and audio is playing, the dock shrinks to a corner mini-player. Shared
anchored popovers, including the narrator picker, preserve their preferred alignment
when space permits and shift inside a 12px viewport gutter when it does not; they open
upward when the room below can't hold them and the room above is larger (so the
narrator menu rises out of the dock). Toasts and the first-visit hint ("Click" or "Tap
the page to show or hide controls", by pointer type) sit above the bottom chrome.
During audiobook playback, the reader selects the active paragraph from its actual
generation-time boundaries by comparing the player clock directly with manifest
milliseconds. It estimates the active one-or-two-sentence group only within that
paragraph, highlights it with the configured accent, and scrolls at group
transitions when needed to keep it clear of the top capsule, the bottom capsule and
the dock. Legacy cached audio without a timing manifest remains playable with
highlighting disabled. Timed highlighting works for both plain and imported rich
chapters. Forced regeneration remains associated with its durable job across reloads
even though the previous audio cache is still playable. The transport marks that state
as updating, polls with one in-flight request and bounded retry backoff, then replaces
the stream with the cache-busted timed audio. A transient browser fetch failure
therefore no longer turns a still-running narration job into a client-side failure.

The end of a chapter is marked by a drawn wave, a sealing check with a small burst of
light when it scrolls into view, and the next chapter's number and title with **Next
chapter** (or **Translate & continue** for a raw chapter), plus Previous, Contents and
the book's page. Pictures in rich chapters open in a lightbox dialog (also by Enter or
Space) that traps focus, closes on Escape and returns focus to the picture.
Arrow-key navigation is disabled inside form controls, links,
editable content, dialogs, and open reader settings/tools/contents. Focus restores the
hidden reader controls. Bookmark mutation failures show a message, and failed
table-of-contents requests offer retry. Auto-scroll pauses while reader settings,
translation tools, or contents are open.

**Translation workspace.** `reading/TranslationTools.jsx`, re-exported from
`ReaderParts.jsx`, opens a portaled, focus-trapped dialog. Desktop shows the chapter
editor beside a live plain-text reading preview; mobile switches between Edit and
Preview. The chapter title, sharing scope, word count, unsaved state, and persistent
save footer remain visible. Ctrl/Cmd+S saves. Closing through Escape, the close button,
or the backdrop asks before discarding a changed draft; browser reload warns while a
draft is dirty or a write is in progress. Failed saves preserve the draft. Closing
restores focus and the reader's scroll position.

Shared edits, personal overlays, conflict merge/keep/base choices, retranslation,
contribution, and reverting a personal copy retain their existing endpoints.
Contribution requires saved, conflict-free text; replacing a dirty draft through
retranslation or conflict resolution is guarded. Reverting confirms deletion of the
personal copy. The dedicated `TranslationTools.css` scopes this workspace's layout.

**Chapter illustrations.** `codex/ChapterIllustrations.jsx` loads available art when
its chapter opens, while its generation controls remain collapsed after the prose.
Scenes appear at the opening, after an anchored passage, or at the end of the story,
independently of whether the controls are open. Plain prose retains its original
paragraph and narration indices; rich HTML keeps its sanitized markup and narration
spans, inserting React figures into dedicated slots outside the text. Unknown or
ambiguous anchors are omitted rather than inserted at an unrelated passage. Shared
illustrations are hidden while a personal translation or conflict overlay is displayed.

Eligible owners/admins choose **Luminous anime** (soft-cel anime, the default) or
**Painterly** (semi-realistic painted illustration) and explicitly generate. These are
the only two selectable styles, each with a short description. AI selects one to three
scenes; there is no image-count field. Each chapter initially selects Luminous anime,
even if it only has Painterly art. The style selector switches inline scenes and
reference sheets together. Historical Celestial/Ink images remain accessible under
**Earlier illustrations**, without reintroducing those styles into the selector. Character
sheets remain under a disclosure, and full-size links use authenticated image endpoints.
Opening the chapter or controls never starts generation. Generate again requests a fresh
set while retaining the current art during processing.

**Manage → Illustrate ahead.** The novel management screen accepts an inclusive first
and final chapter and one of the same two styles, defaulting to Luminous anime.
Existing illustrations in that style and its current revision are skipped by default; the explicit replacement checkbox requests regeneration. The background range
job processes chapters in order to carry character designs forward. Its status survives
navigation, reports waiting/failure/completion, and links to Jobs for progress and
cancellation. Preparing upcoming chapters does not mark them read or reveal their art
before the reader's trusted chapter boundary permits it.

Both illustration surfaces poll every five seconds only while work is queued, running,
or waiting for the provider, and stop on terminal state. Errors preserve completed art
and expose a retry or refresh action. Navigation discards late responses so another
chapter or novel's state cannot appear in the new view. Source, generation, and viewing
boundaries are described in [chapter illustrations](../pipelines/chapter-illustrations.md).

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

`styles/tokens.css` defines the two themes — **Tide** (dark) and **Pearl** (light) —
with colors, the accent hue, atmosphere hues, type, spacing, radii, shadows, glass
edges, focus and motion tokens; every other stylesheet builds on those values.
`base.css` holds resets and the shared entrance choreography (`.page-enter`, `.rise`
with a `--i` stagger, scroll-driven `.reveal-on-scroll`); `ambient.css` the living
background; `components.css` the shared primitives; `shell.css` the island, capsule and
dock; `transitions.css` the view-transition choreography; `surfaces/<area>.css` each
screen area; `reader.css` the reader and its tones. The default accent hue is 192 (sea
glass); a saved choice remains authoritative, except that the previous design's
implicit default (165) is moved to 192 once (`nw-design` marks the migration). Theme
toggling sets `data-theme` and persists to localStorage (`nw-theme`, `nw-accent-h`);
an inline script in `index.html` applies both before first paint.

Pointer effects are installed once (`motion/pointerFX.js`): `data-tilt` tilts covers
toward a fine pointer with a glare, `data-spotlight` lights a card's edge under the
cursor, and buttons emit a ripple from the press point. `<MotionConfig
reducedMotion="user">` and a global reduced-motion rule collapse animation while
keeping every state and action.

The Codex ceiling popover accepts an exact chapter number (including fractional chapter
numbers) and validates it against the reader's available range. Its range slider remains
available for coarse browsing, while “Follow my reading” restores the trusted latest-read
ceiling. The number field uses the mobile decimal keyboard so long books do not require
precise slider dragging. The Codex header separately shows the latest chapter with a
completed extraction checkpoint and the number of chapters built, so build coverage is not
confused with the reader's spoiler ceiling. Chunking or embedding alone does not count as a
completed build.

The Codex treats the boundary as a water line. Its trigger is a glass pill ("Bounded to
Ch. N") with a small orb filled to the boundary's depth; the popover rolls the chapter
numeral and keeps the exact-chapter form, a tide-staff slider, the revealed count and
**Follow my reading**. The browser counts real `/stats` figures up, lists entities as
cards (links, so they open in a new tab) with type-tinted orbs, and ends in a frosted
"still under the tide" panel over redacted placeholders with **Continue reading**. When
the boundary rises, newly revealed cards surface with ripples and a "New" chip; "new" is
measured against the list the reader last saw, so a fresh visit does not flag entries.
An entity dossier opens with a large orb (it flies in from the card on repeat visits),
identity reveals, the entry in the reading face, "What's known" as a chapter-grouped
tideline, relationships with a small connections map drawn only from returned
relationships, and **Show through Ch. N** when the entity lies beyond a lowered
boundary; its loading hero shows the clicked name only when it was listed at the same
boundary. Ask's question field is multi-line (Enter sends, Shift+Enter adds a line);
answers reveal line by line (instantly under reduced motion) with the whole text in the
DOM. Citations are numbered keyboard buttons whose source popover follows its chip on
scroll and closes on Escape (returning focus), an outside click or focus moving away;
a numbered sources list sits under each answer.

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
- `src/modules/codex/ChapterIllustrations.test.jsx` — explicit generation, active-job
  polling/recovery, unavailable access, preserved galleries, and discarded late responses
  after chapter navigation. `e2e/illustrations.spec.js` exercises desktop/mobile controls, range generation, and inline placement
  and verifies opening the panel does not generate images.
- `src/modules/reading/ReaderSettings.test.jsx` — rendering at the reader root, focus on
  open and its return on Escape/close, radio-group arrow keys, and clicks that stay out
  of tap-to-hide; `src/modules/reading/RichContent.test.jsx` — the image lightbox's
  labelled modal, Escape and focus return, and its close button.
- `src/modules/reading/TranslationTools.test.jsx` — shared/personal editing, conflict
  actions, draft protection, keyboard save, failed-write recovery, and contribution/revert
  controls. Editor browser scenarios in `e2e/critical-paths.spec.js` cover desktop/mobile
  space, preview switching, and draft protection.
- `src/modules/acquisition/NovelpiaCookies.test.jsx` — saved/expired status, JSON
  validation, successful replacement and field clearing, confirmed removal (and a
  cancelled one that keeps the cookies), request failures, and replacement/removal
  recovery after unreadable saved status.
- `src/modules/acquisition/ImportView.test.jsx` — `?job=` opens that import and follows
  the chosen one, commit/OCR polling resumes, previous reviews stay hidden while a
  selected job loads, and a series commit cannot save retained edits under a newly
  selected volume; `src/modules/reading/readerPrefs.test.js`
  exercises malformed and out-of-range persisted reader settings.
- `src/modules/identity/Account.test.jsx` — section routes, theme/accent/ambient
  pickers, reading/audio/password saves, an honest usage error, and gauges that report
  their real value before they scroll into view (filled at once under reduced motion);
  `src/modules/identity/Profile.test.jsx` — loading, error and empty profile states, and
  shelves that show without motion; `src/modules/admin/Admin.test.jsx` — admin guards and
  self-guards, quota/AI-access editor saves, confirmed bans and role changes,
  type-to-confirm delete, tab routes and panel naming, the usage chart hidden behind its
  table, moderation, global jobs, worker health and the confirmed smoke test.
- `src/modules/catalog/Library.test.jsx` + `Discover.test.jsx` — shelves, search, sorts and
  saved views, optimistic shelf moves with undo, URL-synced filters, paging, optimistic
  add with rollback, and honest error states.
- `src/components/ui.test.jsx` + `overlay.test.jsx` — tab keyboard pattern, focusable
  loading buttons that ignore presses and form submits, popover focus return, and
  popover viewport positioning.
- `src/modules/catalog/novelHero.test.jsx` — honest figures, the fact strip, and the
  tideline's progress, place, bookmarks and not-started states; `src/modules/reading/toc.test.jsx`
  — volume grouping, the current volume and read state, opening rows, and list windowing.
- `src/modules/acquisition/ImportFlow.test.jsx` — the import tideline, OCR progress, the
  review's commit summary and unnumbered-chapter flags, the confirmed **Replace
  chapters**, filename titles without extensions, and the basin's drop invitation;
  `src/modules/work/Jobs.test.jsx` — grouping, live progress and cancel, links from
  imports that need you, the copyable error disclosure (`aria-controls`) with Novelpia
  recovery, no Active count before the list loads, the load-failure retry, backend names
  and finished-row wording.
- `src/modules/identity/AuthScreen.test.jsx` — labels, modes, validation (errors as
  descriptions with `aria-invalid`, never part of the field's name), providers, the
  keyboard-reachable password toggle and its pressed state, and the `?error=oauth` message.
- `src/modules/catalog/sourceForms.test.jsx` — adapter loading/retry, language and raw
  defaults with explicit overrides, archive password scoping and replacement/retry,
  and finite continuation/edit offsets.
- `e2e/critical-paths.spec.js` — mocked Playwright scenarios for register→read→
  codex journeys, including mobile narration highlighting and reveal behavior.
  `e2e/real-backend.spec.js` uses the disposable fixture prepared by
  `scripts/test_real_browser.py` for the corresponding real-stack path.
- The production build itself is a release gate (`npm run build`).
- `e2e/showcase/` is a visual-review harness, not a test suite: `shoot.mjs` starts its
  own Vite server with the synthetic fixtures in `fixtures.mjs` (novels with covers
  and generated jackets, chapters, an inline illustration, Codex, jobs, users) and
  captures any route across themes and viewports, optionally as frame strips after
  load or after a click:

  ```bash
  node e2e/showcase/shoot.mjs --routes /,/library,/n/1/read/5 \
    --themes dark,light --viewports desktop,mobile --out /tmp/tideglass-shots
  ```

  `--signed-out` renders the sign-in screens; `SHOWCASE_BIG_LIBRARY=1` renders a
  60-book library and `SHOWCASE_EMPTY=1` a new account. `fixtures-codex.mjs` adds
  boundary-aware entities, cited answers and illustration plates; `fixtures-novel.mjs`
  adds an owner inbox (`/n/3/manage`), an unscraped book (`/n/15`) and a very long
  title (`/n/16`); `/n/404` and `/n/500` render a missing book and a failed load. All
  stories and people in the fixtures are invented.
