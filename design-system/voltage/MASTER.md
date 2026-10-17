# Design System Master File — Voltage

> **LOGIC:** When building a specific page, first check `design-system/voltage/pages/[page-name].md`.
> If that file exists, its rules **override** this Master file. If not, follow the rules below.

**Project:** Voltage (AgenticVideoEditor) · **Rewritten:** 2026-10-14 (UX-8), replacing the "Ink and teal" room of UX-7. Source of truth in code: `frontend/src/styles/globals.css`, `frontend/components.json`, `frontend/src/components/ui/`.

## The room

Stock **shadcn/ui** (new-york style, **zinc** base) on Tailwind v4, **light and dark**. Flat surfaces, 1px borders, `shadow-xs`/`shadow-sm` at most, an 8px base radius. No gradients, glows, frosted bars, serif type or breathing orb. Voltage's presence beside its words is a small bolt icon (`Presence`), a spinner while it works. The picture never stops; the line is the unit; the user's next action is the panel's last element.

Theme: follows the system, with a Light / Dark / System menu in the header (`ThemeToggle`, `lib/theme.ts`). The choice is saved in `localStorage` (`voltage-theme`, always in try/catch); an inline script in `index.html` sets `.dark` before first paint.

## Tokens (use the Tailwind utilities they generate, never a raw colour)

All colours are OKLCH variables in `globals.css`, defined for `:root` and `.dark`, exposed to Tailwind with `@theme inline`. `theme.test.ts` fails on a raw colour, a gradient, a blur, a missing token or a missing dark value.

| Role | Utilities |
|---|---|
| Page, text | `bg-background` `text-foreground` |
| Cards, panels, popovers | `bg-card` `bg-popover` (+ `-foreground`) |
| Primary action (near-black in light, near-white in dark) | `bg-primary` `text-primary-foreground` |
| Quiet fills, hover, selected | `bg-secondary` `bg-muted` `bg-accent` |
| Secondary text | `text-muted-foreground` (≥ 4.5:1 on background and card in both modes) |
| Borders, inputs, focus | `border-border` `border-input` `ring-ring` |
| Errors | `text-destructive` |
| **Changed**: words Voltage wrote, a take that is ready, links to it | `text-changed` `bg-changed-soft` |
| **Kept / ok** | `text-ok` `bg-ok-soft` |
| **Needs you** | `text-needs` `bg-needs-soft` |
| Speakers A–D | `text-spk-a..d` (and `bg-spk-a..d`, usually at low opacity) |
| The picture's surround | `bg-monitor` |
| Radii | `rounded-sm/md/lg/xl` = 4 / 6 / 8 / 12px off `--radius: 0.5rem`; nothing larger than `rounded-xl` |

Colour never carries meaning alone: every state has a word (Kept, Ready to hear, Needs you) beside its colour.

## Typography

**Inter** (variable, self-hosted through `@fontsource-variable/inter`; no external font request). One family. Headings are `font-semibold tracking-tight` and one `h1` per screen. Scale: `text-xs` 12 is the floor (labels, `kbd`, never a sentence), `text-sm` 14 for compact UI, `text-base` 16 for body and inputs. Line-height 1.5. Times and money use `.tnum`. Verdicts and states are sentences first, numbers behind them.

**Voltage's panel has two sizes, not four** (2026-10-17). What Voltage and the user say is `text-chat` (a token in `globals.css`: 15px / 1.6, a step under body so a 550px panel holds a sentence on two lines, not three); everything around the words — labels such as "I noticed" and "Or try", chips, notes, "· my guess", text links, the hint under the composer — is `text-sm` 14, muted where it is secondary. `text-xs` stays for `kbd`, counts and the plan's meta line only. A filename in a sentence is `font-medium break-all`, not bold.

**Voltage's words are markdown, drawn not pasted.** `components/Markdown.tsx` (parser in `lib/markdown.tsx`) renders what the model writes — paragraphs, `- ` and `1. ` lists, **bold**, *italic*, `code`, http(s) links, a heading as a bold line (a chat has no headings) — as React nodes, never HTML, so nothing a model writes reaches the page as markup. A plain sentence stays one text node (tests find it whole). Used for every assistant message in `ChatPanel`, the reading's opening line, a question's text and a plan's summary; the user's own bubble is plain text.

## Spacing, layout, targets

4px grid via Tailwind. Player left, Voltage panel right at desktop; stacked below 960px with a 16px gutter and no horizontal scroll; Voltage tucks away into a 64px rail (a strip with its own composer on a phone). Full-height screens use `dvh`, never `vh`.

**Targets:** the shadcn controls are 36px with a mouse and grow to **44px on coarse pointers** (`pointer-coarse:`); any custom clickable element adds `pointer-coarse:min-h-11`. At least 8px between adjacent targets.

## Motion

`tw-animate-css` enter/exit (150–250ms); `prefers-reduced-motion` zeroes every transition and animation (`globals.css`). At most one or two moving things per view; exits faster than entrances.

## Interaction rules (unchanged by UX-8)

- Everything is reachable from the keyboard with a visible focus ring (`focus-visible:ring-[3px] focus-visible:ring-ring/50`); `outline-none` only beside a ring. Dragging is never the only way (Move up / Move down, typed times, nudge keys).
- Every wait is spoken: one `role="status"` region per panel, `role="log"` on the chat, `role="alert"` for failures, `role="progressbar"` with values, `aria-busy` on the region doing the work. Disabled controls read as inert, never as a secondary button.
- Sheets are real modals (shadcn `Dialog`/Radix: focus in, Tab trapped, Escape closes, focus returns). Every screen has an `h1`, a `<main>` and a skip link.
- Icons are `lucide-react` SVG, never emoji; a meaningful icon has a text alternative; beside visible text it is `aria-hidden`.
- Loading reserves the space of what is coming (`Skeleton`, frame slots) and says in a sentence what is happening.
- Errors appear where they belong, in one sentence with one action.
- Compact labels do not wrap (`whitespace-nowrap`, `min-w-0`); nothing lives only in a tooltip.
- Chat: the user's bubble right, Voltage's left; the thread scrolls, the composer stays; the user's next action is always the last element. Once lines are voiced that action is the **ship card** (`ShipCard`: what is ready, Play the seams, Ship N) — never a button in the header; saying "ship it" in the composer does the same. One action lives in one place: the header keeps only Review.
- Voices Voltage makes (20b): a voice designed from words arrives in the thread as a **previews card** (`VoicePreviews` in `ChatPanel`, a `role="group"` named by its sentence): one row per preview — "Preview n" `text-sm font-medium`, a native `<audio controls preload="none">` (click to play, never autoplay, `aria-label` "Play preview n") and the length in `.tnum text-xs` — then Voltage's own sentence under it. Voltage cannot hear the previews, and says so; the user listens and says which. A kept voice shows up in the catalogue (the plan card's Voice row) on the next turn without a reload.
- Every composer path is a turn (20c): a goal, an answer, a change, "ship it", the Voice row's Change and Another take all go to Voltage in words; the send button is **Send** (Answer under a question, Preview the change with a selection). Nothing in the panel fills a form on the user's behalf.
- Voices: the picker groups voices by accent (`byAccent`, `<optgroup>`) once there is more than one; a plan that asked for a kind of voice shows a **Voice** row on the plan card (name · "female, indian" · the planner's one-sentence note · Change). A voice that could not be matched is said plainly in words ("No Indian voice is on the list yet, so I kept the default voice."), never silently defaulted.

## Components in use

shadcn: `Button` `Input` `Textarea` `Badge` `Card` `Dialog` `Popover` `DropdownMenu` `Progress` `Skeleton` `Switch` `Select` `Tooltip` `Separator` `Label` `ScrollArea` `Toggle` `ToggleGroup` (in `components/ui/`; generated by the shadcn CLI, then fixed where the CLI is wrong: the `cn` import path, `Progress` forwarding `value` so `aria-valuenow` is set, the coarse-pointer sizes).

Voltage's own, built on them: `LineDoc` (the transcript row and its in-place editor; `EditorControls`, `editorStyles`), `PlanCard`, `ReadingCard`, `QuestionCard`, `CandidateCard`, `PlaceEditor`, `ReviewPanel`, `Player` (monitor, caption, timeline), `Timeline`, `ChatPanel`, `ActivityLog`, `SpeakersBar`, `VoicePicker`, `AutonomySwitch`, `SpendMeter` (popover), `ExportBar`, `ConsentSheet`, `ShipSheet`, `LoadScreen`, `ProjectList`, `SignIn`, `Avatar`, `Presence`, `ThemeToggle`.

Native `<select>` is kept for Voice and "If it runs long", and segmented controls are `aria-pressed` buttons, so roles stay what the tests and assistive tech already expect; they are styled to match.

## Adding a component

`cd frontend && npx shadcn@latest add <name>`, then check the generated file's `cn` import (it should be `@/lib/utils`) and add `pointer-coarse:` sizes if it is a control. Never spell a colour; add a token to `globals.css` (both `:root` and `.dark`, plus `@theme inline`) if a new meaning is needed.
