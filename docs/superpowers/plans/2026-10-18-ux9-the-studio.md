# UX-9 — The studio (2026-10-18)

The user's words, with two mocks (dark, then light): *"This is how I am thinking of the new design"* → *"DO 2 → this is the light mode."* Option 2 was the full room: the three-pane studio layout **and** a new skin — obsidian and cyan in the dark, slate and cyan in the light, Geist and JetBrains Mono — with the design-system master rewritten and its tests updated.

## What the mocks say, and what we keep

**Kept as drawn.** Three panes (player and lanes · transcript and takes · Voltage) with a slim dock on the left. A **multitrack** under the player: V1 the picture (copies, flexed and held spans), A1 the spoken lines by speaker (removed ones struck), A2 the added and proposed lines, A3 room tone where a removal left it. A transcript header with the line count, **Add all (N)**, a speaker filter (All · each speaker with a count) and the state counts (N Proposed · N Added · N Removed). The **hero proposal card**: Before/After as a diff, delivery chips, the direction line, a facts grid (voice engine, dials, fit, picture retime), the measured line (SIM-o, UTMOS, prosody against their thresholds) and Add it (K) · Hear in place · Voice it · Discard (Del). The Voltage pane: user bubble, Thinking line, the steps as a list, the reply, the gate card with Add it now / Hear it / Adjust direction, the composer under "Instruction · Turn cap $0.50". Timecodes, money and counts in mono.

**Changed before it ships (said before the user chose 2).**
- Type floor stays: labels 12 px, compact UI 14 px, sentences 14–15 px. The mocks' 8–10 px becomes 12 px with the same hierarchy (mono, uppercase tracking where the mock had it).
- No invented numbers: FPS, ProRes, 4K DCI, LUFS, latency, "Neural Engine Online", a licence line — gone. Every figure on screen comes from the record, the same rule the agent is held to. The footer goes with them.
- No glows, frosted panels or gradients (the theme test keeps forbidding them). The cyan accent does the work: `primary` is cyan in both modes; a proposal's border is `primary`; a `shadow-sm` is the most a card gets.
- Autonomy lives in the header only. The dock holds real destinations only: Projects, Workspace, Speakers, What Voltage may do.
- Light mode is a first-class theme (the second mock), dark its sibling; the System choice stays.

## The room (tokens)

| Role | Light | Dark |
|---|---|---|
| background | slate 100 (#f1f5f9) | obsidian (#051424) |
| card / popover | white | #0b0f17 |
| foreground | slate 900 | #d4e4fa |
| muted-foreground | slate 500 | #849396 |
| border / input | slate 300 / 200 | #233143 / #162332 |
| primary (cyan) · on primary | #0891b2 · white | #00e5ff · #002027 |
| secondary / muted / accent | slate 100–200 | #0f1420–#151b2a |
| changed (proposed) | cyan 700 on cyan 50 | cyan 300 on cyan 950 |
| ok (added) | emerald 700 on emerald 50 | emerald 300 on emerald 950 |
| needs (flagged, removed) | rose 600 on rose 50 | rose 300 on rose 950 |
| destructive | rose 600 | rose 400 |
| speakers a–d | blue, violet, amber, pink at 55–58% | the same at 78–82% |

All as OKLCH variables in `globals.css`, exposed with `@theme inline`; components never spell a colour. Fonts: `@fontsource-variable/geist` (sans), `@fontsource-variable/jetbrains-mono` (mono, `.tnum` and timecodes), Inter dropped.

## Build order (each a commit on `ux9-the-studio`, merged to main at the end)

1. **Tokens and type** — palette, fonts, `MASTER.md` rewritten, theme tests kept green (they test rules, not colours).
2. **Lanes** (`components/Lanes.tsx`, built in parallel) — ruler and playhead, V1/A1/A2/A3, overlapping added lines packed into sub-rows so coexisting audio is visible; click a pill to seek; the placing block for a take being moved; the Precise word timeline stays a toggle under it.
3. **Layout** — header (brand · file · duration | Original · With proposals · Final | Check with me · Just do it | spend pill · Variant · Export again · Export/Download · settings · theme · user), dock, three panes; stacked under 960 px.
4. **Transcript pane** — header with counts, speaker filter and Add all; rows as cards; the hero proposal card with inline delivery chips (a chip is a turn: "Voice i1 again, said warmer"), the facts grid and the measured line from the candidate; added, removed, voicing and voice-over cards as drawn.
5. **Voltage pane** — header (Voltage · the autonomy word), the thread as drawn, the question as a gate card, the composer with the turn cap.
6. **Docs** — as-built here, `docs/requirements.md`, memory.

## Out of scope here

Resizable panes; a waveform on pills; stems as separate playable lanes (A3 shows room-tone patches only, because that is what we render); a dictation button (no recording path, story E3).
