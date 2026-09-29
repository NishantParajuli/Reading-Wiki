---
version: 2
slug: "novelwiki-frontend-src-modules-experience-home-jsx"
primary_target: "novelwiki/frontend/src/modules/experience/Home.jsx"
related_targets: ["novelwiki/frontend/src/layouts/Shell.jsx","novelwiki/frontend/src/modules/experience/MoonPhase.jsx","novelwiki/frontend/src/atmosphere/Ambient.jsx","novelwiki/frontend/src/styles/surfaces/home.css"]
---

# Home — the tide-lit reading room

Tideglass revamp. The owner delegated every visual decision; no approval round was
required. Mode: Read (a place to return to), with a small Operate corner for work.
This replaces the earlier forest-and-paper "Personal Reading Room" brief.

## DESIGN THESIS
Night water seen through sea glass: the book you are reading lights the room. Home is
a threshold, not a dashboard — one story leads, everything else waits quietly below.

## WORLD
A coastal reading room after dark: tide pools, frosted sea glass, moonlight on water,
a single lamp over an open book. Candidates weighed: harbour chart rooms (too
instrumental), observatory domes (kept only as the moon), aquarium glass (too cold),
bookshop windows (kept as the cover-first rails). The chosen world lets the product's
two moods — calm reading and quiet background machinery — share one surface.

## FIRST VIEWPORT
A time-of-day greeting in Fraunces ("Good evening, Mira") with the date and the moon
drawn at its real phase. Beneath it the spotlight: the current book's jacket floats on
a slow bob with a reflection, the room's water and aura take that jacket's colours,
and the copy states the true resume chapter, its title, progress, and a single
primary "Continue reading" (plus "Listen" when narration exists). Background work
sits beside it in a small glass card that says plainly when all is quiet.

## VISITOR PATH
Continue the current chapter; reach other current reads from "Also on your
nightstand"; open "Fresh chapters" from books in progress; browse "New in the shared
library"; step to the library, Discover, or Import from the three horizon tiles. A new
account sees the welcome room instead: moon, a two-line headline, and three paths —
add a webnovel from a link, bring an EPUB or PDF, or find a read in the shared
library.

## SIGNATURE INTERACTION
The book lights the room: opening Home re-tints the WebGL water and the out-of-focus
cover aura to the spotlight book, and a click on any cover morphs that jacket into the
novel page's hero (View Transitions). The spotlight's tide line fills to the reader's
progress. Reduced motion keeps every state and action but holds the water still and
drops travel.

## SYSTEM AND RISK
Tokens, glass, and motion come from DESIGN.md (Tideglass). Every figure is real data
from the home and activity queries; empty, loading, and failed states are explicit
("Background work couldn't load." with "Try again"). The risk is spectacle over
substance: the ambient layer stays behind content, never animates text, drops to a
still gradient on request or when WebGL is unavailable, and never delays the first
paint of the resume action.

## Implemented surface

- Header: greeting by hour, date line, `MoonPhase` (synodic calculation; parallax on
  scroll where scroll-driven animation is supported), name in the accent gradient.
- Spotlight (`section.spotlight`, `data-vt-card`): floating tilting cover with
  reflection, chapter + title, "N% through your story", Continue/Listen, tide line.
  Loading uses skeletons with `role="status"`; the empty state links to the library.
- Rails: "Also on your nightstand" shelf books with a hover/focus play button and
  progress; "Fresh chapters" rows link to each novel's chapter list; "New in the
  shared library" covers.
- Background work: live job rows linking to Jobs, a calm orb when nothing runs.
- Horizon: three destination tiles with pointer spotlight.
- Readiness: `useReadySignal("home", !isLoading)` lets route transitions wait for real
  content; `useBookAtmosphere(reading[0])` tints the ambient layer.

## Review evidence

Captured with the showcase harness (`novelwiki/frontend/e2e/showcase/shoot.mjs`) on
synthetic fixtures across Tide/Pearl, desktop/tablet/mobile, including the empty
account (`SHOWCASE_EMPTY=1`). Captures establish composition, not production data.
