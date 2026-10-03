# The warm agentic pass (Phase 13b)

**Date:** 2026-10-03 · **Status:** built the same day, from the "Warm agentic" page of the mocks (https://claude.ai/artifact/LhccYtUyhe2YAipTQ6Nyp7, screens W1–W6).

## Why

After Phases 12 and 13 the user's verdict was: it does not *feel* agentic enough, and the design should be smooth, elegant, user-friendly and warm to the eye. The first mocks had the right structure but the manner of a tool. This pass gives Voltage a presence and a way of speaking, and changes the room it works in.

## What changed

**The look.** `frontend/src/styles/theme.css`: a warm dark room (`#171412` / `#1F1B18` / `#2A2522`), cream text, one amber accent (`#E9A860`, deep `#C9823D`, ink on it `#1A1511`), rose only for "needs you", teal for "sounds right", Fraunces for headings and for Voltage's name. Panels at 16 px radius with a soft shadow; amber primary buttons. Voltage is a soft glowing orb (`Orb.tsx`) that breathes while working.

**The manner.** Voltage says what it noticed while reading (`findings`, revealed one by one), asks at most one question before planning (`question`, with its own guess, so "go" is always enough), gives a reason sentence per change, narrates each take ("Take 1: pitch is 6 semitones off the surrounding speech. Trying again"), recommends its own fix first, and signs off with a receipt. When you edit a line yourself it says so and stands by.

**The flow.** W1 is its own stage after upload: "What should this video say?", with "Edit a line yourself instead" one click away. W2 lights the line Voltage is "on" while it reads. W3 waits with *Go ahead* and *Adjust*. W4 narrates. W5 is "Three changes, ready to ship" with *Hear the seam* (the edited video from 1.5 s before the change to 1.5 s after) and *Ship it*. W6 offers two tighter wordings, a *prefer a shorter wording* policy, and a readout of how the last take fit.

## Where

- Backend: `app/orchestrator/planner.py` (`Question`, `findings`, `answer`), `app/adapters/claude_planner.py` (schema and prompt), `app/domain/plan.py` (`findings`, `question`, `progress`), `app/usage.py` (`spent_usd_since`), `app/orchestrator/pipeline.py` (why a take is redone), `app/api/main.py` (`clarifying` status, `POST /plans/{id}/clarify`, `progress` per item, `spend_usd`, `long_lines: shorten`).
- Front end: `GoalStage`, `Orb`, `PlanCard` (rewritten), `ReviewPanel`, `ActivityLog`, `TranscriptDoc` (reading state, offers, readout, `onEditingChange`), `Player` (a seek can play and stop), `App` (the `goal` stage, thinking and clarifying states, the composer's three jobs, seam playback, readouts).

## Exit

424 backend + 158 frontend tests; `npm run lint`, `tsc` and `npm run build` clean. Headless screenshots at 1470 px: the goal stage (W1), the editor with a shipped plan, and a proposed plan after a question (W3).

**Live, on the Bhaji Cam clip.** Goal: "Add a line saying delivery is free this week, and make the close warmer." Claude's findings: "Delivery only comes up once, in the final line, so that's the natural place for the free-delivery news." "The clip ends flatly on a request with no reply from the shopkeeper, so the close has nowhere warm to land." "The shopkeeper speaks in short, polite beats ('Done, sir.'), so a new line in his voice should stay brief." Its question: who should say it, with the shopkeeper as its guess; taking the guess gave a one-change plan in 12 s. Two bugs surfaced and were fixed the same hour: the model put "Shopkeeper:" in front of the words to speak (`strip_label`), and an added line spoken by someone else was attributed to the line it followed, so it would have been voiced in the wrong person's voice (a change now names its `speaker`, and the run uses that voice). Planning cost ≈ $0.03.

## Not in this pass

"Ease the picture" as a needs-you option (the mock shows it; it is Phase 16 of the natural-fit roadmap and is not offered until it is real). Replanning by conversation still makes a new plan.
