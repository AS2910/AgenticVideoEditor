# UX-1 · The line is the unit

**Date:** 2026-10-04 · **Status:** built, from the "The line is the unit" mocks (L2–L5, with L10's "over the picture" default) and the UX plan of 2026-10-03.

## What changed

**Everything about a line happens at the line.** The transcript (`LineDoc`) is the working surface. Each row carries its state in words — *Planned*, *Voicing…*, *Ready to hear*, *Needs you*, *Kept*, *Removed*, *Couldn't voice it* — and, on hover or focus, its actions: *Change the words*, *Change the delivery*, *Add a line after*, *Remove*, *Play original*. The editor opens in the row: wording with "You'd be changing:" shown as you type, **Delivery** (as spoken, warmer, more excited, calmer, slower, firmer, or in your words), **Voice**, **Sound meets picture** for an added line (*Over the picture*, the default, or *Hold the picture*), **If it runs long**, and the cost before *Hear it*. The take appears under the line: *Play take in the video*, a verdict in words with the score behind it ("Sounds like the Customer, and sits in the room. Trimmed 120 ms of pauses."), *Keep* and *Another take*; a second take sits beside the first as a choice. A kept line shows its change inline with *Undo*; a removed line is struck through with the room's own sound in its place; an error sits in the row with *Try again*. "+ Add a line here" closes the list.

**The picture does not stop.** An added line is placed *over* the picture that follows: the engine layers it on the pause after the line, fitted to that pause (Phase 14's gap-first fit). Only when the pause cannot hold speech, or the take cannot be fitted to it, is the picture held — and the line says so. The planner prefers "over" for added lines too.

**The panel does less.** Takes, questions and errors no longer appear there; what you must do next is the panel's last element ("One line needs you, at 0:17 · Go to it"), and *Go to it* scrolls the line into view. The chat box is for the whole video; a selection on the *Precise* word timeline (hidden by default) still previews through it, as a fallback.

**Audio goes where you put it (UX-1b, same day).** The user asked to "pick an audio and move it anywhere in the timeline (edited or otherwise)". Every take and every kept line shows "Starts at 0:04.96 · Move": Move puts a draggable block of the take's length on the monitor's bar (arrow keys nudge it, Shift for a second), with a typed time and ◀ ▶ nudges beside the line; *Put it here* re-places the same audio without voicing it again (`POST /candidates/{id}/move`, or `POST /edits/{id}/move` for a kept line, which reverts and re-keeps in one step). The add editor has *Starts at*: empty follows the line; a time puts the new line there, over the sound at its natural length (or with the picture held there).

**The original speech moves too (UX-1c, same day).** The user opened a line and asked how to shift its timing; Move only lived on takes and kept lines. Every untouched line now has **Shift** (and the S key): the same place control appears — drag the block on the bar, type a time, nudge — and *Put it here* calls `POST /lines/shift {start, end, to}`: the line's own audio is cut out of the source (`extract_segment`), the room's sound takes its place, and the words play over the picture from the new time, as spoken, nothing voiced. It is two paired edits (`ApprovedEdit.partner`): undoing either undoes both; moving the placed half again keeps the pair linked. The user then asked to see the line in its new position and to drag it there: a shifted line is now **its own row at the new time** ("Moved · Moved from 0:09, as spoken, over the sound here", with Undo, Move and a grip), the original row stays struck through as "Moved away · Moved to 0:01.58", and the line it lands on is left alone. **Any untouched line, and any moved row, can be dragged up or down the transcript by its ⋮⋮ grip**: while dragging, an amber line shows where it would land with "Starts at 0:08.88" (the end of the row above), the block moves on the monitor's bar too, and dropping it shifts the line there.

**Play in place.** A take plays over the video from its line, with the original's words muted for a replacement and left alone under an added line, and stops at the end of the take.

## Where

- Backend: `EditPlan.delivery` and `DELIVERY_SETTINGS` in the ElevenLabs adapter (stability / style / speed per delivery); mix `over` resolved in `_generate` (layer on `room_after`, else concatenate, `MIN_OVER_ROOM` 0.3 s); `POST /projects/{id}/lines/remove` (room tone from the recording's own quiet gaps, tiled; approved at once; undone with revert); plan items carry `delivery` and may be `over`; `PUT …/items/{id}` takes `delivery` and `mix`.
- Front end: `LineDoc` (replaces `TranscriptDoc`), `transcript/verdict.ts` (the verdict in words), `Player` `compact` and `muted`, App per-line state (`lines`), `hearLine` / `keepTake` / `anotherTake` / `answerLine` / `removeStatement` / `playTake`, the *Precise* toggle.

## Exit

464 backend + 162 frontend tests; lint, typecheck and build clean. Stories B2, B3, B4, B5, B6, C1, C2, C3, C4, C5, F1, F4 are reachable without visiting the panel.

Live on the Bhaji Cam clip: "Thirty off." added after "Feed is live." (a 0.74 s pause before the next line) was **layered over the picture** — three takes, the model's 1.2× speed, 110 ms of pauses trimmed, prosody passed — while a longer "Thirty off today." in the same place fell back to holding the picture, as designed. "Done, sir." removed and undone. One finding fixed on the way: word-boundary snapping now tolerates 20 ms of float drift, so a timing that comes back from JSON a few millionths off no longer pulls a neighbouring word into the span.

## Left for later

Consent at first voicing (UX-3); per-line review and the ship sheet (UX-3); revising the plan in words and Stop (UX-2); keyboard (UX-4). Cutting the picture when a line is removed waits for Phase 16; "ease the picture" for Phase 16 too.
