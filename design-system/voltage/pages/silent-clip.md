# Page override — the silent clip (UX-5)

Applies to the goal stage, the panel and the transcript when a project has no transcribed speech. Everything in MASTER.md holds; these rules add to it.

- **Frame strip** replaces the transcript column: 3–8 frames, each a `button` with `aria-label="Frame at 0:02"`, 16:9 slots reserved before the images arrive (no layout shift), `loading="lazy"`, 512px JPEG/WebP served by the backend; the frame under pointer or focus enlarges 1.08× in 200ms (0 under reduced motion); a click sets the voice-over range there.
- **The orb line** is one true sentence about the picture ("No one speaks. A wide, empty beach at dusk…"); while Voltage looks, the orb works and the strip shows its slots with `aria-busy`.
- **Range picker** on the monitor bar: a draggable, resizable amber block, plus typed start and end fields and ◀ ▶ nudge buttons (100ms; Shift = 1s); arrow keys move it, Shift+arrow resizes; drag is never the only way (WCAG 2.2 dragging movements).
- **Questions, up to three**: the card shows "Question 1 of up to 3" as a `role="status"` sentence (not a bare number), the agent's guess as the first chip, *Go with your guesses* as a secondary button; chips never wrap.
- **Refusals in the thread**: a 4xx on a goal is Voltage's reply under the user's bubble, `role="alert"`, one sentence, one action; never the red strip.
- **Empty transcript** shows the place editor, never a bare sentence: a heading ("Where should the voice-over go?"), the range picker, the add editor, *Hear it* with the cost.
