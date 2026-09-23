# Phase 7 — Real Render Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Date:** 2026-09-23
**Status:** Done 2026-09-23 — exit evidence in the roadmap

**Goal:** Export produces a real MP4 you can download: the original video with the approved lines re-voiced, seamless at the splices.

**Exit criteria**
1. Export returns a stored MP4 artifact; the UI offers it as a download.
2. The file plays, has the source's duration (±1 frame), and its audio says the edited words — verified by transcribing the whole rendered file.
3. No clicks at the seams: equal-power crossfades, measured as no sample discontinuity above the surrounding signal.
4. Re-approving a span replaces the earlier edit there instead of stacking both.

## Decisions worth your eye

| Decision | Choice |
| --- | --- |
| Video in edited spans | **The original frames.** Lip-sync is backlogged, and the mock "frames" are a flat colour — splicing those in would make the export worse, not better. So v7 re-voices the audio over untouched video; the mouth will not match the new words until Phase 5. The render takes a flag so Phase 5 flips it on. |
| Overlapping edits | The **later approval wins** on the overlap (edits are a stack). Today's manifest emits both segments — a bug, fixed here. |
| Sync vs job | Synchronous. Video is stream-copied and only the audio is re-encoded, so a 3-minute source renders in seconds. |

## Tasks

- [x] **1 · Manifest fix** — tests first: two edits on the same span → one edited segment, the later one; partial overlap → the later edit keeps its whole span, the earlier is trimmed; adjacent edits untouched.
- [x] **2 · Audio splice** (`app/render/compose.py`, numpy) — tests first: source audio decoded at 48 kHz in its own channel layout; each edited span replaced by its (upmixed, resampled) audio; 20 ms equal-power crossfades inside each span's edges; untouched regions bit-identical to the decoded source.
- [x] **3 · Mux** — tests first: video stream-copied when the container allows, re-encoded to H.264 when it does not; AAC audio; duration within one frame of the source; stored as a `video/mp4` artifact.
- [x] **4 · API** — `POST /export` returns the manifest plus `render` (the artifact). Export with no edits still renders (a clean copy). Download is the existing artifact endpoint, with a `Content-Disposition` filename.
- [x] **5 · UI** — after Export, a "Download MP4" link; tests first.
- [x] **6 · Live check + docs** — render the live 6a candidate: probe, transcribe the whole output (expect "Get 30% off today only"), check the seams; roadmap/README; commit.

## Deviations from the plan

- **Content-Disposition** was not needed: the UI link uses the `download` attribute (same origin through the dev proxy), so the artifact endpoint is unchanged.
- **Found live and fixed:** the demo edit failed when ElevenLabs returned a 0.74 s take for a 0.96 s selection (tempo 0.77 < 0.8). `fit_duration` now pads a slightly short line with silence (speech must still fill ≥ 60 % of the span), and the pipeline regenerates unfittable takes.
