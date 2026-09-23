# Phase 6a — Measured Continuity (prosody + audio integration) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-23
**Status:** Done 2026-09-23 — exit evidence in the roadmap
**Roadmap:** the half of Phase 6 that does not depend on the backlogged 4b (voice clone) and 5 (lip-sync).

**Goal:** two of the four continuity scores become measurements of the real audio instead of constants; the pipeline auto-corrects what it can and regenerates what it cannot, within the budget; and the scorecard stops presenting made-up numbers as if they were measured.

**Exit criteria**
1. Prosody and audio integration are computed from the generated audio and the source audio around the selection.
2. A labelled set — real good edits and deliberately bad ones built from the sample ad — separates cleanly at the chosen thresholds: every bad edit fails, every good edit passes.
3. Loudness and room tone are matched to the context automatically, before the candidate is shown.
4. A prosody failure triggers regeneration (paid) up to a cap, and the best attempt is kept.
5. The UI shows *which* scores are measured. Voice identity and lip-sync read "not measured yet" — not 0.95.

## Decisions worth your eye

| Decision | Choice |
| --- | --- |
| Regeneration cap | `AVE_MAX_REGENERATIONS=2` — at most 3 paid calls per preview. Every call is charged to the project budget first; if the budget runs out mid-loop the best candidate so far is kept, not an error. |
| When scores are measured | Only when the voice is real (ElevenLabs). The mock voice is a sine tone; measuring a tone's "prosody" is meaningless, so offline/dry-run keeps the mock engine — and its scores are labelled *simulated*. |
| What gates approval | Only the measured checks. Voice identity and lip-sync are `null` and cannot block anything until 4b / 5 exist. |

## Measurements (`app/continuity/signals.py`, numpy)

All on mono 16 kHz audio. *Context* = the source audio of the transcript words within 3 s either side of the selection, excluding the selection itself.

- **Speech level** — RMS dBFS over active frames (20 ms frames; active = within 30 dB of the loudest).
- **Noise floor** — 10th percentile of frame level.
- **Pitch** — per-frame autocorrelation F0 in 75–400 Hz, voiced where the normalised peak > 0.5; the median over voiced frames.
- **Speaking rate** — words per second: the new text over the selection's length, against the context words over their spans.

Scores (each clamped to 0–1; thresholds start at 0.8 and are set by calibration):
- **Prosody** = min(pitch score, rate score). Pitch score falls off with the semitone difference of the medians; rate score with the log-ratio of the rates.
- **Audio integration** = min(level score, noise-floor score), measured *after* auto-correction.
- A metric with nothing to compare against (no context speech, no voiced frames) is `null`, not guessed.

## Auto-correction (before the candidate is shown; spec §6)

1. **Level match** — gain the generated audio so its speech level equals the context's (clamped to ±12 dB).
2. **Room tone** — if the generated audio's floor is more than 10 dB cleaner than the context's (studio TTS into real footage), lay the source's own between-word room tone under it at the context's floor level. The splice then loses the tell-tale dropout.

Crossfades at the seams belong to rendering (Phase 7).

## Tasks

- [x] **1 · Domain + dependency** — `ContinuityReport` metrics become `float | None` and gain `measured: tuple[str, ...]`. numpy added to `pyproject.toml`.
- [x] **2 · Signals** — tests first on synthetic audio with known answers: a 220 Hz tone reads 220 Hz; −20 dBFS reads −20; silence has no pitch; a known noise floor reads within 2 dB.
- [x] **3 · Context extraction** — tests first: words either side within the window, never the selection; `None` with no context.
- [x] **4 · Scoring** — tests first on the scoring functions (0 difference → 1.0, monotonic fall-off, `None` propagates).
- [x] **5 · Auto-correct** — tests first: level lands within 1 dB of the context; room tone is added only when the generated audio is much cleaner; duration unchanged.
- [x] **6 · `MeasuredContinuityEngine`** — returns measured prosody + integration, `null` voice/lip-sync, and the corrected audio artifact. Mock engine labels itself (`measured=()`).
- [x] **7 · Calibration** — build the labelled set from the sample ad (pitch-shifted ±6 st, noise-drowned, and the real ElevenLabs fixture as the good case); pick thresholds that separate it; pin them as a test that runs the whole set.
- [x] **8 · Pipeline retry loop** — tests first with a scripted voice: fails then passes → 2 attempts, second kept; always fails → cap reached, best kept, warning added; budget exhausted mid-loop → best kept.
- [x] **9 · API + UI** — `null` metrics serialised; the scorecard shows "not measured yet" for `null` and "simulated" for unmeasured values; `/health` reports `continuity: measured:prosody,audio` or `mock`.
- [x] **10 · Live check + docs** — real preview on the sample, scores recorded; a deliberately bad edit (pitch-shifted) fails live; roadmap/README updated.

## Deviations from the plan (found by measuring real audio)

- **Speaking rate dropped from the score.** On the sample, Whisper counts the original "20% off" as 2 words in 0.96 s against 3.5 words/s around it, so the speaker's own line failed. Rate is held by the duration fit instead.
- **Noise-floor match replaced by clarity** (speech level above the clip's quietest part). A sub-second clip has no silence to read a room from: the TTS line's "floor" read −52 dB of speech tails, which would have failed every clean edit against the room.
- **Room tone is filtered to quiet frames.** Calibration showed the correction *damaging* good edits (the original line moved 221→207 Hz): the "gap" where Whisper dropped `%` holds the spoken "percent", and it was being mixed under the new line.
