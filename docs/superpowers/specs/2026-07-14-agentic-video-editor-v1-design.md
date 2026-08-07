# Agentic Video Editor — v1 Design

**Date:** 2026-07-14
**Status:** Approved for planning
**Scope:** v1 (dialogue-change editing). Visual swap and later edit types are explicitly out of scope and noted as future phases.

---

## 1. Problem & Product Thesis

Shooting video is expensive, and reshooting a scene to fix a small problem — a wrong number, a flubbed line, a changed offer — is disproportionately painful. There is no good tool for *editing what was already shot* while keeping the result indistinguishable from the original take.

The Agentic Video Editor lets a user select a moment in an existing video, describe in plain English how the **spoken message** should change, and get back a seamlessly re-voiced and lip-synced version that looks and sounds as if it were shot that way. The user iterates by chat until satisfied, then commits the change.

**The differentiator is continuity.** Splicing an AI clip into footage is easy; making it *belong* — matching voice, delivery, audio levels, and mouth motion to the surrounding footage — is the hard problem and the moat. The product is an **agentic orchestration layer plus a continuity engine** built on top of swappable third-party generation models. We do not train models in v1.

### Target user
Primary: marketing / ad / social video teams producing short brand videos. Secondary (future): YouTubers and other talking-head creators. v1 is designed for the primary user.

---

## 2. Scope

### In scope (v1)
- Change what an on-screen speaker says: reword, change an offer/number, or fix a flub.
- Keep the **same speaker, same voice, same shot** — only the spoken segment changes.
- Continuity guaranteed across voice identity, prosody/energy, audio levels, and mouth motion.
- Timeline-based region selection → natural-language prompt → candidate preview → approve or iterate-by-chat loop.
- Commit approved edits non-destructively; export the final composited video.
- **English only.**
- Short-form video only: **cap ~2–3 minutes.**
- **Consent gate:** the uploader must confirm they have the right to edit and clone the speaker before any voice generation runs.

### Out of scope (future phases)
- **Phase 2:** Visual detail swap (change product color/label, remove object/logo/background) — reuses the same backbone with visual continuity checks added.
- Pacing/filler-word edits; full scene regeneration; multi-speaker crosstalk edits.
- Languages other than English; videos longer than the v1 cap.

---

## 3. Interaction Model

Confirmed via visual prototyping. The edit loop:

1. **Play/pause** the uploaded video in the editor.
2. **Select a region** on the timeline by dragging handles; selection snaps to word/sentence boundaries from the transcript.
3. **Prompt** the agent in natural language describing the change to the spoken content.
4. The agent produces a **candidate** — a preview of just the edited segment — marked "continuity checked."
5. **Approve → replace** commits the edit into the video, **or** keep chatting to refine until it is right.
6. **Export** the final video with all approved edits.

**Visual design:** dark premium theme, "Voltage" palette (electric blue + cyan accents on near-black). Left side = player + timeline with a glowing selection region and playhead; right side = agent chat with candidate preview and Approve/Try-again actions.

---

## 4. Architecture

Four cleanly separated layers, each independently understandable and testable:

1. **Editor front-end** — the Voltage web UI: player, timeline selection, agent chat, candidate preview, approve/commit, export.
2. **Agent orchestrator** — converts a natural-language prompt + selected region into a concrete **edit plan** (exact new text, voice profile, audio span, frame range), routes the plan through the generation adapters in order, and manages the iterate loop with preserved context.
3. **Generation adapters** — swappable wrappers around third-party APIs, one per capability slot: transcription (word-level timestamps), voice cloning / TTS, lip-sync. Each hides its vendor behind a stable interface so vendors can be swapped without touching the rest of the system.
4. **Continuity engine** — verifies every candidate *belongs* before it is shown. Scores voice match, loudness/EQ, prosody, and lip-sync; auto-corrects where possible, auto-retries where not, and surfaces honest warnings for anything it cannot fix to threshold.

**Non-destructive core:** the uploaded video is stored as **immutable source**; edits are an **ordered stack of approved changes**; a **render step** composites source + edits into output. This gives undo, rollback, edit history, and safe re-export for free.

---

## 5. Edit Pipeline (data flow)

1. **Ingest** — upload; extract audio; transcribe with word-level timestamps; detect the on-screen face; store source immutably.
2. **Select** — user frames the moment; selection snaps to sentence/word boundaries so cuts land in natural silences.
3. **Prompt** — user types the desired change to the spoken content.
4. **Plan** — orchestrator emits an edit plan: new text, voice profile, audio span to regenerate, frame range to re-sync.
5. **Generate** — adapters run in sequence: look up/clone the speaker's voice → synthesize new audio with matched prosody → lip-sync the mouth region across the affected frames.
6. **Continuity check** — engine scores the candidate; below threshold triggers auto-correction or auto-retry with adjusted parameters *before the user sees it*.
7. **Preview** — user receives the candidate segment with a "continuity checked ✓" indicator and any warnings.
8. **Approve or iterate** — approve pushes the edit onto the non-destructive stack; iterating returns to step 4 with context preserved.
9. **Export** — render the final video with all approved edits composited in.

---

## 6. Continuity Engine

For dialogue edits, "belonging" decomposes into four measurable checks. Each has a threshold and a defined correction path:

- **Voice identity** — speaker-embedding similarity between regenerated and original voice. Below threshold → retry with better reference audio.
- **Prosody & energy** — pace/emphasis matched against neighboring lines so delivery is not flat or robotic → re-synthesize with adjusted expressiveness.
- **Audio integration** — loudness, EQ, and room tone matched to adjacent audio, with micro-crossfades at seams to avoid clicks or level jumps → auto-applied.
- **Lip-sync accuracy** — lips match the new phonemes; mouth region blended into the real face with correct lighting and no smearing → sync-confidence score; retry or flag if low.

Anything not auto-fixable to threshold is surfaced as an honest warning rather than hidden. This engine is reused (with visual checks added) when visual swap arrives in Phase 2.

---

## 7. Non-Functional Requirements & Guardrails

- **Async job model** — edits run server-side and take on the order of minutes; the UI shows progress and notifies when a candidate is ready.
- **Length cap** — short-form only, ~2–3 minutes, to hold quality and keep cost/latency sane.
- **Consent gate** — uploader must confirm rights to edit/clone the speaker before any voice generation runs. Non-negotiable.
- **Versioning** — every candidate and approved edit is retained; nothing is lost; rollback is always available.

---

## 8. Error Handling

- **Continuity below threshold** → auto-retry with adjusted parameters, then honest warning. Never silently ship a bad edit.
- **Vendor/API failure** → retry with backoff; fall back to an alternate adapter where configured; surface a clear error otherwise.
- **Selection lands mid-word or spans a scene cut** → snap to boundaries and warn the user.

---

## 9. Testing Strategy

- **Adapter interfaces** — tested against recorded fixtures; no live API calls in the test suite.
- **Continuity engine** — tested on a labeled set of good/bad edits; must reliably catch the bad ones.
- **End-to-end golden path** — known input + edit → expected composited output.

---

## 10. Phasing

- **v1 (this spec):** dialogue change, English, short-form, highest achievable quality.
- **Phase 2:** visual detail swap on the same backbone + continuity engine, with visual continuity checks (temporal consistency, identity/lighting preservation).
- **Later:** pacing/filler edits, additional languages, longer videos, full scene regeneration, YouTuber-focused features.
