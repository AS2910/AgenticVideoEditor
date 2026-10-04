# UX-2 · The panel does one job

**Date:** 2026-10-04 · **Status:** built, from the "The line is the unit" mocks (L1, L7, L8) and section 4–5 of the UX plan of 2026-10-03.

## What changed

**The goal stage shows the clip.** Before asking what the video should say, Voltage takes the clip in once (`POST /projects/{id}/reading`, one low-effort Claude call, saved with the project): a specific opening line ("Two speakers, twenty short lines… The product name is said only once, at 0:07; the shopkeeper never answers the expiry-date question asked at 0:28") and a **role for each speaker** — *the Customer*, *the Shopkeeper* — shown as "my guess" next to the compact transcript (time · who · words), with **Looks right** to confirm every guess in one click, or **Rename** per speaker. A confirmed role becomes the speaker's name everywhere (the cast row, the planner's prompt, the plan). Until the reading arrives the stage says "Taking it in…"; if it fails, the plain count stands.

**Plan items have the line editor's controls.** Each planned change carries **Delivery** (as spoken, warmer, more excited, calmer, slower, firmer, or in your words) and, for an added line, **Sound meets picture** (over the picture / hold the picture) — the same two controls the line editor has, wired to the item route. A change to either sends a voiced item back to planned.

**The plan is revised in words, in place.** The box under Voltage is for the whole video: a goal when there is no plan, a change to the plan when there is one. `POST /plans/{id}/revise {instruction}` asks Claude for a *diff* of the plan — untick, put back, reword, re-place, re-deliver, add — applied to the plan's items in place, so **the takes already voiced survive**: "not the first one" leaves an item out but keeps its take; "warmer at 0:17" sends only that item back to planned. The plan goes back to *proposed* with "1 voiced" in its count, voiced items show their take with "Already voiced; it keeps this take unless…", and the button says **Voice the change** (only what is planned is voiced, and only that is in the estimate). An instruction that is really a new goal makes a new plan, as before. Offline, the rule planner understands "not the second one", "skip the one at 0:17", "put the last one back" and quoted changes.

**Stop.** A running plan has **Stop** in the plan's head: the line being voiced finishes, the rest stay planned ("Stopped with 2 lines still planned"), and the plan waits as *proposed* for Go ahead later. While it stops, the card says "Stopping after this line…" and the box says so too.

## Where

- Backend: `Planner.read` / `Planner.revise` (`app/orchestrator/planner.py`: `Reading`, `Role`, `ItemView`, `ItemChange`, `Revision`; rule fallbacks), `READ_SYSTEM` / `REVISE_SYSTEM` and their schemas in `app/adapters/claude_planner.py`; routes `POST /projects/{id}/reading`, `POST …/plans/{id}/revise`, `POST …/plans/{id}/stop` in `app/api/main.py` (`_apply_revision`, `_status_after_edit`, `_stops`); `Plan.runnable` now means "ticked and not yet voiced", so Go ahead after a revision voices only what changed; `PUT …/items/{id}` on a finished plan puts it back to proposed; the project carries `reading`.
- Front end: `GoalStage` (columns: the script with its cast, the goal), `PlanCard` (`ItemControls`, Stop, the voiced-item take in the proposed view), `App` (`reading`, `revise`, `stop`, the composer's two jobs), `api.readProject` / `revisePlan` / `stopPlan`.

## Exit

482 backend + 183 frontend tests; lint, typecheck and build clean. Stories A1, A2, B1, B7, B8 and D1 pass. Live on the Bhaji Cam clip: Claude named the Customer and the Shopkeeper correctly with a reason each; "Say it warmer, and let the picture keep moving under it instead of holding" on the finished plan set the closing line to *warmer* and *over the picture*, sent only that item back to planned (estimate 80 characters), and left the shipped lines alone. Stop is covered by a test with a gated voice; not exercised live (it would have cost a take to interrupt).

## Left for later

Per-line review with Keep / Hold, the ship sheet, variants, consent at first voicing and the spend meter (UX-3); keyboard (UX-4). The reading's opening can run to two long sentences on a busy clip; a tighter prompt is a one-line change if it grates.
