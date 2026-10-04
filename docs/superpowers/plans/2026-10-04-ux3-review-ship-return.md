# UX-3 · Review, ship, return

**Date:** 2026-10-04 · **Status:** built, from the "The line is the unit" mocks (L9–L11) and sections 6–8 of the UX plan of 2026-10-03.

## What changed

**Review is per line.** Every finished change is a row — before and after, the take, the verdict — with **Keep** and **Hold** on each. A take that failed the sound check starts held. **Ship it** (or "Ship 1 of 2") ships what is kept and holds the rest as drafts: they stay *ready*, with their takes, for a later ship. A shipped line keeps **Undo** in its row: the edit is reverted, the line goes back to a draft (the plan item returns to *ready*, "You undid the line at 0:17" joins the log), and the project is a draft again.

**The ship sheet.** After shipping, a sheet says what is in the file: "2 lines changed, 1 added; 1 held as a draft. 0:48.9 → 0:49.6 (+0.7 s). $0.11 for this plan." with the lines listed, **Download MP4**, **Copy link**, and **Make a variant**.

**Variants.** `POST /projects/{id}/variants` makes the same clip a new project — the media copied, transcript, speakers, settings and consent carried over — with the latest plan as a draft: every line planned again, nothing voiced, "Made as a variant of bhaji.mp4, with its plan as a draft" in its log. The app opens it; the project list shows "variant of bhaji.mp4".

**The project list** shows a frame of each clip (the source media's half-second mark), where it stands — *New*, *Draft*, *Shipped* — and its last change ("Rendered the edited video", "Planned 2 changes"), from richer summaries on `GET /projects`.

**Consent at first voicing.** The gate before the app is gone; a clip is uploaded without consent. The first time a voice is about to be made — a line heard, a plan run, a draft plan made — a sheet asks in a sentence, naming the speaker: "I'll be creating speech in the Shopkeeper's voice, and editing what they say on camera. You have their permission?" *Yes, I have it* records it (`POST /projects/{id}/consent`) and the action resumes; *Not yet* does nothing. Asked once per project, remembered; the server still refuses to voice without it.

**Spend** is a small meter against the project's cap in the header, amber past 80 %, with the breakdown by vendor on hover. Costs before (line editor, plan foot) and after (take, receipt) stay where they were.

## Where

- Backend: `create_variant`, `_summary` (state, last change, media, variant_of), `revert_edit` returning a shipped plan line to *ready*, in `app/api/main.py`. `approve` with `items` already did partial shipping.
- Front end: `ReviewPanel` (Keep / Hold, Ship, Undo), `ShipSheet`, `ConsentSheet` (replaces `ConsentGate`), `ProjectList` (frame, state, last change), `SpendMeter`; App `withConsent` / `confirmConsent` (a ref carries the grant into actions that resume), `approveAll(items)`, `makeVariant`, `api.grantConsent` / `createVariant`.

## Exit

485 backend + 186 frontend tests; lint, typecheck and build clean. Stories C6, D2, D5, G1, G2, G3 pass. Live: the project list reads "bhaji.mp4 · Shipped · Made the added closing line warmer…" with a frame; a variant of the Bhaji Cam project (p9) came back with both speakers, consent, and its plan as a draft with nothing voiced.

## Left for later

A small player per review row (G24): Hear the seam still plays in the monitor, which is full-size in Review. Share is a link to the rendered file on this server, not a hosted page (I1 sign-in first). Keyboard (UX-4).
