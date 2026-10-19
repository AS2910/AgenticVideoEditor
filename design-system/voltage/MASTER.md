# Design System Master File — Voltage ("Volt")

> **LOGIC:** When building a specific page, first check `design-system/voltage/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** Voltage (AgenticVideoEditor) · **Rewritten:** 2026-10-19 for **Volt**, the user's design hand-off in `voltage-design/` (`HANDOFF.md` + eleven screens), replacing the UX-9 studio. Source of truth in code: `frontend/src/styles/globals.css` (tokens and the class layer), `frontend/src/components/ui/`. What was adapted from the hand-off and why is in `docs/superpowers/plans/2026-10-18-volt.md`.

## The idea

**Paper and ink, one volt.** A warm off-white page (`#F3F3EF`) with white surfaces, near-black ink (`#0B0B0C`) for type, borders and the primary button, and one accent — **volt** (`#D7FF3A`) — used only as a fill with ink text, or as text on the black pane. Amber (`#FFB020`) is the one other colour, for a step that waits on you. Flat surfaces, **1.5 px ink borders** where something is actionable, and a **hard offset shadow** (`4px 4px 0 ink`, `7px 7px` on hover) on exactly three things: a proposal card, a gate card, a primary button. No gradients, glows, blurs or drop shadows anywhere (`theme.test.ts` fails on them). Dark mode is the same room at night: `#0E0E10` page, `#17171B` surfaces, the same volt and amber. **Voltage's pane is black in both themes** (`--pane`), so the agent is always the dark half of the screen.

Theme follows the system; Light / Dark / System is chosen on the Settings page (`lib/theme.ts`, `localStorage` `voltage-theme` in try/catch, `.dark` set before first paint by `index.html`).

## Tokens (use the utilities; never a raw colour)

OKLCH/hex variables in `globals.css` for `:root` and `.dark`, exposed through `@theme inline`. shadcn roles are mapped onto them so stock components fit.

| Role | Utilities | Light → Dark |
|---|---|---|
| Page, text | `bg-background` `text-foreground` | #F3F3EF / #0B0B0C → #0E0E10 / #F3F3EF |
| Surface (cards, header) | `bg-card` | #FFFFFF → #17171B |
| Sunk (rows on hover, wells, inputs) | `bg-sunk` | #EAEAE4 → #202025 |
| Hairlines / stronger lines | `border-line` `border-line2` | #DEDED6 / #C8C8BE → #26262C / #35353D |
| **Ink**: borders, the primary button, stamps' text | `border-ink` `bg-ink` `text-ink` | #0B0B0C in both |
| **Volt**: the one accent, as a fill with ink text | `bg-volt text-ink`, `text-volt` only on the pane | #D7FF3A in both |
| Amber: waiting on you | `bg-warn text-ink` `border-warn` | #FFB020 in both |
| Secondary / faint text | `text-muted-foreground` `text-faint` | #5C5C58 / #8A8A84 → #A3A39C / #6E6E68 |
| The picture's stage | `bg-pic` | near-black in both |
| Lanes (tracks panel) | `bg-lane` `bg-lane2` | warm greys |
| **The pane** (Voltage) | `.pane` → `bg-pane text-ptext`, `text-pmuted`, `border-pline`, `bg-psunk` | #0B0B0C → #050506; text #F3F3EF; muted #9A9A94; line #26262C; sunk #141418 |
| shadcn roles | `primary`=volt/ink, `changed`=ink, `changed-soft`=volt, `ok`, `needs`=warn, `border`=line2, `ring`=text | |
| Radii | 4 / 6 / 8 / 10 / 12 px (`rounded-sm` … `rounded-xl`, `rounded-[10px]` for rows); nothing larger than `rounded-xl` except circles | |

Colour never carries meaning alone: every state has a word (Proposed, ✓ In the video, Waiting on you, Removed, Voicing…) in a `.stamp`, and a marker on the scrubber has a title.

## Typography

Three faces, self-hosted (`@fontsource-variable/*`, no network request):
- **Space Grotesk** (`.disp`, `--font-display`, letter-spacing −0.02em) for display: the wordmark, page titles (26–40 px), card titles, big numbers, and every `.btn`.
- **Geist** (`--font-sans`, body 14 px) for UI and sentences; the transcript's words are `.say` 16 px / 1.55.
- **JetBrains Mono** (`--font-mono`, `.tnum`) for times, money, counts, tags and the trace. `.tag` and `.who` are 12 px mono, uppercase, tracked (.05–.06em).

**12 px is the floor**; nothing smaller, nothing in 8–10 px however the hand-off drew it. One `h1` per screen. Verdicts are sentences first; **no number appears that was not measured or recorded.**

## The class layer (`globals.css` `@layer components`)

The hand-off's vocabulary is a small set of classes, used by name so a screen reads like the mock:

- **Buttons:** `.btn` (38 px, ink border, display face) with `.volt` (volt fill, offset shadow on hover), `.ink` (ink fill, volt text; inverted in dark), `.ghost` (pane outline), `.sm` 32 px, `.lg` 46 px, `.shine` (one sweep on a primary CTA). `.act` is the quiet text verb (Edit it, Discard, Take it out). `.pill` is a choice (delivery), pressed = volt. `.sugg` is a suggestion chip on the pane. `.kbd` is the key hint beside a verb (␣, K, /).
- **State:** `.stamp` (volt, mono uppercase), `.stamp.need` (amber), `.stamp.in` (outline: ✓ In the video), `.stamp.inkd`.
- **Transcript:** `.row` (76 px time column + body; the app adds a 24 px grip column), `.row.prop` (a proposal: card, ink border, offset shadow, `pop` in), `.waiting` (dashed ink: a step waiting on you), `.who`, `.say`, `.meta`.
- **Playback:** `.segs` / `.seg` (Edited · With proposals · As shot; the chosen one is ink with volt text; O flips Edited ↔ As shot; with no live edits a plain "As shot" label instead), `.meter` (a measured score), `.lane-n`, `.blk`.
- **The pane:** `.pane`, `.pm` (muted on black), `.bubble` (your words, right), `.trace` with `.ln .ts .g .c .tool` (one step per line: time ├ sentence tool cost), `.gate` (Your go is needed), `.wave` (Voltage's presence: volt bars, `.busy` fast, `.need` amber).
- **Motion:** `wv rise pop fill shine nudge scan grow blink stampin ringpulse` keyframes; `.rise(.d1-3)`, `.fillin`, `.scan` (the 2 px line that sweeps the picture while Voltage looks), `.grow`, `.blinkdot`, `.stampin`, `.rec`. `prefers-reduced-motion` zeroes them all.

## Layout

**Account pages** (Projects, Voices, Usage, Settings, Billing; `pages/Shell.tsx`): a 62 px header with a 1.5 px ink rule — wordmark, `.nav` (mono uppercase; the current page is ink with volt text), a right slot, the account circle (initial in a 34 px ring) — then `<main>` with the page's own grid (Projects: hero drop zone + cards; Voices: three columns + the black "make a voice" pane; Usage: tiles + bars + a table; Settings: a side nav + sections).

**The editor** (`App.tsx`): the same header carrying the file name, the length and voices tag, the play `.segs`, the autonomy word (Check with me ▾ → the What Voltage may do sheet), the spend (`$spent ▮ $ceiling`, a link to Usage), **Export** (`.btn.ink.sm`, to `#pN/export`), the account circle. Below, two panes: **the work** (left; `max-width: 820px` centred; the picture ≤ 720 px with its mode tag, clock, caption and scan line; the transport row — ink play, mono clock, the scrubber with markers (volt = proposed, ink = in the video, amber = waiting) and the playhead, **Tracks ▾**; then the transcript) and **Voltage** (right, 400 px, `.pane`). Under 960 px they stack. `dvh`, never `vh`.

**Targets:** 32 px `.sm` buttons with a mouse and 44 px on coarse pointers (`pointer-coarse:`); 8 px between adjacent targets; every icon-only control has an `aria-label`.

## The transcript (one transcript, four verbs)

- `Transcript` in display 26 px · `N lines` · `<volt>P</volt> proposed · A in the video` · **Add all N** (`.btn.volt.sm.shine`, when more than one).
- A **row per audio line**, in time order: a spoken line; a shifted line where it now plays; an added line in the video; a proposed or working added line. The first line is `.who` + stamp; then `.say`; then `.meta`; then the verbs.
- **A proposal** is `.row.prop`: words at 18 px with `<ins>` (volt highlighter) and `<del>`, one line of facts (whose voice · the verdict · what the picture does), then **Hear it ␣** (`.btn.sm`) · **Add it K** (`.btn.volt.sm`) · Edit it · Discard (`.act`). **Edit it opens the depth in place**: Before/After, the delivery pills (+ "Your words…"), Voltage's direction, a facts grid (Voice · Model · Dials · Fit), the Measured tiles with meters (Voice match, Natural, Prosody, Room against their bars), "Lip-sync · not measured yet", then Hear it · Add it · Voice it again · Change the words · Discard · Less ↑.
- **A line in the video** shows `✓ In the video` and, on hover or focus, Hear it · Take it out · Edit it as `.act`s.
- **A line as shot** shows `.who` and `.say`; its verbs (Hear it · Edit it · Discard · Add a line after · Move up/down · Shift to a time…) appear on hover/focus, or behind "…" on touch.
- **Long runs of untouched lines fold** to "+ N more lines" once anything is proposed or in the video; the current, selected, focused or edited line never folds; arrow keys unfold as they pass.
- Keyboard on a focused row: ↑↓ move · Enter edit · ␣ hear · K add · ⌫ discard · A add after · S shift · U take it out · / ask Voltage.

## The pane (Voltage)

Header, always one line: the wave, **Voltage** (display 18), the state word (`ready` · `working` · `reading` · `N proposed` · `needs your go`; it truncates, never wraps), and an info button on the right whose tooltip names the engine (`Opus 5.5 · high`, only when the model is known). Below 380 px of pane the brief and voices chips fold behind a **Context** chip (container query on `.pane-root`). The thread is **turns**: your `.bubble`, the **trace card** (Trace · N steps · T s, one `.ln` per step with time, tool and cost), Voltage's words (Markdown), a question as a **gate card** (⚡ Your go is needed) or a question card. Options are `.btn.sm.opt`, stacked 8 px apart, wrapping their words (fit to them, at most the card's width): Voltage's pick first with a small "Voltage's pick" tag, a long option as a short label (about 40 characters) with the full sentence beneath; under a gate the first option is `.volt.shine`, Not yet quiet. The money is one sentence ("This turn has $0.00 left of its $0.50 cap."); when the turn's cap caused the question, the first option is the way through ("Go ahead, allow $0.04 more"). Earlier turns collapse to chips. The thread scrolls in its own area under a fixed header and composer, its top fading out; new content scrolls in only when you are near the bottom, else a "New from Voltage ↓" pill waits. The pane never scrolls sideways (`.pane-root`: overflow-x hidden, min-width 0 on every child, overflow-wrap anywhere; checked at 320/390/440 px by `npm run test:visual`). Under the thread: suggestion chips (the first read's examples), then the composer ("Describe a change", `/` focuses it) with "Turn cap $x.xx" and the send button named for what it does (Send · Answer).

**The first read** (nothing said yet): the picture with a big volt play, **Who's speaking** (Voltage's guess per speaker, lines and seconds, Rename, ✓ Looks right), the transcript; the pane carries the opening line, what Voltage saw on a silent clip (the place, Looks right / Correct it) and the example chips. **While Voltage works**: the scan line sweeps the picture with the step beside it, the row it is on reads `Waiting on you` (dashed) when it stops for you.

## Folders, tours and help (2026-10-19)

- **Home** keeps a 260 px sidebar of projects (folder glyph, count; "Standalone videos" dashed). Video cards carry a project chip (dashed "No project"). The ••• menu is a small card with an ink border and a volt offset shadow.
- **Project page**: the brief card has the volt offset shadow (it is the project's one primary surface); the other side cards are plain ink-bordered panels; Voltage's suggestion sits on the black pane colour inside the brief card.
- **Move dialog**: radio rows; the chosen one is volt with ink text; the voice question is a sunk panel with an ink border.
- **Editor crumb**: a 34 px chip with a volt folder (dashed and muted when standalone); its menu shows the brief Voltage is using. The pane shows context chips under its header (first one volt).
- **Tour**: a dimmed backdrop of four panels (no blur), a 2 px volt ring around the target, the coach card with a volt offset shadow; the highlighted control stays usable. **Tips** are black cards with a volt offset shadow and one Got it. The **Get started** pill is ink with volt text, bottom left.
- **Keyboard sheet** and **Help** use `.kbd` keycaps and the article reader as a right-hand drawer.

## Interaction rules

- Every change is a proposal first; nothing is in the video until **Add it**. The user's next action is the last element of whatever it acts on.
- A paid or committing step waits as a gate card under Check with me (and for whatever `ask_before` keeps under Just do it); the answer is the next turn.
- Playback: Final · With proposals · Original; "With proposals" is a preview render keyed to the takes it carries. Hear it on a proposal plays the take in place; a replacement mutes the original under it.
- Nothing is voiced outside a turn: Edit it → Voice it, delivery pills, "Voice it again", a chip — all are sentences said to Voltage.
- Focus is visible everywhere (3 px ring at 50 %); `outline-none` only with a ring; sheets are real dialogs (focus in, Escape, focus back).
- No invented speech: Whisper's hallucinated lines are screened before anything is built on them; no placeholder reply stands for Voltage.

## Components in use

shadcn `button`, `input`, `textarea`, `dialog`, `badge`, `toggle` under the class layer; `Player`, `Lanes` (+ `Timeline` for Precise), `LineDoc`, `PlaceEditor`, `VoltagePane`, `WhoSpeaks`, `WhatVoltageMayDo`, `ConsentSheet`, `Wordmark`/`Wave`; pages under `src/pages/` with `Shell`, `bits` (`Tile`, `FillBar`) and `fmt`.

## Adding a component

Use the class layer first (`.btn`, `.act`, `.pill`, `.stamp`, `.row`, `.tag`); add a token to `globals.css` for both modes and to `theme.test.ts`'s list before using it; never a raw colour, gradient, blur or `shadow-[`; keep 12 px as the floor; name every control; test light and dark.
