# UX-4 · Keyboard and polish

**Date:** 2026-10-04 · **Status:** built, from section 10 of the UX plan of 2026-10-03 (H3) and its "every screen at 1470 px and 420 px" exit.

## What changed

**The transcript works from the keys.** Every line is a focusable row. With a row focused: **↑ ↓** move between lines (J too), **Enter** opens the editor on that line (Esc closes it and puts focus back on the row), **Space** plays the line, **A** adds a line after it, **K** keeps the latest take waiting on it, **U** undoes a kept change, **Delete** removes the line. **/** puts the cursor in Voltage's box from anywhere that is not already a text field. The transcript's heading shows the keys while a row has focus; typing inside a row's editor never triggers them.

**Narrow.** At phone width a row's actions no longer sit on every line: tapping a row focuses it and they appear. The plan card's control labels take their own line; the spend meter keeps its figure and drops its bar. The header wraps.

**Motion.** Rows ease between states; takes, questions, errors and the editor rise in; the plan card and the sheets rise in. Reduced-motion users get none of it (already honoured in the theme).

**Empty states.** A plan that changes nothing says so in the card ("Nothing to change for that. {the planner's reason}. Try saying what should be different, or click a line to change it yourself.") instead of an empty list with a dead button. A clip with no speech, a review with nothing to ship and an empty project list were already covered.

## Where

`LineDoc` (`onRowKey`, `focusedRow`, `returnTo`), `App` (the `/` listener), `PlanCard` (`plan-empty`), the narrow rules in `LineDoc.module.css`, `PlanCard.module.css`, `SpendMeter.module.css`.

## Exit

485 backend + 190 frontend tests; lint, typecheck and build clean. Story H3 passes: a line can be found, changed, heard, kept and undone without the mouse. Checked at 1470 px and 420 px on the Bhaji Cam variant (p9).

## Left for later

Space while the editor is open could toggle the take; Keep / Hold in Review from the keys; a visible focus order for the plan card's pills.
