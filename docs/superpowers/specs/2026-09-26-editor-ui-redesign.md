# Editor UI redesign

**Date:** 2026-09-26 · Method: the `frontend-design` skill — a plan, a critique of the plan, then the build.

## The subject

This is **ADR** — automated dialogue replacement — the post-production job of re-recording lines after the shoot, done here by a model instead of a booth. The people using it cut ads and short social video: they think in *lines*, *takes* and *who says what*, not in waveforms.

What ADR's own trade already has, and this design borrows:

- **The script** is the working surface. Supervisors mark up a printed script, not a timeline.
- **Screenplay format**: the character's name over the line, set in Courier. Courier *is* the vernacular here — every script is set in it.
- **Revision marks**: a revised line gets an asterisk in the right margin, and revised pages are printed on coloured paper (blue first). That is exactly what an approved edit is.
- **The monitor** sits in a dark, neutral surround so picture reads true.
- **Takes**: each attempt at a line is a take; one is circled (approved).

## Pass one — the plan

### Palette

| Name | Hex | Role |
|---|---|---|
| Bay | `#15161A` | the room: page background around the monitor |
| Console | `#1F2127` | controls, timeline, dock surfaces |
| Script paper | `#F3F4F1` | the script page — the one light surface |
| Ink | `#1E1F24` | script text |
| Revision blue | `#2E5BDB` | revised lines, the approve action, focus |
| Revision tint | `#E3EBFB` | background of a revised line (blue revision pages) |
| Caution | `#B7791F` | continuity warnings, spend near its limit |

Speakers get two more inks, used only for their name and dot: `#0E8A7A` (A), `#B4467E` (B); further speakers cycle muted tones.

### Type

- **Courier Prime** — the script's lines and character names. Designed for screenplays; this is the one place type carries the brief.
- **Instrument Sans** — everything else: controls, messages, labels. Tabular figures for timecodes (not a monospace).
- Sizes: script 15/24; UI 13–14; header 15. Line length in the script ≤ 62 characters, as a screenplay column.

### Layout

```
┌──────────────────────────────────────────────────────────────────────────┐
│ ← Projects   bhaji.mp4                     $0.12 of $2.00   [Export MP4] │
├────────────────────────────────────────┬─────────────────────────────────┤
│                                        │  Cast  ● Customer  [Brian ▾]    │
│                                        │        ● Shopkeeper [Chat's ▾]  │
│            MONITOR (video)             │ ┌─────────────────────────────┐ │
│                                        │ │ 0:05   CUSTOMER*            │ │
│                                        │ │        Hi, I want to buy    │ │
│                                        │ │        groceries.         * │ │
│ ▶  0:07.54 / 0:48.90   Edited|Original │ │ 0:09   SHOPKEEPER           │ │
│ ────────●──────────────────────────────│ │        Sure, sir.           │ │
│ − + Fit   [ word timeline, zoomable ]  │ │          …  (script paper)  │ │
│                                        │ └─────────────────────────────┘ │
│                                        │ Direction: last reply / take    │
│                                        │ [ Ask for a change…  ] [Voice▾] │
└────────────────────────────────────────┴─────────────────────────────────┘
```

- **Left: the bay.** Monitor, transport (timecode, not a bare slider), the word timeline. Dark and quiet.
- **Right: the script.** A paper page. Each statement is set as a screenplay line — time in the left margin, speaker name above, words in Courier. Click a line to rewrite it; approved edits show the new line in revision blue on the blue tint, the old one struck through beneath, and a `*` in the right margin.
- **Direction dock** under the script: the conversation, collapsed to the latest exchange, with the take / question card in place; the composer and the chat voice. Earlier messages expand on demand.
- **Cast** heads the script: each speaker's name and voice.
- **Header**: project, spend, Export.

### Principles

- The boldness is spent once: **the script page**. Everything else is graphite, flat, quiet.
- Structure means something: the margin `*` is a revision; the tint is an approved change; colour on a name is a speaker. No decorative borders.
- One motion moment: an approved line turns revised (tint fades in). Nothing else animates.
- Floor, unannounced: keyboard reachable, visible focus, `prefers-reduced-motion`, readable at 1280 and on a narrow window (stacks: monitor, script, dock).

## Pass two — critique and revisions

- *Dark bay + one accent* is red flag 2 territory. It is kept because a monitor needs a dark surround, but the accent is **revision blue from the trade**, not an acid neon, and the big move is a **light** paper page — so the screen reads as "script on a desk in an edit bay", not "dark SaaS".
- *Courier* is a monospace — red flag 5 warns about monospace *data*. Here it is the content itself (a script), never used for numbers, labels or chrome. Timecodes use tabular Instrument Sans.
- *Screenplay names in capitals* — the skill discourages all-caps labels. Screenplays do set names in capitals, but here they are **small caps via `font-variant`**, shown only once per speaker change, which keeps the convention without shouting.
- Rejected from the first sketch: a cyan glow on everything (the current UI) — decoration without meaning; a card per chat message — the SaaS-card kit; an "AI" sparkle anywhere.
- The chat was the main surface; it becomes the **dock**, because in ADR the script is where you work and direction is what you say about a line. Selecting a line in the script sets the selection the dock talks about.

## Also fixed in the rebuild

- The transcript panel collapsed to nothing in a height-limited column (a flex item with `overflow` shrinking to 0).
- Reloading lost the open project: the project id goes in the URL (`#p3`), so a reload reopens it.
