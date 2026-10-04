# Design System Master File — Voltage

> **LOGIC:** When building a specific page, first check `design-system/voltage/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** Voltage (AgenticVideoEditor) · **Written:** 2026-10-04, by hand from `frontend/src/styles/theme.css` and the UX plan of 2026-10-03. Not generated: the ui-ux-pro-max `--design-system` result for this product (Swiss minimalism, Inter, recording red) was checked and set aside — Voltage's room is already built and shipped.

## The room

A warm dark room: one dark surface, amber for anything the agent changed or wants you to look at, rose for "needs you", teal for "ok". Fraunces for the one heading per screen and the brand word, Instrument Sans for everything else. No light mode. The picture never stops; the line is the unit; the user's next action is the panel's last element.

## Color tokens (use the variables, never raw hex in components)

| Role | Token | Hex |
|---|---|---|
| Background | `--bg` | `#171412` |
| Surface (panels) | `--surface` | `#1F1B18` |
| Raised (cards, rows on hover) | `--raised` | `#2A2522` |
| Line / border | `--line` | `#3A332E` |
| Text | `--text` | `#F3EDE4` |
| Muted text | `--muted` | `#A89F94` |
| Faint text (never for body copy) | `--faint` | `#7A7168` |
| Accent: changed words, ready, links, focus | `--accent` | `#E9A860` |
| Accent fill (primary button) | `--accent-fill` | `#C9823D` |
| Ink on an amber button | `--accent-ink` | `#1A1511` |
| Accent tint / line | `--accent-tint`, `--accent-line` | 14% / 40% amber |
| Needs you (rose) | `--amber`, `--amber-tint`, `--amber-line` | `#E5897B` |
| OK | `--ok`, `--ok-tint` | `#5FBFAD` |
| Speakers A–D | `--speaker-a..d` | teal, mauve, amber, blue |
| Shadow | `--shadow` | inset hairline + `0 12px 32px rgba(0,0,0,.28)` |
| Radii | `--radius`, `--radius-lg` | 10px, 16px |

Contrast: `--text` on `--bg` ≈ 14:1; `--muted` on `--surface` ≈ 6.5:1; `--faint` on `--surface` ≈ 3.6:1 — faint is for labels beside text, never alone. `--accent` on `--bg` ≈ 8:1; `--accent-ink` on `--accent-fill` ≈ 7:1.

## Typography

- Headings and the brand word: `--serif` = Fraunces (one `h1` per screen, 28–36px, weight 500–600; `h2` for panel and card titles, styled small if need be but a real heading).
- UI and body: `--ui` = Instrument Sans. Scale: **12** label floor (always `nowrap`), **13** small label, **14** compact body (log entries, hints, row meta), **16** body and inputs (the `body` base), 20, 28, 36. A full sentence is never under 14px. Nothing under 12px, including avatar initials and `kbd`.
- Line-height 1.5 for body, 1.2 for headings. Tabular numerals for times and money.
- Verdicts and states are sentences first, numbers behind them.

*Decided 2026-10-04 (UX-6 audit): the base was 14px and most controls had drifted to 12–13; the revamp moves the base to 16.*

## Spacing and layout

8px grid: 4 / 8 / 12 / 16 / 24 / 32. Panel padding 16–24px. **Targets:** every button, link, chip and input is at least 44×44 CSS px to the pointer (the visual can be smaller inside a padded hit area); chips and pills at least 36px tall; at least 8px between adjacent targets; segmented controls 36px with a 2px gap. Rows 44px tall minimum. The player left, the panel right at desktop; stacked at phone width with a 16px gutter and no horizontal scroll. Breakpoints: 420 (phone), 768, 1024, 1440.

## Motion

150–250ms for state changes, 300ms for a row opening; `prefers-reduced-motion` turns every transition to 0ms and stops the orb's breathing. At most one or two moving things per view. Exits faster than entrances.

## Interaction rules

- Every control is reachable from the keyboard with a visible amber focus ring (`--accent`, 2px, `outline` or `box-shadow`; never `outline: none` without it); rows have grips, but dragging is never the only way (Move up / Move down, typed times, nudge buttons), and a grip that promises a drag also opens the place control on Enter.
- Every state change the user waits for is spoken: one `role="status"` region per panel for progress and the agent's narration, `role="log"` on the chat, `role="alert"` for failures, `role="progressbar"` with values on bars, `aria-busy` on the region doing the work. Disabled controls read as inert (`opacity: .5`), never as a secondary button.
- Sheets are real modals (`<dialog>`, focus in, Tab trapped, Escape closes, focus returns). Every screen has an `h1`, a `<main>` and a skip link.
- Icons are inline SVG, 16/20px, 1.5px stroke, never emoji; a meaningful icon has a text alternative; an icon beside visible text is `aria-hidden`.
- Loading: the orb "working" state plus a sentence about what is happening; reserve the space of what is coming (skeleton rows, frame slots) so nothing jumps; `aria-busy` on the region.
- Errors appear where they belong — in the row, or as the agent's reply in the thread — in one sentence with one action; the red strip under the player is only for the engine.
- Compact labels (chips, counts) do not wrap: `white-space: nowrap`, `min-width: 0`, with the full text reachable. Nothing lives only in a `title` tooltip.
- `--faint` is for glyphs and dividers and for a label *beside* larger text; never for a sentence, a time, a cost or a struck word (those are `--muted`).
- Chat: the user's bubble right, Voltage's left; the thread scrolls, the composer stays; the user's next action is always the last element.

## Components in use

`LineDoc` rows (states: Planned, Voicing…, Ready to hear, Needs you, Kept, Removed, Moved, Couldn't voice it), the line editor (words, Delivery chips, Voice, Sound meets picture, If it runs long, cost, Hear it), `QuestionCard` (a sentence in quotes + option chips + the agent's guess first), `PlanCard`, `Player` with the monitor bar and the Move block, `GoalStage`, `ProjectList` cards (frame, state word, last change), `ConsentSheet`, `SpendMeter`.
