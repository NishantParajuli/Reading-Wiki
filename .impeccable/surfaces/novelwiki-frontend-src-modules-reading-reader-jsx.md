# Reader editing and illustrations

Local extensions of the existing Personal Reading Room world; code-led, preserving Newsreader/Hanken typography, forest accents and paper/night surfaces.

## Direction contract

THESIS: Reading stays quiet; chapter editing earns a protected, spacious workspace and illustration creation is a deliberate optional action.

FIRST VIEWPORT: The editor gives most of the screen to prose with a desktop preview and visible save controls. Illustrations sit at chosen story beats; their controls follow the chapter text in a calm, collapsible section.

TOPOLOGY: Desktop editor split columns; mobile full-height Edit/Preview tabs. Illustrations occupy reading-width gaps between prose blocks, with character sheets tucked under a disclosure.

SIGNATURE INTERACTION: Live prose preview while editing; guarded discard preserves unsaved work. Images are generated only on explicit request.

MOTION: Existing reduced-motion-aware transitions; no decorative entrances obscure controls.

TRUTH: Shared versus personal edits are explicit. Art is an interpretation, bounded to this chapter; invented design details are labeled. Generation uses the connected Codex account and may wait or fail.

## Implemented surface

The reader remains a Read surface. Its translation editor is an Operate workspace
within the established Personal Reading Room; neither feature changes the global
palette, typography, or navigation model.

### Translation workspace

The desktop editor is a bounded, near-viewport dialog over a dark scrim, capped at
1440px wide and 960px high. Equal columns separate a sans-serif chapter textarea
from a live serif reading preview. The heading names the chapter, the context row
states shared or personal ownership and unsaved state, and the footer keeps save
and cancel actions outside the scrolling text. Word count and preview status are
supporting labels rather than competing headings.

At 980px and below the footer actions stack. At 760px and below the dialog fills
the dynamic viewport and replaces the split view with Edit/Preview controls.
Safe-area padding protects the header and footer. The preview keeps paragraph
breaks; it presents the draft as prose rather than rendering HTML.

Save labels state their effect: “Save for everyone,” “Save my version,” or “Save
merged version.” Conflict comparison is expandable above the editing panes.
Closing with unsaved changes opens a focused discard confirmation; failed saves
leave the draft available. Busy state disables edits and conflicting actions.

### Optional illustrations

“Illustrate this chapter” follows the prose and precedes the chapter-completion
card. Controls start collapsed, but existing scenes load automatically and appear at
the opening, after the chosen passage, or at the ending. AI chooses one to three
scenes per requested chapter; the user chooses only the style. Manage's “Illustrate
ahead” form accepts first/final chapters, defaults to keeping existing art, and links
the background range job to Jobs. No generation starts from reading or navigation.

The selector offers exactly two styles: “Luminous anime” (the default) and
“Painterly.” Luminous anime requests expressive anime characters, clean linework,
soft cel shading, and luminous light; Painterly requests semi-realistic characters,
textured brushwork, and cinematic lighting. A short description follows the
selected value in Reader and Manage and is associated with its selector for
assistive technology. The default remains Luminous anime when a chapter contains
only another style. Retired styles remain viewable under “Earlier illustrations”
in the reader but cannot be selected for new generation. These are requested image
styles, not changes to the app's theme or guarantees of provider output quality.

Scenes occupy prose gaps at reading width, containing the complete image in a 3:2
frame, and link to full-size images. Titles and captions sit below the art; design notes and character reference
sheets use disclosures. Reference sheets use two columns, stacking at 540px and
below; the generation action becomes full width at that breakpoint.

The introduction identifies images as interpretations and acknowledges imagined
details. Queued, running, waiting, failed, canceled, and unavailable states use
plain text. Active work links to Jobs and lets the reader continue reading. Failed
image loads retain a direct image link. Switching chapters resets the disclosure
and prevents old chapter results from appearing in the new chapter.

### Prepare illustrations in Manage

“Illustrate ahead” is an Operate form within the existing management card grid.
Visible labels identify first chapter, final chapter, and art style. Fields wrap
with the available width; the action spans the form on narrow screens. A separate
unchecked replacement checkbox keeps regenerating existing art a deliberate choice.
Supporting text explains the automatic scene count, sequential chapter processing,
and ability to leave while work continues. Progress remains beneath the form with
a Jobs link. Preparing future chapters does not expose their illustrations early
or change reading progress.

## Review evidence

The prior translation workspace review returned ship. The current illustration revision is covered by the desktop/mobile captures below and automated range/placement checks. The reviewed
captures show the desktop split editor, mobile workspace, and illustration controls:

- [Desktop editor](../review/editor-desktop.png)
- [Mobile editor](../review/editor-mobile.png)
- [Desktop illustration controls](../review/illustrations-desktop.png)
- [Desktop inline illustration](../review/illustration-inline-desktop.png)
- [Desktop range form](../review/illustration-range-desktop.png)
- [Mobile illustration controls](../review/illustrations-mobile.png)
- [Mobile inline illustration](../review/illustration-inline-mobile.png)
- [Mobile range form](../review/illustration-range-mobile.png)

These use synthetic story content and selected form values. They establish UI
composition, not generated-art quality or live provider reliability.
