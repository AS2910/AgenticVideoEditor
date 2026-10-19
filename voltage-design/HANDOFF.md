# Voltage · "Volt" redesign handoff

For Claude Code: this folder is a design reference, not runnable code. Each `screens/*.dc.html` is one screen's markup and CSS, written for a design-canvas runtime (`support.js`, `<x-dc>`, `{{holes}}`, `<sc-for>`, `<sc-if>`). Read them for structure, copy, tokens and motion, and rebuild them in the app's own React + Tailwind (`frontend/src`). Keep the existing behaviour and API. Only the look, the layout and the motion change.

## What changes from UX-9

- **Two panes, not three.** Left: picture, scrubber and transcript, centred at a max width of about 820 px. Right: the Voltage pane, about 390 px, black in both themes. The tracks (`Lanes`) are hidden behind a "Tracks" toggle under the scrubber. The dock goes away: Projects, Voices, Usage and Settings move into a top nav on non-editor pages.
- **Depth on demand.** A proposal row shows its words, one line of facts and four actions. "Edit it" opens the row in place to show Before/After, takes, delivery pills, the direction, the facts grid (Voice · Model · Dials · Fit) and the measured meters (voice match, naturalness, prosody, seam).
- **Voltage's presence.** An animated waveform avatar: idle is slow volt bars, working is fast, and needs-you is amber. Steps render as a mono "trace": `time ├ sentence tool_name  cost`.
- **Saved voices (new).** A Voices page with three sections. Yours: kept across projects, either recorded, designed or added from the library. Made inside a project: deleted with the project, with a "Keep in my voices" button. Catalogue. Plus a New voice panel with three ways in (record or upload, describe it, from a project speaker) and the consent checkbox.

## Tokens (light / dark)

| Token | Light | Dark |
|---|---|---|
| bg | #F3F3EF | #0E0E10 |
| surface | #FFFFFF | #17171B |
| sunk | #EAEAE4 | #202025 |
| line / line2 | #E0E0D9 / #C9C9C1 | #2A2A30 / #3C3C44 |
| text (ink) | #0B0B0C | #F2F2EE |
| muted / faint | #55555C / #66666D | #A6A6AE / #8F8F98 |
| volt (accent) | #D7FF3A | same |
| warn (needs you) | #FFB020 | same |
| pane bg / text / muted / line / sunk | #0B0B0C / #F2F2EE / #A6A6AE / #26262C / #17171A | #050506 / same / same / #1F1F24 / #111114 |

Rules:

- Volt is used only as a fill with ink (#0B0B0C) text on it, or as text on the black pane. Never use volt as text on white.
- Borders are 1.5 px ink. Hard offset shadows (`4px 4px 0 ink`) appear only on proposal cards, gate cards and primary buttons. No glows, blurs or gradients.
- Proposed words use `<ins>` with a volt highlighter. Removed words use `<del>`.

## Type

- **Space Grotesk 600–700** for display: headings, the wordmark "VOLTAGE", buttons and big numbers.
- **Geist 400–500** for UI and body text (transcript lines are 16 px, proposal text 18 px).
- **JetBrains Mono** for every timecode, cost and count, and for uppercase tags (12 px, 0.06em tracking). The 12 px floor holds.

## Components (by class in the mocks)

- `btn` is an outline button. `btn volt` is the primary, with an ink border and a hover lift. `btn ink` is black with volt text (Export, Play). `act` is a quiet text action.
- `seg` is a segmented control, mono uppercase, with the active segment ink-filled and volt text. Used for the playback switch (Final · With proposals · Original), takes and effort.
- `stamp` is a mono uppercase badge. Volt = Proposed, amber = waiting on you, outline = in the video.
- `row` / `row prop` is the transcript row. `prop` = ink border + offset shadow.
- `trace` is the step list in the pane. `gate` is the question card with a volt border and a pulsing offset shadow.
- `wave` (`.busy`, `.need`) is the avatar.

## Motion (all off under `prefers-reduced-motion`)

| What | Animation |
|---|---|
| Trace steps | rise in, staggered 150 ms |
| Proposal cards | pop in (scale .97 → 1) |
| `<ins>` highlighter | sweeps left to right (`background-size` 0 → 100%, 0.7 s) |
| Meters (spend, measured, usage) | fill from 0 |
| Primary CTAs (`.shine`) | a light sweep every ~3.6 s |
| Volt buttons | lift on hover (`translate(-2px,-2px)`, bigger shadow), press on click |
| Gate card | shadow pulses 4 px ↔ 8 px |
| Player while Voltage reads or looks | a 2 px scan line sweeps across |
| Tracks lanes | blocks grow in from the left |
| Designed-voice previews | bars bounce |
| Export | "It's out." stamps in |
| Voices | cards lift on hover, bars animate; the record button pulses |

## Screens → where they land

| Mock | App |
|---|---|
| Login | `SignIn.tsx` |
| Projects | start screen and project list |
| FirstRead | goal stage (reading + speaker roles + example goals) |
| Main | editor: `LineDoc`, player, `ChatPanel` |
| EditorWorking | a turn waiting at a gate (question card, live trace, scan line) |
| EditorDepth | `Lanes` open, a proposal expanded, the designed-voice previews card |
| Export | ship sheet as its own page: download, copy link, make a variant, receipt tiles |
| Voices | `VoicesSheet` becomes a page. Needs a new endpoint to promote a project voice (designed or cloned) into the user's voices so it is not deleted with the project. |
| Usage | ledger by vendor and by project, against the per-user ceiling |
| Settings | "What Voltage may do": autonomy, turn cap, effort, which commits still ask under Just do it; appearance; account |
| Billing | placeholders only; no billing system exists yet |

Figures in the mocks are illustrative, taken from the build logs. Bracketed placeholders like [PLAN NAME] are not real values.
