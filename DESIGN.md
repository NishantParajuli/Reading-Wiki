---
name: Tideglass
description: A personal reading room in paper, forest ink, and literary type.
colors:
  accent: "oklch(0.40 0.065 165)"
  accent-soft: "oklch(0.46 0.075 165 / 0.10)"
  on-accent: "oklch(0.99 0.01 90)"
  paper: "oklch(0.977 0.008 90)"
  desk: "oklch(0.947 0.012 90)"
  surface: "oklch(0.995 0.006 86)"
  ink: "oklch(0.27 0.015 155)"
  muted: "oklch(0.49 0.018 85)"
  border: "oklch(0.9 0.015 80)"
  directory: "#183d35"
  directory-ink: "#f1eee3"
  directory-muted: "#becfc6"
  directory-active: "#2b5146"
  success: "oklch(0.62 0.11 155)"
  warning: "oklch(0.62 0.13 75)"
  danger: "oklch(0.55 0.16 25)"
  info: "oklch(0.56 0.1 250)"
  dark-paper: "oklch(0.195 0.012 62)"
  dark-surface: "oklch(0.238 0.014 62)"
  dark-ink: "oklch(0.93 0.012 84)"
  dark-muted: "oklch(0.7 0.016 76)"
  dark-border: "oklch(0.32 0.015 66)"
  dark-accent: "oklch(0.8 0.12 165)"
  dark-on-accent: "oklch(0.2 0.02 70)"
typography:
  display:
    fontFamily: '"Newsreader", Georgia, "Times New Roman", serif'
    fontSize: "clamp(2.25rem, 4vw, 3.25rem)"
    fontWeight: 400
    lineHeight: 1.12
    letterSpacing: "-0.03em"
  headline:
    fontFamily: '"Newsreader", Georgia, "Times New Roman", serif'
    fontSize: "clamp(2rem, 3.5vw, 2.75rem)"
    fontWeight: 400
    letterSpacing: "-0.025em"
  title:
    fontFamily: '"Newsreader", Georgia, "Times New Roman", serif'
    fontSize: "1.5rem"
    fontWeight: 500
  body:
    fontFamily: '"Hanken Grotesk", system-ui, -apple-system, sans-serif'
    fontSize: "0.9375rem"
    fontWeight: 400
  label:
    fontFamily: '"Hanken Grotesk", system-ui, -apple-system, sans-serif'
    fontSize: "0.8125rem"
    fontWeight: 600
  prose:
    fontFamily: '"Newsreader", Georgia, "Times New Roman", serif'
    fontSize: "19px"
    fontWeight: 400
    lineHeight: 1.7
  mono:
    fontFamily: '"Spline Sans Mono", ui-monospace, "SF Mono", Menlo, monospace'
    fontSize: "0.75rem"
rounded:
  sm: "6px"
  md: "12px"
  lg: "16px"
  full: "999px"
spacing:
  "1": "4px"
  "2": "8px"
  "3": "12px"
  "4": "16px"
  "5": "24px"
  "6": "32px"
  "7": "48px"
  "8": "64px"
components:
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-secondary:
    backgroundColor: "{colors.accent-soft}"
    textColor: "oklch(0.36 0.07 165)"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  button-ghost:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "10px 18px"
  input:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "10px"
    padding: "10px 12px"
  card:
    backgroundColor: "{colors.surface}"
    textColor: "{colors.ink}"
    rounded: "{rounded.md}"
    padding: "{spacing.4}"
  chip:
    backgroundColor: "oklch(0.978 0.009 84)"
    textColor: "{colors.muted}"
    rounded: "{rounded.full}"
    padding: "3px 10px"
  directory-item:
    backgroundColor: "{colors.directory}"
    textColor: "{colors.directory-muted}"
    rounded: "5px"
---

# Design System: Tideglass

## Overview

**Creative North Star: "The Personal Reading Room"**

Tideglass pairs a forest-ink directory with a generous paper desk. Book covers,
literary headings, and comfortable prose establish the identity; navigation and
working controls stay compact and legible. The result is calm, tactile, and useful
for both returning to a story and managing a collection.

These are the implemented visual rules, extracted from the current
[tokens](novelwiki/frontend/src/styles/tokens.css),
[components](novelwiki/frontend/src/styles/components.css), and desktop/mobile
review captures. [PRODUCT.md](PRODUCT.md) contains product constraints;
[frontend overview](docs/frontend/overview.md) describes behavior and code ownership.
Update this reference and its [.impeccable/design.json](.impeccable/design.json) sidecar
when shared visual decisions change. Individual surface compositions stay in their
surface briefs.

**Key Characteristics:**

- Warm paper backgrounds with a distinct forest navigation area.
- Serif titles and prose, clear sans-serif controls, restrained monospaced metadata.
- Consistent book-cover proportions and slim reading-progress indicators.
- Flat everyday surfaces, visible focus, and limited depth for covers and overlays.
- Full light/dark themes with preserved reader appearance choices.

## Colors

The palette combines warm neutrals and forest ink with semantic status colors. The
frontmatter records the default light and dark values. Runtime accent colors use
`--accent-h`, whose default is 165; saved user choices override that default. Use the
CSS variables in implementation so changing hue or theme updates the complete system.

### Primary

The accent identifies the principal action, links, reading progress, and selected
controls. Its soft counterpart supports quiet selections and secondary actions.
Accent text uses the dedicated ink variant for legibility on paper. The directory
palette is separately defined and remains forest-colored across app themes.

### Neutral

Paper is the page canvas; the desk tone distinguishes the featured reading surface.
Surface colors support controls, dialogs, and restrained cards. Ink carries content;
muted text is reserved for supporting information. Borders separate neighboring
controls and list rows without replacing spacing as the main grouping cue.

The dark theme keeps warm backgrounds and increases accent/text lightness. The reader
also provides coordinated sepia and night palettes in
[reader.css](novelwiki/frontend/src/styles/reader.css); they override text, surfaces,
and borders together.

### Status

Success, warning, danger, and information colors explain state. Keep their text labels
or icons alongside color. Codex entity-type colors distinguish categories; they do not
indicate that hidden story information has become available.

## Typography

Newsreader carries titles, book names, and reading prose. Hanken Grotesk carries
navigation, forms, descriptions, and actions. Spline Sans Mono supports chapter
positions, timing, shortcuts, and code-like metadata. Fonts are self-hosted and have
system fallbacks.

The display and headline roles create the page hierarchy; section titles are smaller
and moderately weighted. Small labels support the interface instead of competing
with a book title. Form labels use normal capitalization. Uppercase remains a limited
treatment for small category labels and chapter-completion metadata.

The prose role records the default reader settings. Readers can choose serif or sans,
adjust size and line spacing, and change column width. Preserve those choices when
refining chrome or typography.

## Layout

The desktop shell has a sticky directory, a breadcrumb/search bar, and an independently
flowing content column. The directory is 224px expanded and 76px collapsed; the main
page container caps at 1380px. Horizontal page padding scales from 20px to 56px. Use the
shared spacing scale for recurring gaps, with component-specific geometry where the
implementation already defines it.

At 767px and below, primary navigation moves to fixed bottom tabs, the directory is
hidden, and search remains available as an icon button. Content reserves space for
the navigation and device safe areas. At 640px and below, the library uses two cover
columns and page actions wrap. Home's main/aside layout stacks at 1150px; these are
surface-specific breakpoints, not a universal grid requirement.

The reader fills the viewport outside the shell. Its centered column uses character
measure: narrow, normal, and wide widths are based on 55ch, 65ch, and 80ch plus the
column's padding allowance; full width is also available. Horizontal cover rails
scroll within their own region, while forms and page headings wrap at narrow widths.

## Elevation & Depth

Cards and primary buttons are flat at rest. Subtle borders and tonal differences carry
most grouping; book covers may use ambient depth, and dialogs, popovers, and citation
panels use the stronger floating shadow. Interactive cards can gain depth on hover.
The shared shadow definitions, focus ring, and motion values are recorded in the
sidecar directly from the CSS; do not add shadows to every surface.

Short transitions mark hover, focus, selection, and opening/closing. Page entrance is
a small movement; reader chapter changes can fade. Reduced-motion preferences reduce
animation/transition duration and disable smooth scrolling while retaining actions.

## Shapes

Small-radius buttons and icon controls contrast with softly rounded containers. Input
fields retain their own rounded outline. Chips, avatars, progress tracks, and play
buttons use circular or pill shapes because those shapes communicate their roles.

Book jackets use a 2:3 proportion and slightly asymmetric corners to suggest a spine.
Missing covers are flat colored jackets with a title, an inset rule, and no invented
illustration. Tiny cover slots omit the placeholder title instead of squeezing it into
unreadable type.

## Components

### Buttons

Primary buttons use accent and on-accent colors without a resting or hover shadow.
Secondary buttons use the soft accent; ghost buttons use the surface with a fine
border. The shared button has a 42px minimum height. Hover changes color or brightness;
disabled controls reduce opacity and use the disabled cursor. Keep an explicit text
label unless the action is a familiar, accessibly named icon control.

### Fields and chips

Fields use a surface fill, a fine outline, and visible labels. Focus changes the border
and adds a soft accent ring. Errors use explanatory text and a danger outline. Chips
are compact supplementary metadata, with semantic variants for status; they are not
substitutes for form labels or primary actions.

### Cards and book covers

General cards use a border and surface fill; their padding variants follow the spacing
scale. Collection cards give the cover and title prominence. Cover, resume, and shelf
actions are separate controls. Cover actions appear on hover and keyboard focus and
remain visible on touch devices.

### Navigation and search

Directory items use muted light text, a lighter forest active surface, and a small
active marker. Keyboard focus is a light outline against the directory. The paper
breadcrumb bar retains a clearly reachable search control on desktop and mobile.
The search palette is a bounded floating surface with grouped results, keyboard
navigation, a focus trap, and an explicit loading/failure message.

### Reading controls

A slim accent rail marks scroll progress at the viewport edge. Reader chrome can
recede during reading and returns on interaction or keyboard focus. The footer gives
previous/next actions and reading position; settings and translation tools become
bottom panels on narrow screens. Narration highlights the active text while retaining
the reader's typography and tone.

## Do's and Don'ts

### Do

- **Do** use shared theme tokens and preserve stored accent and reader preferences.
- **Do** let book titles, real covers, and comfortable prose carry visual character.
- **Do** preserve clear focus, keyboard actions, touch access, and reduced-motion behavior.
- **Do** show loading, empty, and failed states distinctly, with a useful recovery action.
- **Do** verify desktop, narrow screens, and dark theme after shared visual changes.

### Don't

- **Don't** nest a shelf button or resume link inside another book link.
- **Don't** hide essential cover actions from keyboard or touch users.
- **Don't** replace semantic status labels with color alone.
- **Don't** invent statistics, processing stages, or verification claims as decoration.
- **Don't** apply fixed light-theme colors to theme-aware reading surfaces.
