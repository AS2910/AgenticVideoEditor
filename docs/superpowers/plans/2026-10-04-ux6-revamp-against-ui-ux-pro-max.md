# UX-6 · The revamp: Voltage against ui-ux-pro-max

**Date:** 2026-10-04 · **Status:** built the same day, in five phases on `ux6-revamp`, each merged to main (as-built note at the end). The user asked for the `ui-ux-pro-max` skill to be applied to the whole product, not only the silent-clip work, "so we will do a final revamp". This is the audit and the plan that follows from it. Nothing here is built yet.

## How the audit was done

The skill is installed globally (`~/.claude/skills/ui-ux-pro-max/`, provenance in `~/.claude/skills/_SOURCES.md`). Its 119 UX guidelines (`references/quick-reference.md`) were applied in the skill's own priority order — accessibility, touch and interaction, performance, style, layout, typography and colour, animation, forms and feedback — by three sweeps over every component and stylesheet under `frontend/src`, each reading the code and computing contrast from the tokens in `styles/theme.css`, plus headless-Chrome captures of the start screen and the editor at 1440 and 500 px. Every finding below points at a file and line and was spot-checked. Counts at the start: 501 backend / 198 frontend tests, all green.

**What the skill's design-system generator said, and why it was set aside.** Asked for an "AI video editor voice-over tool, dark, warm, cinematic", the generator proposed Swiss minimalism in Inter with recording red. Voltage's room — warm dark surfaces, amber for what the agent changed, rose for "needs you", Fraunces headings over Instrument Sans — is shipped and liked; the skill's own typography data endorses the pattern (a warm editorial serif for heroes at 36–42px over a sans at 16–18px, labels at 12px). So the direction stays and is written down as `design-system/voltage/MASTER.md`; this revamp fixes how well the room is built, not what it looks like.

## What is strong, and must survive the revamp

- **The tokens are honest.** `--text`, `--muted`, `--accent`, `--ok` and `--amber` all clear 4.5:1 on every surface they are used on (muted 6.6:1, accent 8.3:1, rose 6.7:1, ink-on-amber 8.8:1). Only `--faint` fails, and MASTER already reserves it for labels beside larger text. Raw colours in components: eleven in total.
- **The global rules do real work.** `theme.css` gives every control a 2px amber `:focus-visible` ring, `cursor: pointer`, inherited fonts, tabular numerals, and a reduced-motion rule that genuinely neutralises every transition and keyframe in the app (the orb's breathe, the sheets' rise, the caret).
- **Semantics exist where someone thought about them.** Every interactive element is a real button, link or input; `aria-pressed` on toggles; labelled groups on the autonomy and version switches; `alt=""` and `role="img"` on avatars; `role="alert"` on the engine strip; SVGs beside text are `aria-hidden`; the scrubber is a native range with a label; the Move block is a true slider with arrow keys.
- **The keyboard model in the transcript is sound.** Single-key shortcuts fire only with the row focused, ↑/↓ rove, Enter and Escape work, focus returns to the row when an editor closes, and every drag has an alternative (the S key, typed times, ◀ ▶ nudges, *Put it here*).
- **The layout already stacks.** 960px queries with `minmax(0, 1fr)` columns on the editor, the goal stage and review; chat scrolls itself; the player reserves its box; project frames reserve 56×36. The start screen fits at 500px with no horizontal scroll.
- **The voice.** Sentences before numbers, the next action last, errors in the row with one action, Undo on removed lines, the recommended answer first with its reason.

## The findings, by the skill's priority

Severity: **S1** fails a rule outright for some users, **S2** makes the product harder than it should be, **S3** polish. Each line names the file; line numbers are in the three audit reports and in the code.

### 1. Accessibility (critical)

| # | Finding | Where | Sev |
|---|---|---|---|
| A1 | **Nothing is announced.** Voltage's replies, the thinking line, plan progress, the generating block, the header state word, per-item narration, row state chips (Voicing… → Ready → Needs you), working/failed/needs-you blocks, upload progress, "Link copied" — none sits in a live region. A screen-reader user types a goal and hears nothing back. | `ChatPanel.tsx`, `App.tsx` (thinking, progress, stateWord), `PlanCard.tsx`, `LineDoc.tsx`, `LoadScreen.tsx`, `ShipSheet.tsx` | S1 |
| A2 | **The sheets are not modals.** Ship and Consent set `role="dialog" aria-modal` but never move focus in, trap Tab, return focus on close, or close on Escape; Tab walks the page behind the overlay. | `ShipSheet.tsx`, `ConsentSheet.tsx` | S1 |
| A3 | **`--faint` used as text.** Struck words (`.del`), the editor's helper sentences, "Starts at 0:04.96", the cost line, "Drag it on the bar above…", the spend meter detail, goal-stage timecodes, "Or try", placeholders, the simulated-metric suffix: all 3.2–3.8:1. | `LineDoc.module.css` `.del` `.faint`, `SpendMeter`, `GoalStage.module.css` `.time` `.or`, `CandidateCard.module.css` `.simulated` | S1 |
| A4 | **Focus rings removed or thinned.** Seven `outline: none` sites; the replacements are a 1px border recolour or a 1.5px 40%-amber inset (≈2.1–2.4:1, under the 3:1 non-text minimum): rows, the chat and goal inputs, the rename field, the plan wording field, the editor textarea, the speaker name. | `LineDoc.module.css:13,62`, `ChatPanel.module.css:24`, `GoalStage.module.css:18,47`, `PlanCard.module.css:24`, `SpeakersBar.module.css:18` | S1 |
| A5 | **Invalid ARIA on rows.** Focusable `div role="row"` with no grid/table parent and no cells; assistive tech drops the role or mis-reads the row. | `LineDoc.tsx:560,626` | S1 |
| A6 | **A keyboard-dead control.** The ⋮⋮ grip is a button whose label promises "Drag to move the line" but only handles pointer-down; Enter and Space do nothing. | `LineDoc.tsx:578,682` | S1 |
| A7 | **Rose on amber.** A question's first option is amber-filled; when it carries a warning the rose warning text sits on it at ≈1.25:1. Separately, `#6B3B2E` on amber in the question card is 4.47:1 at 12px. | `LineDoc.tsx:454`, `QuestionCard.module.css:16` | S1 |
| A8 | **No headings, no landmarks, no skip link.** "Voltage", "The plan", "What I did", "Recent" are spans or divs; only the editor has a `<main>`; the start, goal and sign-in screens have none; no skip link anywhere. | `App.tsx`, `PlanCard.tsx`, `ActivityLog.tsx`, `ProjectList.tsx`, `LoadScreen.tsx`, `GoalStage.tsx`, `SignIn.tsx`, `index.html` | S2 |
| A9 | **Progress and meters are divs.** Plan, voice and export progress bars have no `role="progressbar"` or value; the spend meter reads as two prices and a count with no noun; `near` the cap is colour only. | `App.tsx` progress, `PlanCard.tsx:185`, `SpendMeter.tsx` | S2 |
| A10 | **State by colour alone.** Delivery chips show selection by tint with no `aria-pressed` (the mix pills have it); candidate metrics pass or fail by bar colour only; timeline words carry no selected state and nothing announces the range. | `LineDoc.tsx:300`, `CandidateCard.tsx:88`, `Timeline.tsx:111` | S2 |
| A11 | **Hover-only content.** The vendor breakdown, the reason for a role guess, voice descriptions, "Approve for a trial", the full filename, the edit strip's positions all live only in `title`. | `SpendMeter.tsx:19`, `GoalStage.tsx:103`, `VoicePicker.tsx:27`, `CandidateCard.tsx:118`, `App.tsx:1128`, `ExportBar.tsx:18` | S2 |
| A12 | **Times and scores read as digits.** "0:04.96 / 1:02.00", `aria-valuenow` without `aria-valuetext`, "sounds right 0.87", "0:12.5 → 0:13.1". | `Player.tsx`, `ReviewPanel.tsx:128`, `ShipSheet.tsx:55`, `LineDoc.tsx` | S3 |
| A13 | Small: the "/" separator is read aloud; `aria-label` on a role-less div in the speakers bar; scroll regions with no focusable child cannot be scrolled by keyboard in Safari/Firefox; ≈350 tab stops through a 40-line transcript (no roving tabindex on row children). | `App.tsx:1127`, `SpeakersBar.tsx:40`, `ShipSheet.module.css:10`, `GoalStage.module.css:39`, `LineDoc.tsx` | S3 |

### 2. Touch and interaction (critical)

| # | Finding | Where | Sev |
|---|---|---|---|
| T1 | **Almost nothing is 44px.** Measured heights: header controls 24–32; pills 26–28; row actions 26; the grip 16×22; the time button 21; Undo/Move/"in your words…" 18; Delete / Keep / "Delete for good" 24; Review's Keep / Hold 28 and Undo 18; the send button 34; primary buttons 35–43; nudges 36; take play 28, transport play 34; zoom controls 20; speaker name and voice 22; scrubber hit area 20, the Move block 16; timeline words 26 tall and sometimes a few px wide. | everywhere; see the three audits | S1 |
| T2 | **Targets 4–6px apart.** Option rows, pill rows, nudges, Keep/Hold, zoom controls, the segmented switches (0px between 24–26px segments). | `PlanCard`, `QuestionCard`, `LineDoc`, `ReviewPanel`, `Timeline`, `AutonomySwitch`, `App.module.css` | S2 |
| T3 | **Row actions are unreachable on phones.** Under 960px the six actions hide until hover/focus-within, but the visible parts of a row are themselves buttons (line opens the editor, time seeks), so Remove, Shift and Add a line are reachable only by tapping dead space. | `LineDoc.module.css:122` | S1 |
| T4 | **"Delete for good" lands under the finger.** The confirm renders exactly where Delete was tapped, so a double-tap deletes with no undo, and the focused button unmounts, dropping focus to `<body>`. | `ProjectList.tsx:44` | S1 |
| T5 | **The hidden actions column squeezes the transcript.** Rows are a grid `34px 22px minmax(0,1fr) auto`; the actions stay in the layout at full width while invisible, so at 1440px lines wrap after four words and most of the row is empty (seen in the capture). Verify at build; the fix is the same as T3's: the actions overlay or take their own line. | `LineDoc.module.css:10,48` | S2 |
| T6 | **Instant state changes.** Every hover/pressed/focus/disabled colour change in the panel, plan card, switches and inputs has no transition; actions and the grip fade in 120ms. | `App.module.css`, `PlanCard.module.css`, `AutonomySwitch.module.css`, `QuestionCard.module.css`, `ChatPanel.module.css`, `LineDoc.module.css:48,131` | S2 |
| T7 | **Disabled looks like secondary.** Disabled primaries (raised background, line border, muted text) are visually the enabled secondary beside them: "Not yet" vs a disabled "Yes, I have it"; Approve vs Try again; Redo while busy. | `ConsentSheet`, `GoalStage`, `ReviewPanel`, `LoadScreen`, `CandidateCard`, `PlanCard` `.secondary` | S2 |
| T8 | Small: timeline labels overflow onto the next word and intercept its tap; `cursor: text` on a drag track; Backspace removes a line instantly (undo exists, no redo of a discarded take); mouse-only instructions ("Hover a line", "Click a word, shift-click…"). | `Timeline.module.css:20`, `LineDoc.tsx:234`, `Timeline.tsx:144`, `LineDoc.tsx:726` | S3 |

### 3. Performance and layout shift (high)

| # | Finding | Where | Sev |
|---|---|---|---|
| P1 | **Rows jump.** Takes, needs-you, failed and editor blocks fade in but the row's height snaps; everything below shifts. While planning, one spinner line is replaced by the whole plan card rising in. | `LineDoc.module.css:115`, `App.tsx:1278`, `PlanCard` | S2 |
| P2 | **Every timeupdate re-renders every word.** The playhead is inline style on the same component, no memo, no virtualisation. | `Timeline.tsx:111` | S2 |
| P3 | Progress fills animate `width`; the selection animates `left`/`width`; the orb animates `box-shadow` every frame. | `App.module.css:105`, `PlanCard.module.css:11`, `Timeline.module.css:30`, `Orb.module.css` | S3 |
| P4 | Index keys in the chat (remounting every bubble when a message scrolls past RECENT), the thinking list and the log; every past project mounts a `<video>` on first paint. | `ChatPanel.tsx:61`, `ActivityLog.tsx:23`, `ProjectList.tsx:30` | S3 |
| P5 | No `color-scheme` or `theme-color` meta: native controls, scrollbars, selects and the pre-CSS first paint are light. | `index.html` | S2 |

### 4–6. Layout, typography and colour (high / medium)

| # | Finding | Where | Sev |
|---|---|---|---|
| L1 | **Base text is 14px.** `body { font-size: 14px }` is why most controls land at 12–13px and full sentences (hints, log entries, "Voltage recommends", helper lines) sit at 12px; MASTER says 16 base, 13–14 for labels, nothing under 12. The project-state pill is 11px, the kbd and the drop marker 11.5px, the small avatar initial 9px. | `theme.css:56`, `ProjectList.module.css:13`, `LineDoc.module.css:18,140`, `Avatar.tsx:14` | S2 |
| L2 | **Overflow at 375px.** Two takes stay side by side at any width; the player's control row never wraps (Edited/Original pushed off); a long filename in the project list never truncates (`nowrap` without `min-width: 0`); the plan's needs-you option is `nowrap` with a sentence inside; a long log detail overflows its card; the ship sheet has no max-height or scroll on short phones. | `LineDoc.module.css:97`, `Player.module.css:12`, `ProjectList.module.css:11`, `PlanCard.module.css:49`, `ActivityLog.module.css:9`, `ShipSheet.module.css:1` | S2 |
| L3 | **Two export buttons.** The header shows *Export MP4* and *Download MP4* side by side once a render exists; the "inserts" sentence that explains a longer export is hidden under 1600px, i.e. nearly always. | `ExportBar.tsx`, `ExportBar.module.css:17` | S2 |
| L4 | `100vh` on three full-screen states (iOS toolbar overshoot); raw colours (`#000` ×5, `#fff` ×2, `#1B1714`, `#F6D3A4`, `#6B3B2E`, three copies of the same amber glow gradient). | `GoalStage`, `LoadScreen`, `SignIn`, `Player`, `Orb`, `App.module.css:37`, `QuestionCard` | S3 |
| L5 | Compact labels that can wrap: plan count, take label, score, state pill, "Starts at 0:04.96"; the speaker name input is a fixed `11ch` and clips. | `PlanCard.module.css:8,30-33`, `ProjectList.module.css:13`, `SpeakersBar.module.css:13` | S3 |

### 7–8. Animation, forms and feedback (medium)

| # | Finding | Where | Sev |
|---|---|---|---|
| F1 | **Controls that do not respond.** The plan checkbox, delivery and mix pills, Stop, Keep, Keep take n, Another take, Try again, Approve and Export show no pending state; the control looks ignored until the round trip returns, and Export can be clicked twice. | `PlanCard.tsx`, `LineDoc.tsx:424,473`, `CandidateCard.tsx:109`, `ExportBar.tsx:37`, `App.tsx:736` | S2 |
| F2 | **Errors far from their cause.** Plan-panel failures (toggle, reword, Stop, autonomy, the plan job) land in the red strip under the player in the other column; MASTER reserves the strip for the engine. | `App.tsx:1179` and its setters | S2 |
| F3 | **A silent discard.** An invalid "Starts at" value shows its hint in faint grey with no `aria-invalid`, and *Hear it* still runs, dropping the time and placing the line "after this line" without a word. | `LineDoc.tsx:244,322,353` | S1 |
| F4 | **Uploads with no progress.** A three-minute clip uploads with only the button label changing; no status, no progress bar, and the upload error has no alert role. Consent saving changes nothing but the grey. | `LoadScreen.tsx:57,65`, `ConsentSheet.tsx:24` | S2 |
| F5 | **Empty states with no action.** No projects → the list renders nothing; no lines → a sentence; no speech on the timeline → a sentence. | `ProjectList.tsx:21`, `LineDoc.tsx:155`, `Timeline.tsx:108` | S3 |
| F6 | Copy and small bugs: the send button is labelled "Preview" whatever it will do; "You have their permission?" with no word on what "Not yet" does; Escape on a rename commits the draft via blur; `clock()` renders "-1:-1" for a tiny negative time; "Copy link" success and failure are label-only. | `ChatPanel.tsx:77`, `ConsentSheet.tsx:19`, `GoalStage.tsx:93`, `transcript/format.ts:2`, `ShipSheet.tsx:40` | S3 |
| F7 | `scrollIntoView({behavior:'smooth'})` ignores reduced motion; the first paint while `getMe` runs is blank; the 400ms entrance. | `App.tsx:1113,1014`, `App.module.css:47` | S3 |

## The revamp, in five phases

Each phase is committed and merged on its own, with build, lint, typecheck and tests clean, and a headless-Chrome check at 375, 768 and 1440 px of the start screen, the goal stage, the editor (Bhaji Cam, p3) and the silent clip (p10). The order follows the skill's priorities and puts the global changes first so the component work lands on a settled base.

### R-1 · Foundations (theme, tokens, sizes) — fixes L1, T1 (shared classes), T6, A4, L4, P3, P5

- `body` to 16px; a written type scale in `theme.css`: 12 (label floor, `nowrap`), 13 (small label), 14 (compact body: log, hints, row meta), 16 (body), 20, 28, 36 (Fraunces). Every 12px *sentence* moves to 14; every label stays ≥12. The 11px pill, the 11.5px kbd and marker, and the 9px avatar initial go to 12.
- Shared control classes in `theme.css` (or a `controls.module.css` the components import): `.primary`/`.secondary` `min-height: 44px`; `.pill`/`.chip` `min-height: 36px` with `gap: 8px`; `.textButton` keeps its look but grows its hit area with padding and negative margin; `.iconButton` 44×44; segmented switches 36px tall with a 2px gap. Components adopt them rather than restating sizes.
- A 150ms `transition` on colour, border and background for every interactive class; the global reduced-motion rule already zeroes it. The 400ms entrance to 250ms; progress fills and the selection to `transform`; the orb's glow on a pseudo-element's opacity.
- Remove every `outline: none` or replace it with a 2px `--accent` ring (`box-shadow` where an outline would clip). Rows get `inset 0 0 0 2px var(--accent)` on `:focus-visible`, distinct from the 2px selected bar.
- Tokens for the raw colours: `--monitor` (#000), `--frame`, `--text-bright`, `--surface-2`, `--orb-highlight`, `--glow` (the shared gradient), and `--faint` restricted by a lint-like test: a stylesheet grep in the frontend tests fails if `--faint` is applied to a class that holds sentence text (the list is explicit).
- `100dvh` for the three full-screen states; `<meta name="color-scheme" content="dark">` and `<meta name="theme-color" content="#171412">`.

### R-2 · Say it out loud (semantics) — fixes A1, A2, A5, A6, A8, A9, A10, A12, A13

- **Live regions, few and well placed.** The chat list is `role="log" aria-live="polite"`. One `role="status"` region in the panel carries the thinking line, plan progress, the generating step and the header state word (one sentence at a time, atomic). Each row's state chip is `role="status"`; `.failed` and `.needs` are `role="alert"`. The upload card gets a status sentence and the progress bars get `role="progressbar"` with values and labels. `aria-busy` on the panel while planning or voicing, on main while the plan runs, on a row while its take is pending.
- **Real modals.** Ship and Consent move to native `<dialog>` with `showModal()` (focus in, Tab trapped, Escape closes, focus restored to the opener), `max-height: calc(100dvh - 48px)` and internal scroll; the overlay scrolls.
- **Structure.** `h1` for the brand or filename, `h2` for "The plan", "What I did", "Recent", the sheet titles — styled exactly as now. `<main>` on every screen; a visually hidden "Skip to content" link first in `#root`. The project list is `ul`/`li`; transcript rows are `role="list"`/`role="listitem"` (or groups with labels); roving `tabindex` inside rows so Tab moves row to row and arrows move within.
- **State in words.** `aria-pressed` on delivery chips; candidate metrics say "below 0.80" beside a failing value; timeline words in the selection are `aria-pressed` and a polite region says "Selected 0:04 to 0:06". The grip's `onClick` opens the Shift place control (the S key's path). The spend meter is `role="meter"` reading "Spent $0.12 of $5.00" and appends "near the cap" when `near`. Times get `aria-valuetext` / `<time>` with spoken seconds; scores are "Score 0.87". The "/" is `aria-hidden`; the speakers bar is a `role="group"`; scroll regions without focusable children get `tabIndex={0}` and a label.

### R-3 · Touch, phones and the row — fixes T1 (components), T2, T3, T4, T5, T7, L2, L3, L5, T8

- **The row's actions get out of the text's way.** Actions overlay the row's right edge (absolutely positioned inside the row, revealed on hover/focus-within) so the line keeps its full measure at every width; on `(hover: none)` the row shows one "…" button, 44×44, always visible, that opens the same actions as a small sheet under the row. The grip becomes a 44×44 target around its small glyph. Verify the desktop wrap goes away (T5).
- **Every target to size.** The audit's list, component by component, adopting R-1's classes: header controls, pills, time button, Undo/Move/links, the take and transport play buttons (44, visual circle can stay smaller inside), nudges, zoom controls, speaker name and voice (36), the scrubber's hit area to 44 (visual track unchanged), the Move block with a 44px transparent handle, timeline words `min-width: 24px` with a taller lane and a readable default zoom on coarse pointers.
- **Delete that cannot be fumbled.** The confirm pair renders as a row-wide strip ("Delete bhaji.mp4 for good?" · *Keep* · *Delete for good*) in a different place from the Delete button, focus moves to *Keep*, Escape keeps; a 5-second "Deleted · Undo" toast with `aria-live="polite"` after, backed by the existing soft-delete if there is one or a short server-side grace if not.
- **Disabled reads as inert.** `:disabled` on every class: `opacity: .5`, no border emphasis, `cursor: default`; where a reason exists it is shown in a sentence (CandidateCard: "Below the threshold — try again, or approve anyway").
- **Phone layouts.** Two takes stack under 600px; the player's controls wrap under 480px with the bar on its own line; the project name gets `min-width: 0`; the plan's needs-you option drops `nowrap` and renders its warning under the label; the log detail ellipsises with the full text reachable; compact labels (`.count`, `.score`, `.state`, "Starts at") are `nowrap`; the speaker name input sizes to content.
- **One export button.** The header shows a single state-driven button: *Export MP4* → *Exporting…* (disabled, `aria-busy`, progress in the status region) → *Download MP4* with *Export again* as a text button beside it; the "inserts" sentence shows at every width, wrapping under the button on phones.
- Timeline labels clip instead of overlapping; `cursor: col-resize` on the track; Backspace on a row asks for a second press within two seconds (Delete stays single); instructions say "tap or click".

### R-4 · Feedback and forms — fixes F1–F7, P1

- **Pending states.** A per-control busy flag set on click (checkbox, pills, Stop, Keep, Another take, Try again, Approve, Export): the control shows a small spinner or a dimmed pressed state and `aria-busy` until its prop changes; plan item toggles update optimistically and revert on error.
- **Errors where they belong.** Plan-panel failures become Voltage's reply in the thread or a sentence in the plan card's head with *Try again*; the strip under the player keeps only render and export errors. The upload error and the sign-in error get `role="alert"`.
- **"Starts at" cannot discard silently.** `aria-invalid` and `aria-describedby` on the field, the hint in `--amber` as `role="alert"`, *Hear it* disabled while the value is present and unparsable.
- **Progress you can see.** Upload progress from the request (status sentence + progressbar); Consent's primary says *Saving…*; *Copy link* reports "Link copied" or "Couldn't copy — select the link below" in a status span.
- **Nothing jumps.** Rows open with `grid-template-rows: 0fr → 1fr` (transform and opacity inside); three skeleton item rows at the plan card's height while planning; a working row shows a fixed-height placeholder for its take.
- **Empty states with a next step.** Project list: "Your projects will show here after your first upload." Transcript with no lines: the place editor (UX-5). Timeline with no speech: "Load another video" or the place editor.
- **Copy and small bugs.** Send button labelled by what it will do (*Plan*, *Change the plan*, *Answer*); the consent question as a question with "Not yet — keep the line as a draft"; Escape cancels a rename; `clock()` guards negatives; hover-only `title`s become visible helper text or `aria-describedby` (vendor breakdown as a popover button; the role guess's reason as a sentence; the voice description under the picker; "Approve anyway" with its note); the question option's warning renders under the button, never on amber.
- `scrollIntoView` respects reduced motion; the first paint shows the orb and "Opening…".

### R-5 · Polish and performance — fixes P2, P4, remaining S3s

- Timeline: memoise the word list on `[words, duration, selection]`, the playhead in its own child; virtualise rows above ~200 lines if a long clip ever needs it.
- Stable keys: message ids on `ChatMessage`, log entry ids. Past projects' `<video>` frames mount lazily via an IntersectionObserver, or the backend's frame image (UX-5 SV-1) replaces them.
- Roving tabindex inside transcript rows; `aria-valuetext` everywhere a time is spoken; kbd and marker to 12px; the remaining raw colours tokenised.
- A re-run of every audit query in this file, and the skill's pre-delivery checklist (no emoji icons; pointer cursor; 150–300ms hover transitions; 4.5:1 text; visible focus; reduced motion; 375 / 768 / 1024 / 1440), recorded here as the as-built note.

## Order and exit

| Phase | Lands | Exit |
|---|---|---|
| R-1 Foundations | theme, tokens, shared controls, transitions, focus, meta | No `outline: none` in the tree; no `--faint` on sentences (test); every `.primary`/`.secondary` ≥44px and every pill ≥36px by computed style in a jsdom test; captures at three widths unchanged in layout except for size. |
| R-2 Semantics | live regions, dialogs, headings, landmarks, list roles, pressed states | A VoiceOver pass (the user's, with a short script in the as-built note) hears Voltage's reply, each row's state change and the plan's progress; axe-core in the frontend tests reports zero violations on each screen. |
| R-3 Touch and the row | actions overlay, 44px targets, delete strip, disabled look, phone layouts, one export button | Transcript lines at 1440 use the full column; at 375 no horizontal scroll on any screen; every target ≥44×44 in the computed-style test; Delete needs two deliberate actions in different places. |
| R-4 Feedback | pending states, errors in place, "Starts at" validation, upload progress, skeletons, empty states, copy | No control stays silent for a round trip; the red strip shows only engine errors in the e2e flow; an invalid time cannot voice. |
| R-5 Polish | keys, memo, lazy frames, remaining S3s, the checklist re-run | The pre-delivery checklist all ticked; the audit queries re-run clean; as-built note written. |

Tests to add along the way: a computed-style test over every rendered button for the 44/36 floors; a stylesheet test that `--faint` is never on a sentence class; axe-core (`vitest-axe`) on each screen; dialog focus-trap tests; live-region presence tests; a `clock()` negative test; Escape-cancels-rename test; "Starts at" invalid → *Hear it* disabled test. Counts expected to rise from 198 frontend tests to roughly 240.

## Left alone, on purpose

- The visual direction, the fonts and the palette (see above).
- The word timeline behind *Precise* stays hidden by default; it gets the touch and ARIA fixes but no redesign (G14 of the UX plan still says it is noise for most users).
- Lip-sync, own voice, the picture that flexes: the natural-fit roadmap, not UI.
- UX-5 (the silent clip) builds on R-1's classes and R-2's regions; it should follow R-1 and R-2 rather than precede them, so its new screens are built once.

## As built (2026-10-04, same day)

Five commits, each merged to main with build, lint, typecheck and tests clean: R-1 `2db5a03`, R-2 `d453f71`, R-3 `b86dffa`, R-4 `a154e27`, R-5 `5b16dbf`. Frontend tests 198 → 217 (23 files); backend 501, untouched. Nothing in the backend changed.

**What landed, phase by phase.**

- **R-1.** `theme.css` carries the type scale (`--fs-12…36`), the target floors (`--target` 44, `--chip` 36, `--target-gap` 8), one transition (`--t` 150ms, `--t-open` 250ms) and tokens for every colour a component used to spell out (`--surface-2`, `--text-bright`, `--monitor`, `--frame`, `--glow`, `--scrim`, `--orb-highlight`, `--accent-bright`). The body is 16px; every button, select and input is 44px by default; chips opt down to 36 with 8px gaps; text links keep their look and grow their hit area with padding and a negative margin. Disabled is `opacity: .5`. Fills animate `transform`; the orb's glow is a pseudo-element's opacity; `100dvh` everywhere; `color-scheme` and `theme-color` metas. `styles/theme.test.ts` keeps the contract from the stylesheets themselves: no raw colour, no outline removed without a ring, no text under 12px, `--faint` only on the grip, chips with a stated height, no `width`/`left` transitions, no `vh`.
- **R-2.** `useModal` gives the Consent and Ship sheets what a modal owes the keyboard. The chat is a polite log that says who spoke. One status region per panel; progressbars with values; row chips and working blocks are status, failures are alerts. `h1` for the brand, `h2` for every panel and card title, `<main>` on every screen, a skip link. Transcript rows are listitems in a list (the old `role="row"` had no grid). Delivery chips carry `aria-pressed`. The grip's label promises a drag or Enter, and Enter opens the place control. An unreadable "Starts at" is `aria-invalid`, explained in rose, and Hear it is disabled. Escape cancels a rename; the role guess's reason is visible.
- **R-3.** The row's actions are laid over its right edge (clipped away when hidden, so they neither squeeze the line nor catch taps), with a "…" button that opens them under the line on touch; the grip is a 44px target; Backspace asks twice, Delete removes at once. One export button: *Export MP4* → *Exporting…* → *Download MP4* with *Export again* beside it; the "inserts" sentence shows at every width. Delete is a strip across the row with Keep focused first and "Deleted · Undo" for five seconds before the request goes. Two takes stack under 600px; the transport wraps under 480px; timeline lanes are 44px tall on a coarse pointer; a disabled Approve says why.
- **R-4.** Keep, Another take, Approve, Redo, Stop, Go ahead and the plan's ticks and pills show a pending state with `aria-busy` until their request returns. Plan and conversation failures are Voltage's reply in the thread; the strip under the player keeps render, export, move and keep errors. The send button is labelled *Plan it*, *Change the plan*, *Answer* or *Preview the change*. Three skeleton rows stand where the first plan will be; rows unfold with `grid-template-rows`. The upload shows a bar and a sentence. The voice's description and the approve-anyway note are visible. `clock()` never shows a negative time. `feedback.test.tsx` covers the pending states, the invalid time, the send label and the clock.
- **R-5.** The timeline's words are a memoised child, so the playhead moves alone. A past project's frame mounts when its row nears the viewport. Roving focus in the transcript: Tab moves row to row and only the focused row exposes its controls.

**The checklist, re-run.** No emoji icons (inline SVG throughout). `cursor: pointer` on every button (global). Hover and state transitions 150–250ms (global). Text contrast: `--faint` remains only on the grip glyph; everything readable is `--muted` or brighter. Focus visible: three `outline: none` sites remain, each with a 2px ring on the element or its container (the chat composer, the goal card, the transcript row). Reduced motion: the global rule zeroes every transition and animation, including the new shimmer, slide and unfold. Widths: the start screen was captured at 1440 and 500 — no horizontal scroll, long filenames wrap, Delete is a tap target; the upload state was captured by accident at 1440 and reads right (indeterminate bar, sentence, an inert button). Tooltips left on purpose: the avatar's name (its `aria-label` says the same), the send button (same as its label), the filename (full name on hover, shown in the ship sheet too), the spend meter's breakdown (also in its `aria-valuetext`).

**Left for later.**

- ~~Real upload progress~~ — done the same evening with UX-5: the upload goes through `XMLHttpRequest` and reports its share ("Uploading, 40%", a valued progressbar), then "Transcribing…" indeterminate; `vitest.setup.ts` gives the tests an XMLHttpRequest that routes through their fetch mock.
- ~~The silent clip's empty transcript~~ — the place editor landed with UX-5 the same evening.
- The spend meter's breakdown as a visible popover rather than `aria-valuetext`.
- The editor was captured at 1440 after R-5 (Chrome's new headless mode reaches a project only under `--virtual-time-budget`, minutes per capture): the transcript's lines now run the full column — "Hi, I want to buy groceries." on one line where it wrapped after four words before — the header shows one export state (*Download MP4* · *Export again*) with the inserts sentence beside it, the chips and the composer are at size, and the voice's description reads under the picker. Phone-width captures of the editor did not complete headlessly; the start screen did (500px, no horizontal scroll). A VoiceOver pass is the user's.
