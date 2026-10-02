# Video Edits — Roadmap

**Date:** 2026-10-02
**Status:** Proposed. Nothing started.
**Builds on:** `2026-09-22-real-pipeline-roadmap.md` (Phases 0–13). Does not supersede it: this is the video half of the same product, sequenced.

**Question this answers:** today every edit is an audio edit. The export's video track is the source's own frames everywhere; the only thing the renderer ever does to the picture is hold a frame while an added line plays. Can the editor change the picture too, and in what order should that be built?

> This is a **roadmap**, like the real-pipeline one: it fixes the sequence, the exit criteria and the decisions. Each phase gets its own TDD task plan when it starts. Phase 14 is written in enough detail to start from.

---

## What is actually real today (video)

Verified by reading the code on 2026-10-02 (`app/render/compose.py`, `app/render/renderer.py`, `app/orchestrator/pipeline.py`, `app/adapters/mock.py`, `app/adapters/claude_planner.py`).

| Piece | Today | Gap |
| --- | --- | --- |
| Export video track | the source's frames, stream-copied when H.264 (`compose.py`) | the picture is never changed |
| Frame hold for an added line (`mix: concatenate`) | real: `hold_filter` trims, `tpad`s and `concat`s the video, re-encoded | the only video operation that exists |
| Lip-sync slot | `LipSyncAdapter` protocol, `MockLipSyncAdapter` (a flat-colour MP4 the length of the span), "Matching mouth movement" job step, `frames` artifact on every candidate and edit, `lip_sync` score slot, `use_generated_frames` switch in `compose()` | the switch raises `NotImplementedError`; the mock frames are deliberately never spliced in |
| Face detection at ingest (spec §5.1) | absent | nothing locates the mouth |
| Planner's own view of itself | the system prompt tells Claude *"It cannot change visuals, music, or pacing"* | the agent refuses video asks by design |
| Removing a line / shortening the video | absent — `MIXES` is replace / layer / concatenate | the most-asked video edit and it needs no vendor |
| Visual swap (spec §3 "Phase 2") | absent | generative; a vendor and a visual continuity engine |

So: **yes, audio only.** The lip-sync plumbing is complete end to end and waiting on a vendor; everything else about the picture is untouched.

---

## The three tiers of "video edit"

They differ by an order of magnitude in cost and risk, so they are sequenced by that, not by how impressive they look.

1. **Timeline edits** — remove a line, trim the ends, shorten to a target length. Pure ffmpeg on the source's own frames. No vendor, no spend, no new media generated. The non-destructive stack, the manifest and the trim/concat filter graph already exist. **Phase 14.**
2. **Lip-sync** — the mouth matches the re-voiced words. The video half of the dialogue edit the product was designed around. Every seam for it is built; blocked only on a vendor key (roadmap open decision 1). **Phase 5**, unparked.
3. **Visual swap** — change a product colour, remove a logo, replace a background. Generative inpainting across frames plus a new, visual continuity engine. The design spec's "Phase 2". **Phase 15**, sketched only.

Captions and text overlays (`drawtext`) are an ffmpeg-only edit too; they ride on Phase 14's compositor and are listed there as an optional follow-on, not a phase.

---

## Phase 14 · Cuts — remove lines, shorten the video *(no vendor cost)*

**Goal:** "Cut the second line", "drop the bit where he stumbles", "make it under 15 seconds" produce a shorter export where the removed span is gone from both picture and sound, and the seam is clean — or the editor says honestly that it will jump.

**Why first:** it is the video edit people actually ask for on a finished ad, it costs nothing to run, it needs no key, and it is the first edit where *visual* continuity must be measured. That makes it the right place to grow the continuity engine toward the picture before a vendor is in the loop.

### Decisions worth your eye

| Decision | Choice |
| --- | --- |
| What a cut is | A fourth `mix`, `"cut"`: the selection is removed from the video entirely and the rest closes up. `new_text` is empty. Nothing is synthesized or lip-synced; the export is shorter by the span. |
| Where cut edges land | Snap to word boundaries as today, then **widen into the silence either side** (midpoint of the pause before the first word and after the last, capped at ~150 ms each way) so the cut lands in a gap (spec §5.2), not on a consonant. |
| Media on a cut candidate | `EditCandidate.audio` / `.frames` and `ApprovedEdit` become `MediaArtifact | None`. Honest: a cut has no generated media. Touches `pipeline.py`, `api/main.py` (`_artifact_dict`), `store/codec.py`, `renderer.py`, and the frontend `Candidate` / `CandidateCard` types. The alternative — a zero-length placeholder artifact — would be a lie the renderer has to special-case anyway. |
| Overlap rules | Same stack as today: a later approval owns the overlap. A cut over an earlier replaced line removes that line's edited audio too; a later replace over part of a cut un-cuts that part. A reverted cut plays as shot. Manifest tests pin all four. |
| Source time vs export time | Edits keep referring to **source** time (the source is immutable). Only the compositor maps to output time. The UI shows the transcript in source time with the cut line struck through, as it already does for tracked changes. |
| Video encode | A render with any cut re-encodes the video (as inserts already do). Stream copy would need keyframe-aligned cuts; not worth it for ≤3-minute sources. |
| Visual seam check | **Measured, not asserted.** Decode the last ~5 frames before and first ~5 after the cut as greyscale; score the seam by the mean absolute frame difference *across* the cut relative to the typical adjacent-frame difference *within* the source nearby. Reported as `visual_seam` on the continuity report (a new, optional field, `None` on non-cut edits). Calibrated on the sample ad and the Bhaji Cam clip. Below threshold → warning *"This cut lands mid-motion; the picture will jump."* — still approvable ("Approve anyway" exists). |
| Audio seam | The two sides are joined with the existing 20 ms equal-power crossfade; `audio_integration` is measured across the seam (levels either side) with the engine that exists. |
| The agent | Planner prompt gains `"cut"` with the rule *remove a line only when the goal asks to shorten, drop or remove something*; `_Edit.mix` gains `"cut"`; estimate counts zero voice characters for a cut. `RulePlanner` learns `cut "X"` / `remove "X"` offline. A goal like *"make it under 15 s"* is a planning problem (which lines carry least) that Claude already has the whole transcript for. |

### Tasks

- [ ] **1 · Domain + manifest** — tests first (`tests/domain`, `tests/render`): `MIXES` gains `"cut"`; `render()` returns `cuts` alongside `segments` and `inserts`; cut inside original footage, cut over an earlier replace, replace over part of a cut, two cuts, cut next to an insert, reverted cut — all pinned. Output duration = source − cuts + inserts.
- [ ] **2 · Compositor** — tests first: `hold_filter` generalises to a timeline filter that trims, drops and holds; audio spliced with the cut span removed and the seam crossfaded; untouched regions bit-identical; duration within one frame. Re-encode whenever there is a cut.
- [ ] **3 · Optional media on candidates and edits** — `MediaArtifact | None` through pipeline, codec, API, DB round-trip, frontend types. A cut candidate serialises with `audio: null, frames: null`.
- [ ] **4 · Cut edges** — `snap_to_cut_boundaries` in `domain/transcript.py`: word snap, then widen into silence as decided; tests on the sample's real word timings.
- [ ] **5 · Visual seam signal** — `continuity/signals.py` + `measured.py`: frame extraction via ffmpeg to rawvideo grey, numpy difference ratio; synthetic tests (solid colour → clean; colour change at the cut → jump; a slow pan → in between); `visual_seam` on the report, `measured` lists it; calibration test on both real clips.
- [ ] **6 · Pipeline** — `run_edit` short-circuits for a cut: no voice, no lip-sync, no budget charge; continuity assesses the seams only; progress steps read *Checking the seam*.
- [ ] **7 · Intent + planner** — `claude_intent` reads "cut / remove / drop …" as a cut over the selection; `claude_planner` and `RulePlanner` emit `mix: "cut"`; estimate shows 0 characters; the planner's self-description no longer says it cannot change pacing.
- [ ] **8 · API** — preview/plan/approve/export accept and return cuts; export manifest gains `cuts`; `GET /projects/{id}` reopens them.
- [ ] **9 · UI** — transcript row: struck-through line with *(cut)* and Revert; plan card and review: *Removes the line*, no take to play, the seam score instead; line editor: a *Cut this line* action; timeline: cut span hatched; Edited player plays the shorter render (already does).
- [ ] **10 · Live check + docs** — on the Bhaji Cam clip: *"cut the line about the regular ones"* → export shorter by that line, Whisper transcribes the render without it, seam discontinuity in the audio range already measured for Phase 7, `visual_seam` reported; then *"make it under 20 seconds"* → Claude picks lines, Run, Approve all, export length checked. Roadmap + README; commit.

### Exit criteria

1. A cut line is gone from the export's picture and sound; the file is shorter by exactly the span (±1 frame) and plays everywhere the current export does.
2. Nothing outside the cut changes: audio bit-identical outside the seam, video re-encoded but otherwise the same frames.
3. `visual_seam` and `audio_integration` are measured at the seam; a deliberately mid-motion cut reliably warns, a cut in a still shot reliably passes.
4. The agent plans cuts from a goal ("shorten", "remove", "under N seconds") and the estimate for a cut is zero vendor spend.
5. Revert on a cut restores the source there; the test suites stay offline.

### Optional follow-on (same compositor, no phase of its own)

- **Captions / text overlays** — `drawtext` over a span: *"put '30% off' on screen at the end"*. A fifth mix, `"caption"`, with text, span, and a fixed house style. Worth doing only if asked for; the planner can already place it.

---

## Phase 5 · Lip-sync *(unparked from the Backlog; needs a vendor key)*

**Goal:** the mouth matches the re-voiced words, so a dialogue edit is finally a video edit.

Everything below the vendor is built: `LipSyncAdapter.sync(source, plan, audio) -> MediaArtifact`, the `frames` artifact, the job step, the score slot, and the `use_generated_frames` switch. What is left is the vendor, the face, the composite and the measurement.

### Decisions to settle at the start (roadmap open decisions 1 and 4)

| Decision | How to settle it |
| --- | --- |
| Vendor | **Spike first, as the roadmap says.** Same ~10 s clip from the Bhaji Cam footage through each candidate (Sync.so, Hedra, Runway; add any the key allows), compare mouth quality, identity preservation, latency, price per second, and whether it accepts an arbitrary source clip plus an audio file. Pick on the evidence, record it here. |
| Full segment vs mouth-region composite | Whatever the vendor returns. A vendor that returns a whole re-rendered clip → replace the span's frames (`use_generated_frames=True`, overlay the clip at the span, re-encode). A vendor that returns a mouth crop → composite it with a feathered mask over the source frames. The adapter normalises both to a full-frame `frames` artifact for the span so the compositor has one path. |
| Span padding | Ask the vendor for the span plus ~0.25 s either side so the mouth settles into and out of the edit; the compositor crossfades (dissolves) the first and last few frames to hide any residual difference. |
| No face / several faces | Ingest detects faces (spec §5.1, the missing half) and stores per-second face boxes; a span with no face skips lip-sync with the warning *"No face on screen here — the mouth was not changed"*; several faces → the largest, with a warning, until face↔speaker association exists (not v1). |
| Cost | Metered in the ledger like every vendor (`lipsync` line, USD per second), under `AVE_PROJECT_BUDGET_USD`; `AVE_DRY_RUN=1` and no key keep the mock. Lip-sync runs once per edit, on the winning take (already so). |

### Tasks (sketch — the real task plan is written when the key arrives)

- [ ] **1 · Vendor spike** — one script under `tools/`, the same clip through each; a table of results in this document.
- [ ] **2 · Face detection at ingest** — per-second face boxes stored with the project; refuse nothing, just record. Offline detector (OpenCV Haar/DNN or mediapipe) so tests stay offline.
- [ ] **3 · Adapter** — real `LipSyncAdapter` for the chosen vendor, recorded-cassette tests, retry/non-retry classification like ElevenLabs; mock kept.
- [ ] **4 · Composite** — `compose(use_generated_frames=True)`: the span's frames replaced or masked, padded and dissolved; cuts and inserts still honoured.
- [ ] **5 · Measured lip-sync score** — AV-sync confidence over the synced span (SyncNet-style offset/confidence, or the vendor's own score if it exposes one), on the report as `lip_sync`; calibrated against a good take and an off-by-200 ms take.
- [ ] **6 · UI** — the Edited player shows the new mouth; the candidate card's frames preview plays; the stock-voice warning stays until 4b.
- [ ] **7 · Live check + docs** — the Phase 13 Diwali plan re-run with lip-sync on; export inspected by eye and by score.

### Exit criteria

1. On the sample and the Bhaji Cam clip, a replaced line's mouth visibly matches the new words.
2. `lip_sync` is measured, and a deliberately desynchronised take fails it.
3. Dry-run and keyless runs are unchanged; the suites never call the vendor.

---

## Phase 15 · Visual swap *(the design spec's "Phase 2"; after Phase 5)*

Change a product's colour, remove a logo, swap a background — on the same backbone: select → describe → plan → generate → continuity check → approve → render. Only the sketch belongs here; the plan is written after Phase 5 shows what a frame-generating vendor costs and how it behaves in this pipeline.

- A new adapter slot, *visual edit*: (source, span, mask or region, instruction) → frames artifact for the span.
- A region selection in the editor (click or box on the player), stored in source coordinates.
- **Visual continuity checks** added to the engine (spec §6, last line): temporal consistency across the span (frame-to-frame flicker), identity and lighting preservation against frames outside the span, and the seam checks from Phase 14.
- Same stack, manifest, revert, budget and dry-run rules as every other edit.
- Candidates to spike: Runway's video-to-video editing, Pika, Luma; or a per-frame inpainting model with a temporal consistency pass. Priced per second; likely the most expensive vendor in the product, so the budget ceiling matters here more than anywhere.

---

## Sequence and recommendation

**Phase 14 first, now.** It is free, needs no key, is the video edit a marketing team asks for most on a finished cut, and it grows the continuity engine toward the picture under controlled conditions. **Phase 5 as soon as a lip-sync key exists** — its spike can run in parallel with 14 since the spike is a standalone script. **Phase 15 after both**, when the frame-generation path and its costs are understood.

## Cross-cutting rules (unchanged)

The test suite never calls a vendor; secrets never land in git; every paid vendor is metered and sits under the budget ceiling and dry-run; every real adapter keeps its mock; one phase, one plan, one review.
