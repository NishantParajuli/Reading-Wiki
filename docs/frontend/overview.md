# Frontend overview (`novelwiki/frontend/`)

**Stack:** React 18 + React Router 6 + TanStack Query 5, built by **Vite 6**, tested with
Vitest (+ Testing Library) and **Playwright** e2e. No UI framework — hand-rolled
components and CSS custom properties. Self-hosted fonts (Newsreader for prose, Hanken
Grotesk for UI, Spline Sans Mono for code/numbers). The build output
(`novelwiki/frontend/dist`) is served **same-origin by FastAPI** — no separate frontend
server, no CORS in production, cookies just work.

```bash
cd novelwiki/frontend
npm run dev        # Vite dev server (proxies /api to the backend)
npm test           # Vitest unit/contract tests
npm run build      # production bundle → dist/
npm run test:e2e   # Playwright (see e2e/*.spec.js)
```

## Structure — vertical slices mirroring the backend

```
src/
├── main.jsx                 # fonts, global styles, ReactDOM root
├── App.jsx                  # stable compat re-export; composition lives in app/Root.jsx
├── app/Root.jsx             # providers (query client, toasts, citations, auth, theme)
│                            # + the route table + auth gate + hash-URL shim
├── layouts/                 # Shell.jsx (nav chrome), NovelLayout.jsx (novel tabs)
├── modules/                 # ← one slice per backend module
│   ├── identity/            #    AuthScreen, Profile, Account(+Sections), api.js
│   ├── experience/          #    Home (continue reading/listening, activity), queries
│   ├── catalog/             #    Library, Discover, Overview, Manage(+Panels),
│   │                        #    AddNovelDialog, NovelHeader, tags
│   ├── reading/             #    Reader(+Parts), Chapters, toc, queries
│   ├── acquisition/         #    ImportView(+Parts) — upload/plan-review/commit
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

Signed-out: `/login`, `/register`, `/reset`, `/verify`, `/verify-failed` (an auth gate
resolves the session before anything renders; a mid-session 401 re-gates and returns the
user to the interrupted URL after sign-in; a shim redirects legacy `#/…` hash URLs).

Signed-in, inside `Shell` (top nav + toasts):

| Route | Screen |
|---|---|
| `/` | Home (continue reading/listening, active jobs, recent imports, newest shared) |
| `/library` · `/discover` · `/import` · `/jobs` | Library grid · shared-library browser · import center · unified job center |
| `/u/:username` · `/account(/:section)` · `/admin(/:tab)` | profile · account/quota settings · admin dashboard |
| `/n/:novelId` (NovelLayout tabs) | `index` Overview · `chapters` · `manage` · `codex` · `codex/e/:entityId` · `ask` |
| `/n/:novelId/read/:number` | the Reader — **full-bleed, outside Shell** |

## Data layer

- **`shared/api/http.js`** — the single fetch wrapper: same-origin `/api` calls with
  `credentials`, the CSRF header from the `tg_csrf` cookie (and
  `x-tideglass-request: 1` on pre-auth mutations), JSON envelope/error normalization
  (`{detail}` → thrown error with status), and a registered **unauthorized handler**
  (401 → auth re-gate). Its recap transport requests NDJSON and ignores start/heartbeat
  frames until the final result, keeping a long cache-miss request active through the proxy.
- **TanStack Query** — `staleTime` 30 s, `retry` 1, no refetch-on-focus. Slices keep
  their query definitions in `queries.js`; invalidation goes through
  `shared/query/useInvalidate.js` so mutations refresh exactly the affected keys
  (e.g. a translate job start invalidates activity + chapter lists).
- Job-progress surfaces (Jobs page, import view, audiobook status) poll their endpoints
  while a job is active.

## Reader specifics

The Reader is the product's core surface: themes + accent hue (persisted, `data-theme`
on the root, CSS token-driven), column width, auto-scroll, scroll-position recovery,
volume-grouped TOC (`toc.jsx`), bookmarks, per-chapter translation editing (overlay
editor + base-vs-mine diff via `lib/diff.jsx`), provenance badges, the audiobook
transport (narration slice), and codex citation popovers (`lib/markdown.jsx` renders
answer markdown with `CiteProvider` so `[c:…]` markers open evidence popovers).
Resume writes are debounced `PUT /progress` calls and update `last_chapter`/`scroll_pct`
only. The trusted spoiler ceiling advances separately when the authenticated
`GET /chapter/{number}` response is served, so a fabricated progress PUT cannot unlock
future codex data.

## Styling

`styles/tokens.css` defines the design system (colors incl. dark theme + accent-hue
custom property, spacing, type scale); the other sheets consume tokens only. Theme
toggling sets `data-theme` and persists to localStorage (`nw-theme`, `nw-accent-h`).

The Codex ceiling popover accepts an exact chapter number (including fractional chapter
numbers) and validates it against the reader's available range. Its range slider remains
available for coarse browsing, while “Follow my reading” restores the trusted latest-read
ceiling. The number field uses the mobile decimal keyboard so long books do not require
precise slider dragging.

## Testing

- `src/app-contract.test.js` + `src/lib/api.test.js` — Vitest suites asserting the app's
  route table and API bindings match the frozen contracts.
- `e2e/critical-paths.spec.js` — Playwright against a mocked/real backend
  (`e2e/real-backend.spec.js`, `scripts/test_real_browser.py` fixture): register→read→
  codex critical journeys.
- The production build itself is a release gate (`npm run build`).
