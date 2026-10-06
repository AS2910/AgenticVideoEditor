# Design System Master File — Voltage

> **LOGIC:** When building a specific page, first check `design-system/voltage/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** Voltage (AgenticVideoEditor) · **Written:** 2026-10-04, by hand from `frontend/src/styles/theme.css` and the UX plan of 2026-10-03. Not generated: the ui-ux-pro-max `--design-system` result for this product (Swiss minimalism, Inter, recording red) was checked and set aside — Voltage's room is already built and shipped.

## The room

Ink and teal (UX-7a): a deep blue-black ground, teal for anything Voltage touched or wants heard, coral for "needs you", soft green for kept, blue and mauve for the speakers. *Until 2026-10-06 the room was warm-dark with an amber accent.* Fraunces for the one heading per screen and the brand word, Instrument Sans for everything else. No light mode. The picture never stops; the line is the unit; the user's next action is the panel's last element.

## Color tokens (use the variables, never raw hex in components)

*UX-7a (2026-10-06): the Ink and teal room, from the UX-7 mocks. Amber is retired; the older names (`--amber`, `--speaker-a..d`, `--accent-bright`, `--shadow`) are aliases of the tokens below so older components keep working.*

| Role | Token | Hex |
|---|---|---|
| Background / deep (inputs, tracks) | `--bg` / `--bg-deep` | `#0E141C` / `#0A0F15` |
| Surface / low (the foot of a gradient) | `--surface` / `--surface-low` | `#151E28` / `#121A23` |
| Raised / raised under the pointer | `--raised` / `--raised-2` | `#1D2834` / `#243140` |
| Line / soft (dividers inside a surface) / strong (under the pointer) | `--line` / `--line-soft` / `--line-strong` | `#283645` / `#1F2B38` / `#34465A` |
| Text / muted / faint | `--text` / `--muted` / `--faint` | `#EDF2F6` / `#9BABBC` / `#6E7D8E` |
| Accent: changed words, ready, links, focus, the orb | `--accent` | `#3FC8B4` |
| Accent highlight (an inserted word, the orb's lit side) / low | `--accent-hi` / `--accent-lo` | `#B4F2E6` / `#0C6C62` |
| Accent fill (a primary button) / its lit top / ink on it | `--accent-fill` / `--accent-fill-hi` / `--accent-ink` | `#17A997` / `#34C9B5` / `#04110F` |
| Accent tint / line / soft line | `--accent-tint` / `--accent-line` / `--accent-line-soft` | teal 13% / 42% / 25% |
| Needs you | `--rose`, `--rose-tint`, `--rose-line` | `#F08A6E` |
| Kept / ok | `--ok`, `--ok-tint` | `#86C98F` |
| Speakers A / B (C / D) | `--spk-a` / `--spk-b` (`--speaker-c` / `--speaker-d`) | `#7FB8F0` / `#C9A2E8` (`#E9C46A` / `#F2A6A6`) |
| Scrim | `--scrim` | ink 66% |
| Radii | `--radius`, `--radius-lg`, `--radius-xl` | 10px, 16px, 20px |

Contrast: `--text` on `--bg` ≈ 15:1; `--muted` on `--surface` ≈ 6.7:1; `--faint` on `--surface` ≈ 3.6:1 — faint is for glyphs, dividers and a label beside larger text, never alone. `--accent` on `--bg` ≈ 9:1; `--accent-ink` on `--accent-fill` ≈ 7.5:1.

### Depth (UX-7a)

Depth is allowed and specified, and every piece of it is a token, so a component never spells a shadow or a gradient of its own:

| Thing | Tokens |
|---|---|
| Hairline top highlight on anything raised | `--hl` |
| Shadow steps: a button, a card, a sheet | `--sh-1` / `--sh-2` / `--sh-3` |
| A card or panel: `--shadow` (`--hl` + `--sh-2`); a small card inside a panel: `--card-shadow`, `--card-bg` | `--card-bg` is raised → surface |
| A question card | `--card-q-bg`, `--card-q-shadow` (teal-tinted) |
| A panel's or hero card's ground | `--surface-bg` (surface → surface-low), `--panel-shadow` |
| A sheet | `--sheet-bg`, `--sheet-shadow` (22px radius) |
| An input or a track: recessed | `--recess` (`--recess-deep` for the timeline); focus adds `--ring` and `--accent-line` |
| A raised button | `--btn-bg`, `--btn-bg-hover`, `--btn-shadow`; it presses 1px (`button:active`, global) |
| A primary button | `--btn-primary-bg` (lit from above), `--btn-primary-shadow`, `--btn-primary-shadow-hover` (a glow) |
| A segmented control | the track is `--bg-deep` + `--recess`; the chosen segment `--seg-on-bg` + `--btn-shadow` |
| A fill (progress, spend, played) | `--fill-bg` (accent-lo → accent), `--fill-shadow` |
| The bar | `--bar-bg` (frosted: `backdrop-filter: blur(14px)`), `--bar-shadow` |
| The orb | `--orb-highlight`, `--glow-soft`, `--glow-strong`, `--glow-color`; it breathes on a 4.5 s cycle (`swell`), faster while working |
| A speaker dot | `--dot-shadow` |
| Inserted words | `--accent-hi` on `--accent-tint` with an inset `--accent-line-soft` ring; struck words keep `--muted` with a `--rose` strike |

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

`LineDoc` rows (states: Planned, Voicing…, Ready to hear, Needs you, Kept, Removed, Moved, Couldn't voice it), the line editor (words, Delivery chips, Voice, Sound meets picture, If it runs long, cost, Hear it), `QuestionCard` (a sentence in quotes + option chips + the agent's guess first), `PlanCard`, `Player` as the monitor (UX-7b: the 16:9 stage with the caption at the playhead, the timeline of speaker blocks, changed spans, word ticks, playhead and ruler, the Move block), `ReadingCard` (UX-7c: Voltage's first message — what it read or saw, the cast with role guesses to confirm or rename, the place to confirm, example chips that seed the composer; the goal stage is gone), the panel header with its state word and Hide (`\`), the 64 px rail when Voltage is tucked away (orb, count badge — coral for a question — the state word written vertically), `ProjectList` cards (frame, state word, last change), `ConsentSheet`, `SpendMeter`.

## UX-7 (2026-10-05): the room changes — applied in UX-7a, 2026-10-06

Signed off from the mocks in `docs/superpowers/mocks/2026-10-05-voltage-ux7/` (plan: `docs/superpowers/plans/2026-10-05-ux7-the-workspace.md`). These are the tokens the table above now carries (`frontend/src/styles/theme.css`); `voltage.css` in the mocks folder was the source.

| Role | Token | Hex |
|---|---|---|
| Background / deep (inputs, tracks) | `--bg` / `--bg-deep` | `#0E141C` / `#0A0F15` |
| Surface / raised / raised-2 | `--surface` / `--raised` / `--raised-2` | `#151E28` / `#1D2834` / `#243140` |
| Line / soft line | `--line` / `--line-soft` | `#283645` / `#1F2B38` |
| Text / muted / faint | `--text` / `--muted` / `--faint` | `#EDF2F6` / `#9BABBC` / `#6E7D8E` |
| Accent: changed words, ready, focus, the orb | `--accent` / `--accent-fill` / `--accent-ink` | `#3FC8B4` / `#17A997` / `#04110F` |
| Accent highlight / low / glow | `--accent-hi` / `--accent-lo` / `--glow` | `#B4F2E6` / `#0C6C62` / teal 42% |
| Needs you | `--rose` | `#F08A6E` |
| Kept / ok | `--ok` | `#86C98F` |
| Speakers A / B | `--spk-a` / `--spk-b` | `#7FB8F0` / `#C9A2E8` |

Amber is retired. Depth is allowed and specified: a hairline top highlight (`--hl`) on raised surfaces, three shadow steps (`--sh-1..3`), recessed inputs, raised buttons that press 1px, a frosted bar, the orb breathing on a 4.5 s cycle (off under `prefers-reduced-motion`). Fonts, sizes, targets, motion timings and interaction rules above stand. Alternatives B (light, indigo) and C (slate, coral) are on the mocks' Palettes board and are one token block to switch.
