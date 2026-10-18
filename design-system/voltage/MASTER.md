# Design System Master File — Voltage

> **LOGIC:** When building a specific page, first check `design-system/voltage/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** Voltage (AgenticVideoEditor) · **Rewritten:** 2026-10-18 (UX-9, "the studio"), replacing the zinc room of UX-8. Source of truth in code: `frontend/src/styles/globals.css`, `frontend/components.json`, `frontend/src/components/ui/`. The user's two mocks (dark, then light) are the reference; what was changed from them and why is in `docs/superpowers/plans/2026-10-18-ux9-the-studio.md`.

## The room

A **studio**: three panes side by side — the player with its lanes, the transcript and takes, Voltage — and a slim dock on the left. Stock **shadcn/ui** (new-york style) on Tailwind v4, **light and dark as siblings**: slate and cyan in the light (#f1f5f9 behind white cards, cyan 600 as the accent), obsidian and cyan in the dark (#051424 behind #0b0f17 cards, electric cyan as the accent). Flat surfaces, 1 px borders, an 8 px radius, `shadow-xs`/`shadow-sm` at most. **No gradients, glows, frosted panels or blurs**, however the mocks drew them; the accent does the work. Voltage's presence is the bolt (`Presence`), a spinner while it works. The picture never stops; the line is the unit; the user's next action sits on the thing it acts on.

Theme: follows the system, with a Light / Dark / System menu in the header (`ThemeToggle`, `lib/theme.ts`); saved in `localStorage` (`voltage-theme`, in try/catch); an inline script in `index.html` sets `.dark` before first paint.

## Tokens (use the Tailwind utilities they generate, never a raw colour)

All colours are OKLCH variables in `globals.css`, defined for `:root` and `.dark`, exposed to Tailwind with `@theme inline`. `theme.test.ts` fails on a raw colour, a gradient, a blur, a glow, text under 12 px, a missing token or a missing dark value.

| Role | Utilities | Light → Dark |
|---|---|---|
| Page, text | `bg-background` `text-foreground` | slate 100 / slate 900 → obsidian / #d4e4fa |
| Cards, panels, popovers | `bg-card` `bg-popover` (+ `-foreground`) | white → #0b0f17 |
| **Primary action, the accent** | `bg-primary` `text-primary-foreground` `text-primary` `border-primary` | cyan 600 on white → electric cyan on #002027 |
| Quiet fills, hover, selected | `bg-secondary` `bg-muted` `bg-accent` | slate 100–200 → #0f1420–#1c2438 |
| Secondary text | `text-muted-foreground` (≥ 4.5:1 on background and card in both modes) | slate 500 → slate 400 |
| Borders, inputs, focus | `border-border` `border-input` `ring-ring` | slate 300 / 200 → #233143 / #162332; the ring is cyan |
| Errors | `text-destructive` | rose 600 → rose 400 |
| **Proposed**: a take to hear, words Voltage wrote, a pill in A2 | `text-changed` `bg-changed-soft` `border-changed` | cyan 700 on cyan 50 → cyan 300 on cyan 950 |
| **Added / in the video / kept** | `text-ok` `bg-ok-soft` `border-ok` | emerald 700 on emerald 50 → emerald 300 on emerald 950 |
| **Needs you / flagged / removed** | `text-needs` `bg-needs-soft` `border-needs` | rose 600 on rose 50 → rose 300 on rose 950 |
| Speakers A–D | `text-spk-a..d` `border-spk-a..d` (and `bg-spk-a..d/25`) | blue, violet, amber, pink |
| The picture's surround | `bg-monitor` | near-black in both |
| Radii | `rounded-sm/md/lg/xl` = 4 / 6 / 8 / 12 px off `--radius: 0.5rem`; nothing larger than `rounded-xl` |

Colour never carries meaning alone: every state has a word beside its colour (Proposed, Added, Removed, Voicing…, Needs you), and a dot before a count.

## Typography

**Geist** (variable, self-hosted via `@fontsource-variable/geist`) for words; **JetBrains Mono** (`@fontsource-variable/jetbrains-mono`) for times, money, counts, timecodes, lane labels and mono facts — through `font-mono` or the `.tnum` class, which now sets the mono face as well as tabular figures. No external font request.

Scale: `text-xs` 12 px is the floor (labels, `kbd`, lane names, mono facts; never a sentence); `text-sm` 14 for compact UI, chips and card meta; `text-base` 16 for the transcript's words and inputs; `text-chat` (15 px / 1.6) for what Voltage and the user say. Headings `font-semibold tracking-tight`, one `h1` per screen. Uppercase labels are `text-xs font-mono uppercase tracking-wide text-muted-foreground`. Verdicts and states are sentences first, numbers behind them. **No number appears that was not measured or recorded**: no FPS, codec, LUFS, latency or engine status lines.

## Layout: the studio

Desktop (≥ 960 px): a 13-row header, then a row of panes with an 8 px gutter — the dock (40 px), **the player and lanes** (≈ 41%), **the transcript and takes** (≈ 35%), **Voltage** (≈ 24%). Each pane is a `bg-card` panel with a 1 px border and `rounded-lg`, its own header (`text-sm font-semibold`), its own scroll. Under 960 px the panes stack in that order with a 16 px gutter, no horizontal scroll; Voltage can tuck away to a strip with its composer. Full-height screens use `dvh`, never `vh`. 4 px grid via Tailwind.

- **Header:** brand (bolt, VOLTAGE), the file badge (name and length, mono), the play switch (Original · With proposals · Final), the autonomy switch (Check with me · Just do it) — autonomy lives here only — then the spend pill (spent / ceiling, a bar, voice characters), Make a variant, Export again, **Export MP4 / Download MP4** (the one filled primary button), What Voltage may do (sliders icon), theme, user.
- **Dock:** Projects, Workspace, Speakers, What Voltage may do. Real destinations only.
- **Player pane:** the picture on `bg-monitor` with the caption strip; the transport dock (play, timecode in mono, Precise); the retime strip (what the preview carries, what flexed); then the **lanes** (`Lanes`): a ruler with the playhead, V1 Picture (copies, "Flexed +8%", "Held 0.6 s"), A1 Spoken (pills by speaker; removed struck; replaced marked changed), A2 Added (every added or proposed line as a pill; **overlapping pills pack into sub-rows so coexisting audio is visible**; a "−12 dB" tag for a background layer; the placing block when a take is being moved), A3 Tone (room-tone patches). Every pill is a button that seeks; the Precise word timeline opens under the lanes.
- **Transcript pane:** header with "Transcript & takes · N lines", **Add all (N)**, a speaker filter (All · each speaker with its count) and the state counts (● N Proposed · ● N Added · ● N Removed). The list is cards, one per audio line (see the transcript rules below).
- **Voltage pane:** header (bolt, "Voltage", the autonomy word), the thread (the user's bubble right in `bg-accent`, Voltage's words left, steps as a list with money on the right, the Thinking line, a question as a **gate card** with its options), the plan's record, and the composer under "Instruction · Turn cap $x.xx".

**Targets:** shadcn controls are 36 px with a mouse and **44 px on coarse pointers** (`pointer-coarse:`); custom clickable elements add `pointer-coarse:min-h-11`; 8 px between adjacent targets.

## Motion

`tw-animate-css` enter/exit (150–250 ms); `prefers-reduced-motion` zeroes every transition and animation. At most one or two moving things per view: the playhead, and a small pulsing dot on a line being voiced. Nothing else pulses, waves or glows.

## The transcript (one transcript, four verbs)

- A **card per audio line**, in time order: a spoken line; a shifted line where it now plays; an added line in the video; a proposed or working added line. Lines at the same moment are separate cards and play together; a layer never changes a spoken line's words.
- **State words** beside their colour: nothing (as shot), **Proposed**, **Added**, **Removed**, **Voicing…**, **Needs you**, **Couldn't voice it**, **Moved**.
- **The hero proposal card** (`border-primary`, `shadow-sm`): who and when (mono), the state chip; Before/After as a diff in a `bg-muted` box; the **delivery chips** (Warmer · Firmer · Calmer · More excited · Slower — the take's own delivery filled; a click asks Voltage for that take again, said that way); the direction line Voltage wrote; the **facts grid** (voice and model · stability / style · fit · picture) and the **measured line** (SIM-o, UTMOS, prosody against their thresholds, with "flagged" and why when a check failed); then **Add it (K) · Hear it · Edit it · Discard (Del)**, Add it the filled one. A removal proposal reads "Remove it".
- An **added** card: who/when, the words, "In the video · plays over the picture · with N other lines at this moment", Starts at · Move, the level ("background (−12 dB) · Make it foreground" / "Make it background"), and **Hear it · Take it out · Edit it**. A **removed** card: struck words, "Room tone in its place", **Put it back**. A **voicing** card: the words in italics, a thin progress bar, the step in words. A line taken out of the video says "Taken out of the video. Add it puts it back; Discard drops it for good."
- Keys: ↑↓ move, Enter edit it, Space hear it, K add it, Delete discard, U take it out, A add after, S shift, `/` the composer, `\` hides Voltage. Roving focus: only the focused card exposes its controls to Tab.
- The in-place editor opens on the line's current words and choices (never the original once moved past); its submit is **Voice it**, and the take comes back proposed.

## Interaction rules

- Everything is reachable from the keyboard with a visible focus ring (`focus-visible:ring-[3px] focus-visible:ring-ring/50`); `outline-none` only beside a ring. Dragging is never the only way (Move up / Move down, typed times, nudge keys).
- Every wait is spoken: one `role="status"` region per pane, `role="log"` on the thread, `role="alert"` for failures, `aria-busy` on the region doing the work. Disabled controls read as inert.
- Sheets are real modals (shadcn `Dialog`). Every screen has an `h1`, a `<main>` and a skip link.
- Icons are `lucide-react` SVG, never emoji; a meaningful icon has a text alternative; beside visible text it is `aria-hidden`.
- Loading reserves the space of what is coming and says in a sentence what is happening. Errors appear where they belong, in one sentence with one action.
- Compact labels do not wrap; nothing lives only in a tooltip.
- Nothing in the workspace voices a line or changes the plan except a turn; the row's Add it / Discard / Take it out and the moves are the user's own hands. Every composer path is a turn. "What Voltage may do" (autonomy, the turn's spend cap, the effort) is a sheet off the header.
- Playback: Final (the added lines), With proposals (a preview render with the proposed takes mixed in, a status line while it renders), Original.

## Components in use

shadcn: `Button` `Input` `Textarea` `Badge` `Card` `Dialog` `Popover` `DropdownMenu` `Progress` `Skeleton` `Switch` `Select` `Tooltip` `Separator` `Label` `ScrollArea` `Toggle` `ToggleGroup`.

Voltage's own: `Lanes` (the multitrack), `LineDoc` (the transcript cards and the in-place editor; `EditorControls`, `editorStyles`), `PlanCard`, `ReadingCard`, `PlaceEditor`, `Player` (picture, caption, transport), `Timeline` (the Precise word track), `ChatPanel`, `ActivityLog`, `SpeakersBar`, `AutonomySwitch`, `SpendMeter`, `ExportBar`, `ConsentSheet`, `ShipSheet` (only when Voltage ships on its own), `WhatVoltageMayDo`, `LoadScreen`, `ProjectList`, `SignIn`, `Avatar`, `Presence`, `ThemeToggle`.

## Adding a component

`cd frontend && npx shadcn@latest add <name>`, then check the generated file's `cn` import (`@/lib/utils`) and add `pointer-coarse:` sizes if it is a control. Never spell a colour; add a token to `globals.css` (both `:root` and `.dark`, plus `@theme inline`) if a new meaning is needed.
