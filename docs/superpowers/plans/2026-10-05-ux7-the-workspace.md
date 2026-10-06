# UX-7 · The workspace

**Date:** 2026-10-05 · **Status:** design shipped, build not started. The design was drawn from the user stories (`docs/superpowers/specs/2026-10-04-user-stories.md`) without reference to the current screens, reviewed in four rounds, and signed off the same morning. The mocks live on a canvas (https://claude.ai/artifact/QymiqbrAC1BBtM9wcc83KZ, private) and their sources are checked in at `docs/superpowers/mocks/2026-10-05-voltage-ux7/` (one `.dc.html` per screen, `voltage.css` for every token and component, `canvas.json` for the layout). The sources are the record; the canvas is the picture.

## What changes

Three screens, one document. The goal stage and the separate review mode go away.

1. **Your videos.** Drop zone, the sample ad, and a card per project (frame, state word, last change). The monthly spend meter is in the bar.
2. **The workspace.** One screen for the whole loop. The video fills the main column at 16:9 with the player under it; the script under that; Voltage on the right. Voltage's read is the first message in the thread, with example chips, so there is no goal stage. The plan appears in the script as tracked changes marked *Planned* before anything is voiced.
3. **Ship.** A sheet that is the receipt: stat tiles, what is in the file, what was held, the stand-in voice note, then Download, Copy link, Make a variant.

Review is the script filtered to changed rows (a segmented control in the script header), with Before and After stacked, *Play the seam*, and Keep / Hold per row. The Ship button in the bar always says what it will do.

## Rules the mocks follow

- **The line is the unit.** Every row carries its state (Planned, Voicing, Ready to hear, Needs you, Kept, Held, Removed, Moved, Couldn't voice it), its sentence, and one next action, last. Row states are on the States board.
- **Voltage is for the whole video**, and can be hidden. A Hide button in its header (`\`) collapses it to a 64 px rail: the orb, a count badge (coral when it has a question), the status written vertically. Hiding never hides the work: progress and *Needs you* stay on the rows.
- **Moving a line changes when it is said**, not its order. Every row has a ⋮⋮ grip (44 px); dragging shows a drop line with the landing time; the row's ⋯ menu has Move up / Move down / Shift to a time; the editor has Starts at with nudges; with the grip focused, ↑ ↓ move a tenth, Shift a second. Nothing is voiced.
- **One fact, one place.** Spend in the bar only. Counts on the rows or the panel header, not both. No captions under the video. No copy that explains the product.
- **Verdicts are sentences first**, score behind in small type. Voltage asks at most one question, with its guess filled in and *Go with that* first; on a silent clip up to three, counted.
- **The picture shows the line.** A subtitle-style caption over the video shows the line at the playhead, with the changed word highlighted.

## Look

Theme **A · Ink and teal**: deep blue-black ground (`#0E141C`), teal for anything Voltage touched or wants heard (`#3FC8B4`, fill `#17A997`), coral for *needs you* (`#F08A6E`), soft green for kept (`#86C98F`), blue and mauve for speakers. Fraunces for headings, Instrument Sans for everything else, 16 px base. Depth: layered shadows with a hairline top highlight, recessed inputs, raised buttons that press, a frosted top bar, an orb that breathes (off under reduced motion). Two alternatives (B · Paper and indigo, light; C · Slate and coral) are on the Palettes board and are one token block to switch. All tokens are in `voltage.css`; the design-system master is updated to match.

## Screen → stories

| Board | Stories |
| --- | --- |
| 1 Projects | A5, G2, G4, I1, D1 |
| 2 Workspace, just opened | A1, A2, B2–B6, H1, H3, H5 |
| 3 The plan waits | B1, B7, B8, B10, D2, D3 |
| 4 Running (interactive: Hide) | C1–C4, D7, F1, F2, I2 |
| 5 Review, Voltage tucked | C5, C6 |
| 6 Shipped | G1, G3, D6, E2 (honesty line) |
| 7 A silent clip | A3, A4, D4, F4 |
| 8 One line, in full | B9, C4, F4, H2 |
| 9 Row states | all of C, I2 |
| 10 Phone | H4 |
| 11 Palettes | — |
| 12 Moving a line | H2 |

Not drawn: the consent sentence (D5) and the *Needs you* answer flow (F2's question). Both are described on the States board and keep today's behaviour.

## Build phases

- **UX-7a · Tokens and chrome.** `theme.css` takes the Ink and teal tokens and the depth rules from `voltage.css`; the bar, buttons, chips, pills, inputs, segmented control. No layout change. Exit: every existing screen renders in the new look with no test change.
- **UX-7b · The monitor.** Full-width 16:9 frame, player under it, the caption over the picture, the timeline with speaker blocks, word ticks, playhead and ruler. Exit: C1 and H1 walkthrough.
- **UX-7c · One workspace.** Goal stage folded into the panel as Voltage's first message plus chips; the plan rendered into the script as *Planned* tracked changes; the panel header with status and Hide; the rail. Exit: B1, B7, B8, D3 with Voltage hidden and shown.
- **UX-7d · Review in the script.** The Changes / Whole script filter, Before/After rows, Play the seam, Keep / Hold, the Ship button that counts. The ship sheet as the receipt. Exit: C6, G1, G3.
- **UX-7e · Grip and move.** The grip on every row, drag with the drop line, the ⋯ menu, Starts at with nudges, keyboard moves. Exit: H2 from grip, menu and keyboard.
- **UX-7f · Projects and phone.** The cards, the drop zone, the phone layout with the rail as a strip. Exit: A5, G2, H4.

Each phase ships on its own, build, lint and tests clean, then merges. Blocked items go to the backlog.
