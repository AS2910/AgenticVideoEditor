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

## As built

### UX-7a · Tokens and chrome (2026-10-06)

Branch `ux7-workspace`, merged to main. Tests unchanged in count (224 frontend / 514 backend) and unchanged in text: the exit criterion was that every existing screen renders in the new look with no test change, and it did.

- `theme.css` carries the Ink and teal tokens from `voltage.css`, with every older name (`--amber`, `--speaker-a..d`, `--accent-bright`, `--shadow`, `--glow`) kept as an alias so no component broke. Everything that gives depth is a token too — `--hl`, `--sh-1..3`, `--card-bg`, `--surface-bg`, `--sheet-bg`, `--recess`, `--ring`, `--bar-bg`, `--btn-bg`, `--btn-primary-bg`, `--seg-on-bg`, `--fill-bg` — because the stylesheet contract test forbids a colour in a component sheet, and that now covers gradients and shadows as well.
- The chrome: the bar is frosted (`--bar-bg`, `backdrop-filter`) with the orb beside the brand word on every screen; raised buttons with a hairline highlight that press 1px (a global `button:active` rule); the primary button lit from above with a glow under the pointer; chips with the hairline; segmented controls (Edited / Original, Precise, Check with me / Just do it, the timeline zoom) as a recessed track with a raised chosen segment; inputs, selects and the composer recessed with a teal ring on focus; sheets on `--sh-3` at 22px; the spend meter, play bar and progress bars as recessed tracks with a lit fill; inserted words in `--accent-hi` on a teal tint with a soft ring, struck words with a coral strike; the orb teal, breathing on a 4.5 s cycle, faster while working; project-list states as pills with a lit dot.
- Placeholders stay `--muted`: the mocks had them faint, but the design system says a sentence is never faint, and the contract test agrees.
- Not changed, on purpose: layout (UX-7b onward), and the phone layout's clipped right edge at 420 px (the segmented control and the transcript hint run past the viewport) — it was there before UX-7a, checked against main's build, and belongs to UX-7f.
- Checked in headless Chrome against the preview build on the Bhaji Cam clip (`p3`) and the project list, at 1440 and 420 px. The preview server listens on IPv6 only, so the capture URL is `http://localhost:4173`, not `127.0.0.1`.

### UX-7b · The monitor (2026-10-06)

Branch `ux7-workspace`, merged to main. Frontend tests 224 → 234 (backend unchanged at 514).

- **The stage** is the column's full width at 16:9 (held to 56vh so the script stays in reach), inside a monitor card (`--surface-bg`, `--radius-xl`, `--shadow`); the `compact` monitor is gone, so the editor and review show the same picture.
- **The caption** (`transcript/caption.ts`, `captionAt`): the line being said at the playhead, over the picture on a frosted strip, with added words as `ins` and struck words left out. It follows the transcript's current state — a kept revision's words, the plan's words while a line is being voiced, a take in hand before it is kept, nothing for a removed line, a moved line where it now starts, a placed voice-over on a silent clip as an added line — and the words as shot when the Original version plays. It appears once the picture moves (playing, or the clock past zero), so a project opens on a bare frame; it is `aria-hidden`, since the transcript carries the same words.
- **The timeline** replaces the thin progress bar: a recessed 40px track with a block per line coloured by speaker (`--block-a..d`, striped), changed spans lit teal with a glow (kept revisions and lines the plan is voicing), the words as 1px ticks along the foot, a white playhead with a head, the placing block for Move, and the invisible range input over it all so it stays a slider. Under it a ruler (`timeline/ruler.ts`): a label every few seconds — the step chosen for about five — and the end, with the last regular label giving way when the two would touch. Times follow the version that plays (`renderTime` when the edited render is up).
- The word-level timeline behind *Precise* (zoom, drag across words, H1) is unchanged: it is the precision tool; the monitor's timeline is the overview.
- Left out on purpose: the on-frame time badge the mocks draw at the frame's corner — the transport already says the time, and the plan's rule is one fact in one place. The `--faint` contract gained `.tick` as an allowed glyph.
- Checked in headless Chrome on the Bhaji Cam clip at 1440 px: the blocks sit where the lines are, the two kept changes glow, the ruler reads 0:00 … 0:40, 0:52 on the 52.4 s edited render.

### UX-7c · One workspace (2026-10-06)

Branch `ux7-workspace`, merged to main. Frontend tests 234 → 233 (the goal stage's seven tests became the reading card's five and one for the rail).

- **The goal stage is gone.** A project opens in the workspace whatever its state; a fresh one (no plan, no edits) is read on arrival — `POST /reading` once, as before — and Voltage's first message in the thread is the reading: `ReadingCard`, with "I've read all N lines of *file*" (or "I've looked at *file*" for a silent clip) and the opening sentence, the cast with role guesses and *Looks right* / *Rename*, what it noticed as chips and the place to confirm for a silent clip, one sentence on what to ask for, and the example chips. A chip seeds the composer (`ChatPanel.seed`) with the cursor after it, so the words can be sent or changed; the goal is sent from Voltage's box, which already planned a goal when nothing was selected. The silent clip's frame strip and *Say it from 0:03* did not come across: the monitor plays the clip and the place editor is the empty transcript. The `/` shortcut now only ever focuses the composer.
- **The plan is in the script** as it was since UX-1: a planned line shows its new words as tracked changes with the *Planned* chip, before anything is voiced (B1, D3 — checked on the Goa clip: "Welcome to Goa." at 0:00, *Added · plays over the picture*).
- **The panel header** carries the orb, the name, the state word (`role="status"`), the autonomy switch and *Hide* with its key drawn (`\`). **The rail** (`data-testid="rail"`, `aria-label="Voltage, tucked away"`) is 64 px: the orb as the *Show Voltage* button with the state word in its name, a count badge (lines needing you in coral, else lines ready to hear in teal), the state word written vertically, and a chevron. Hiding never hides the work: the monitor and the script keep every state. `\` toggles from anywhere that is not a text field; on a phone the rail is a strip at the foot.
- Checked in headless Chrome on a fresh sample-ad project (the reading as the first message, the Announcer guess, *Looks right*) and the Goa clip with its planned voice-over.

### UX-7d · Review in the script (2026-10-06)

Branch `ux7-workspace`, merged to main. Frontend tests unchanged at 233 (the review tests were rewritten for the new labels and the receipt).

- **Review is the script filtered.** The separate review screen is gone. When a plan has changes ready or shipped, the transcript's heading carries a segmented control, *Changes · N* / *The whole script* (`LineDoc.filter`); on *Changes* the rows are the review rows (`LineDoc.review`, rendered by `ReviewPanel`): time, "Line n · speaker", Before and After stacked with the added words lit, *Play the seam* (the edited video from a moment before the line to a moment after, or the original before a render), the verdict as a sentence with the score behind it, Keep / Hold as a segmented control, *Another take*; a shipped line shows *Shipped* and *Undo*; a held line says the line ships as shot and the change waits as a draft. The bar's *Review · N ready* button toggles the filter and reads *Back to the script* while it is on; the plan card's *Review and ship* opens it too.
- **The Ship button is in the bar and counts**: *Ship* (disabled) with nothing kept, *Ship 2 changes* when every ready change is kept, *Ship 1 of 2* when some are held. Keep/Hold decisions live in the app (`decisions`), so a hold stands across a ship and an undo; a take that failed its sound check starts held (C6).
- **The ship sheet is the receipt** (G1, G3, D6, E2): "It's shipped." with the length in one sentence, stat tiles (lines changed, added, removed, held, the plan's spend), *What's in the file* as the lines at their times with the added words lit and the take's note, each with *Undo* (the line goes back to a draft and the receipt counts it as held), one line for what was held, the stand-in voice said plainly ("The new words are in a stand-in voice, and the mouth still moves to the old ones."), then Download MP4, Copy link, Make a variant, Back to the transcript.
- Not done: a count of takes voiced on the receipt — the plan does not carry it, and the receipt shows only what it knows.

### UX-7e · Grip and move (2026-10-06)

Branch `ux7-workspace`, merged to main. Frontend tests 233 → 237.

- **The grip is on every row that can move**, at the row's left edge in its own column (24 px wide, 44 px to the pointer, drawn as six dots in SVG, dim until the row is under the pointer or has focus): an untouched line shifts (`onShift`), a kept line moves with its take (`onMoveKept`), a moved line moves again; a removed, planned or voicing row has none. One helper, `gripButton`, serves them all.
- **Three ways to move, nothing voiced** (H2): drag the grip up or down the transcript with the drop line saying *Starts at m:ss.ss* and the block riding the monitor's timeline; the row's menu (the hover actions, or ⋯ on a touch screen) with *Move up*, *Move down* and *Shift to a time…* — up and down land where the row above the gap ends, as a drop does, and are absent at the ends; and the keyboard: with the grip focused, Enter opens *Starts at* with its nudges, ↑ ↓ move the block a tenth of a second, Shift ↑ ↓ a second, Escape lets go, and *Put it here* or Enter in the field applies the one move. The row's own `S` key still opens *Starts at*.
- The *Shift* action is now *Shift to a time…* in the menu.

### UX-7f · Projects and phone (2026-10-06)

Branch `ux7-workspace`, merged to main. Frontend tests 237 → 239.

- **Your videos.** The start screen is the bar (orb, brand, who is signed in), the heading *Your videos*, and a drop zone: dashed teal, lit from the top, brighter with a file over it, with an upload glyph, "Drop a video here", "Up to three minutes. With speech, or without any at all.", *Choose a video* (primary) and *Try the sample ad*. A file dropped on the zone uploads like a chosen one (A5); the upload's progress bar and any rejection sit inside the zone. The old hero sentence and tagline are gone from this screen (they stay on the sign-in door).
- **The cards.** Recent projects are cards in a grid (280 px minimum): the first frame at 16:9 with the duration in its corner, the name with the state pill beside it (New / Draft / Shipped, lit for draft and shipped), "variant of …" when it is one, then the date, length and last change (G2). *Delete* sits quietly in the card's corner (always visible on a touch screen); the confirm strip and the five-second *Undo* are unchanged (G4). The frame still loads only when the card is near the viewport.
- **The phone** (H4). Voltage starts tucked away on a narrow screen (`matchMedia('(max-width: 960px)')` at first render) and the rail is a strip stuck to the foot of the page — the orb, the count badge, the state word, and *Open* — frosted like the bar; *Open* shows the panel and scrolls it into view. Rows keep the grip at 44 px and the ⋯ menu; the segmented controls and the transport wrap at 480 px as before.
- **Checking a phone layout in headless Chrome:** the window cannot go below about 500 px, so a 420 px capture is a crop, not a layout — the right edge "clipped" in UX-7a's capture was that. Wrap the app in a 420 px iframe on a local page to see the real layout, or use the Chrome extension. The projects screen does not settle under `--virtual-time-budget` any more (nine card videos seeking to 0.5 s keep virtual time busy); capture it with `--timeout` after a delay, or in the extension.
