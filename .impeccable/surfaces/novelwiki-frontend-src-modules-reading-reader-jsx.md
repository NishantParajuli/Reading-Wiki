# Reader — reading by the tide

Tideglass revamp. The owner delegated every visual decision; code-led. The reader is a
Read surface; its translation editor is an Operate workspace inside it. This replaces
the earlier "Personal Reading Room" brief (Newsreader/Hanken, forest accents).

## Direction contract

THESIS: The page is the room. Chrome floats as frosted sea glass that recedes while you
read; every tone re-lights the whole room, not just the paper.

FIRST VIEWPORT: An engraved chapter numeral with a slow sheen, the title, a drawn
ornament and reading time, then prose with a drop cap and a small-caps first line.
Two glass capsules (top: back, contents, book and chapter, position, bookmark, Aa,
edit; bottom: previous, progress ring with minutes left, next) and a narration dock.

TOPOLOGY: Full-bleed, outside the shell. Settings are a popover under Aa on desktop and
tablet, a bottom sheet on phones. Illustrations occupy reading-width gaps between
prose blocks; character sheets stay under a disclosure.

SIGNATURE INTERACTION: The tide wash between chapters (a wave-edged View Transition),
the end-of-chapter "tide turns" seal, and a narration dock whose tide line drifts while
it plays and which shrinks to a corner mini-player while you read and listen.

MOTION: The first chapter of a visit settles in (prose readable within ~0.8s); later
chapters use the wash. Nothing loops near prose. Reduced motion keeps every state.

TRUTH: Progress, minutes left and positions are real. The seek bar's tide line is
decorative and carries no audio data. Shared versus personal edits are explicit. Art
is an interpretation bounded to its chapter; generation is explicit and may wait or
fail.

## Implemented surface

### Reading chrome and tones

The capsules carry the view-transition names, so their glass blurs the page beneath
in every tone; only keyboard focus holds them on screen. Five tones — Theme, Paper,
Sepia, Dusk, Night — re-map the tokens on `.reader`: page and ink, status colours
(light tones take Pearl's AA set, dark tones Tide's), gold, atmosphere, scrim, the
focus ring and the page behind the reader. The Theme swatch shows the app theme.
Settings (`ReaderSettings.jsx`) move focus to their title, trap Tab, return focus to
Aa on Escape, and treat tone and font as single-stop radio groups with arrow keys;
the phone sheet hides Width and fades its scroll edges. Toasts and the first-visit hint
("Click"/"Tap" by pointer type) rise above the bottom chrome. Rich-chapter pictures open
in a focus-trapped lightbox dialog. On touch, capsule, dock and settings controls are
at least 40–44px.

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
