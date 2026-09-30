---
name: Tideglass
description: Moonlit sea glass — a night-ocean reading room with luminous glass, literary type and a tide you can read by.
colors:
  accent-hue: "192 (sea glass; user-selectable)"
  tide-bg: "oklch(0.155 0.028 262)"
  tide-bg-2: "oklch(0.128 0.025 262)"
  tide-surface: "oklch(0.27 0.036 258 / 0.44)"
  tide-surface-float: "oklch(0.2 0.03 260 / 0.72)"
  tide-ink: "oklch(0.955 0.01 250)"
  tide-muted: "oklch(0.72 0.025 252)"
  tide-border: "oklch(0.86 0.03 250 / 0.1)"
  tide-accent: "oklch(0.83 0.115 var(--accent-h))"
  tide-accent-2: "oklch(0.76 0.13 calc(var(--accent-h) + 48))"
  tide-on-accent: "oklch(0.17 0.035 262)"
  pearl-bg: "oklch(0.978 0.006 88)"
  pearl-surface: "oklch(1 0 0 / 0.6)"
  pearl-ink: "oklch(0.24 0.035 262)"
  pearl-muted: "oklch(0.49 0.03 260)"
  pearl-accent: "oklch(0.52 0.1 var(--accent-h))"
  gold: "oklch(0.87 0.105 82) / oklch(0.6 0.12 72)"
  ok: "oklch(0.8 0.13 165) / oklch(0.45 0.105 160)"
  warn: "oklch(0.85 0.13 80) / oklch(0.5 0.115 68)"
  danger: "oklch(0.72 0.16 22) / oklch(0.5 0.18 25)"
  info: "oklch(0.79 0.1 240) / oklch(0.5 0.12 250)"
typography:
  display:
    fontFamily: '"Fraunces Variable", Fraunces, Georgia, serif'
    axes: "opsz auto, SOFT 30–100, WONK 0–1"
    hero: "clamp(2.9rem, 6.4vw, 5.2rem) / 1.02, weight 380, tracking -0.035em"
    page-title: "clamp(2.4rem, 4.6vw, 3.6rem) / 1.04, weight 400"
  ui:
    fontFamily: '"Geist Variable", Geist, system-ui, sans-serif'
    body: "0.9375rem"
    eyebrow: "0.6875rem uppercase, 0.18em tracking, weight 600–650"
  reading:
    serif: '"Literata Variable" (default)'
    classic: '"Fraunces Variable"'
    sans: '"Geist Variable"'
    legible: '"Atkinson Hyperlegible Next Variable"'
    size: "14–28px (default 19px), line height 1.3–2.2 (default 1.7)"
  mono:
    fontFamily: '"Geist Mono Variable", ui-monospace'
rounded:
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "22px"
  xl: "30px"
  full: "999px"
  cover: "3px 9px 9px 3px"
motion:
  ease-out: "cubic-bezier(0.16, 1, 0.3, 1)"
  ease-in-out: "cubic-bezier(0.65, 0, 0.35, 1)"
  ease-spring: "linear() soft spring (~1.7% overshoot)"
  durations: "140 / 240 / 420 / 700 / 1100 ms"
  springs: "snappy 520/40 · smooth 280/32 · gentle 150/24 · bouncy 430/17 · layout 420/38"
---

# Design System: Tideglass

## Overview

**Creative north star: "Moonlit sea glass."** Tideglass is a reading room at the
edge of a night ocean. Deep water fills the background; interface surfaces are
frosted sea glass that catches light at the edges; titles are set in an expressive
old-style serif; and the product's central idea — the tide that reveals a story only
as far as you have read — is present in its motion: arrivals rise out of the water,
chapters wash in, knowledge beyond your chapter stays beneath the surface.

Two themes share one vocabulary:

- **Tide** (dark) — abyssal navy, moonlight ink, a luminous sea-glass accent.
- **Pearl** (light) — warm pearl, deep-sea ink, iridescent morning light.

These rules describe the implemented system in
[tokens](novelwiki/frontend/src/styles/tokens.css),
[base](novelwiki/frontend/src/styles/base.css),
[components](novelwiki/frontend/src/styles/components.css),
[shell](novelwiki/frontend/src/styles/shell.css),
[ambient](novelwiki/frontend/src/styles/ambient.css),
[transitions](novelwiki/frontend/src/styles/transitions.css), the per-surface
stylesheets in `styles/surfaces/`, and the [reader](novelwiki/frontend/src/styles/reader.css).
[PRODUCT.md](PRODUCT.md) holds the product constraints; the
[frontend overview](docs/frontend/overview.md) describes behavior and code ownership.
Keep this file and its [.impeccable/design.json](.impeccable/design.json) sidecar
aligned when shared visual decisions change.

**Key characteristics**

- A living background: a slow WebGL tide (aurora over water, thin caustic light,
  a faint star field after dark), the focused book's blurred jacket as an aura,
  and film grain. The whole room takes on the colours of the book you are in.
- Floating glass chrome: an island header, a novel capsule, a phone dock, and in
  the reader two receding capsules. Content surfaces are translucent cards without
  backdrop blur; only floating elements blur what is behind them.
- Fraunces for everything editorial (titles, numbers, greetings, drop caps), Geist
  for the interface, Literata for long-form reading.
- Motion with physics and restraint: springs for anything that moves in space,
  rising entrances, view transitions between routes, and calm reading surfaces.
- Full parity between Tide and Pearl; saved accent hue, theme and reader
  preferences are honoured everywhere.

## Colours

All colours are OKLCH tokens in `tokens.css`, redefined per theme. The accent hue
`--accent-h` defaults to 192 (sea glass) and is a real user setting (Account →
Appearance offers Sea glass, Lagoon, Abyss, Amethyst, Coral, Lantern and Kelp);
changing it recolours accents, glows, focus rings, the ambient water and generated
art. A reader whose saved hue was the previous design's implicit default (165) is
moved to 192 once; chosen hues are kept.

- **Ink ramp:** `--ink` (primary text), `--ink-2`, `--muted` (secondary; ≥ 4.5:1 on
  both themes), `--faint` (non-essential only).
- **Surfaces:** `--bg`/`--bg-2`/`--bg-3`, `--surface`/`--surface-2` (translucent
  cards), `--surface-solid` (opaque inputs/menus), `--surface-float` (frosted
  floating chrome). Hairlines: `--border`, `--border-2`, and `--hairline-hi` for the
  lit top edge of glass.
- **Accent:** `--accent`, `--accent-2` (a companion hue +48° for gradients),
  `--accent-ink` (accent-coloured text), `--accent-soft` (tints), `--accent-glow`
  (light), `--on-accent`.
- **Gold** marks warm, rare moments (unread-chapter counts, sparkles).
- **Status:** `--ok/--warn/--danger/--info` with `-soft` tints. Status is never
  conveyed by colour alone.
- **Atmosphere:** `--atmo-h1/--atmo-h2/--atmo-c` (registered `@property` numbers,
  so they glide) are set from the focused book's cover; `--atmo-1/2/3/glow` derive
  from them per theme. Same-origin covers are sampled; covers on other sites (which
  block pixel reads) and missing covers use a stable hue pair from the title. The
  aura layer shows the real jacket colours regardless of origin.

## Typography

- **Display — Fraunces Variable** (opsz, SOFT, WONK). Page titles, greetings, book
  titles, chapter numerals, drop caps and numbers. Soft terminals
  (`"SOFT" 30–100`) and italic `WONK` for emphasis (the reader's name on Home,
  "next chapter" titles). Titles reveal word by word (`TextReveal`).
- **Interface — Geist Variable.** Controls, labels, metadata. Eyebrows are 11px
  uppercase with 0.18em tracking.
- **Reading — Literata Variable** by default; the reader may choose Fraunces
  (classic), Geist (sans) or Atkinson Hyperlegible Next (legible). Size 14–28px,
  line height 1.3–2.2, measure in `ch`.
- **Figures — Geist Mono** with tabular numerals.

All fonts are self-hosted variable fonts (`@fontsource-variable`); only the Latin
subsets a page uses are fetched.

## Layout

The shell content column is `min(1320px, 100%)` with `clamp(18px, 4vw, 56px)`
gutters, starting below the floating island. Novel routes add a sticky capsule.
Below 768px the island is replaced by a floating bottom dock and pages reserve
space for it. The reader measure is 55/65/80ch or full width. Every screen is
designed at 390px with no horizontal page overflow.

## Material, elevation and depth

- `.card` — translucent surface, hairline border, lit top edge, soft shadow.
- `.glass` / floating chrome — `--surface-float` with `backdrop-filter: blur(22px)
  saturate(1.6)`. Reserved for a handful of floating elements because blurring the
  animated background is costly. When the page scrolls, a frosted band (tint plus a
  blur that fades toward the page) softens content sliding under the islands; it sits
  beneath the novel capsule and sticky toolbars.
- A `backdrop-filter`, `filter`, `transform` or `view-transition-name` makes an
  element a containing block (and backdrop root) for what it holds, so overlays portal
  to the page root and entrance animations fill `backwards` only.
- Book covers are 2:3 jackets with a spine crease and top sheen; on fine pointers
  they tilt toward the cursor with a specular glare (`data-tilt`). Cards can catch a
  cursor-following light on their edges (`data-spotlight`).
- Books without cover art get generated jackets: one of four abstract motifs
  (tide under a moon, sea-glass shards, ripples, a horizon) in a hue pair derived
  from the title, with the real title and author set on top. They are decorative
  and never imply real artwork.

## Motion

- **Physics:** springs `snappy`, `smooth`, `gentle`, `bouncy`, `layout` (motion
  library) and the CSS `--ease-spring` curve. Feedback ≤ 240ms, surfaces ≤ 420ms,
  heroes ≤ 1.1s.
- **Arrivals** rise from a soft blur (`.rise` with `--i` stagger, `rise` variant).
- **Layout** changes (tab lozenges, nav pills, grids that filter or reorder) use
  shared-layout animation so selections slide rather than jump.
- **Routes** are View Transitions: a soft rise between pages, a reverse gesture on
  back/forward, a quick crossfade between tabs, the room receding as you open a book,
  and a wave-edged tide wash between chapters. The island, reader capsules and
  progress rail hold still while content changes. A book's jacket flies from any
  shelf into the novel hero (`hero-cover`). Destinations may hold the old frame for
  a moment until their data is on screen, so morphs land on real content.
- **Theme changes** spread from the switch as a circle of the new light.
- **Ambient water** runs at reduced resolution and ≤ 30fps, pauses when the tab is
  hidden, and has a user setting (Living water / Still / Off).
- **Reduced motion:** transitions, entrances, loops and the ambient animation
  collapse to instant or still; every action and state remains.
- Reading surfaces stay calm: nothing loops near prose.

## Components

- **Buttons** are pills. Primary: accent gradient, lit edge, a sheen that sweeps on
  hover, a tide ripple from the press point, a slight press scale. Secondary: accent
  tint. Ghost: glass. Danger: coral. Loading replaces the icon with a spinner and
  marks the button busy (`aria-busy`, `aria-disabled`) without disabling it, so
  keyboard focus stays put and repeat presses are ignored. On touch, compact
  buttons, tabs and segments grow to ~40px.
- **Fields** are 44px, softly inset; focus adds an accent ring and glow; errors are
  explained in text.
- **Segmented controls and tabs** slide a lozenge between options. Tabs follow the
  ARIA pattern: one Tab stop, and arrows, Home and End move and select.
- **Progress:** slim glowing bars (with a sheen when live) and progress rings.
- **Overlays:** dialogs, sheets (phones), popovers, drawers, the command palette and
  toasts are frosted glass with spring entrances and animated exits; focus is
  trapped and restored. Toasts drain a tide line as they time out and can be flicked
  away. In Pearl, the palette and dialogs are near-opaque so they read cleanly over
  the scrim.
- **Focus** is a glowing accent ring (`--ring`) that follows each control's shape and
  outranks component shadows; bare links get softened corners.
- **Status colours** in Pearl are deep enough to pass AA as text on their own soft
  tints; Tide's bright set already does.
- **Empty states** float an icon orb with slow ripple rings, with honest copy and a
  recovery action.

## Surfaces

- **Home** — the date and a time-of-day greeting under tonight's actual moon phase;
  the book you are in floats in a spotlight tinted by its jacket (progress ring,
  chapter, continue/listen); destinations and live background work beside it; rails
  for the nightstand and the shared library; unread-chapter counts in gold.
- **Reader** — see the [reader surface brief](.impeccable/surfaces/novelwiki-frontend-src-modules-reading-reader-jsx.md).
  Five tones (Theme, Paper, Sepia, Dusk, Night), an engraved chapter numeral with a
  drawn ornament, drop caps with small-caps first lines, floating capsules that
  recede, a narration dock that becomes a corner mini-player while you read and
  listen, and an end-of-chapter moment where the tide turns.
- **Sign-in** — a real-time moonlit sea (dawn in Pearl) with a wordmark that rises out
  of the waterline; the glass card morphs between modes while the sea keeps moving.
- **Novel** — a floating jacket over the book's own glow and a tideline across the
  whole book (your place, bookmarks as gold pins, volume ticks).
- **Codex** — knowledge beyond your chapter lies under the tide: a tide-gauge
  boundary, entries that surface as the water drops, and a frosted shelf of what is
  still hidden.
- **Import** — a glass basin that fills as books upload, and a tideline stepper.
- **Lost at sea** — unknown links show a bottle bobbing on the waves and three ways
  home.
- Library, Discover, Jobs, Account, Profile and Admin follow the same system; their
  specifics live with their code and in `docs/frontend/overview.md`.

## Do's and don'ts

### Do

- Use tokens so theme, accent and book atmosphere flow everywhere.
- Let covers, titles and prose carry the identity; keep controls quiet.
- Keep focus visible, targets ≥ 40px, keyboard and touch parity, reduced-motion
  parity, and honest loading/empty/error states with recovery.
- Verify Tide and Pearl, desktop and 390px mobile after shared changes.

### Don't

- Don't add backdrop blur to ordinary cards or long lists.
- Don't loop animation near reading text or animate large lists continuously.
- Don't nest interactive controls inside book links.
- Don't invent statistics, stages or artwork claims for decoration.
- Don't fix light-theme colours onto theme-aware or reader-tone surfaces.
