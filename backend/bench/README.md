# The bench (Phase 19)

A labelled corpus of edits, every metric computed on each, and a gate that fails the build when any metric gets worse.

```sh
cd backend
.venv/bin/python -m app.bench run       # measure the corpus → bench/results/<stamp>.json, bench/rungs.json
.venv/bin/python -m app.bench gate      # compare the latest run with bench/baseline.json; exit 1 on a regression
.venv/bin/python -m app.bench accept    # make the latest run the baseline (commit it)
```

**The corpus.** The sample ad (real speech, Whisper's word times, the recorded ElevenLabs take) and a synthetic two-speaker clip built by ffmpeg, with edits labelled by construction: `good` must pass continuity, `bad` must fail (pitch off, noise), `ask` must not fit the slot. Real clips go in `bench/clips/` (git-ignored) with a manifest beside each:

```json
{"clip": "shop.mp4", "words": [["Hi", 0.0, 0.3, "A"], ...],
 "edits": [{"name": "the offer", "start": 2.1, "end": 3.4, "take": "offer.wav", "label": "good"}]}
```

**The metrics.** Prosody and audio integration (the measured engine), the rung the fit ladder used (none / gaps / tempo / ask), the seam discontinuity — the level step in dB and the colour step in semitones the edit *adds* at its seams on the rendered export, relative to the original at the same point — and the seconds of frozen frame in the export.

**The gate.** Labels are absolute. Against the baseline, no score may fall by more than 0.02, no seam may gain more than 1 dB or 1 semitone, and a frozen frame may not grow.

**The rungs table.** `rungs.json` holds the mean score each rung earned per ratio band (how far the take was from its slot). `fit.ladder()` reads it and puts the better rung first once both have three or more measurements in a band; until then the fixed order (pauses, then speech tempo) stands. `AVE_RUNGS` points it at another file.

## The agent eval (Phase 20d)

```sh
.venv/bin/python -m app.tools.agent_eval            # ten goals, one turn each, against the dev server on :8000
.venv/bin/python -m app.tools.agent_eval --only goa --goals 2 --cap 0.50
```

Ten goals across the three sample clips (the Goa beach, Bhaji Cam, the sample ad), each run as one turn under Just do it on a **fresh upload** of its clip, then graded by Claude (`--grader`, Opus 5.5 by default) against the plan's rubric: the voice fits the scene, the delivery matches the brief, the placement is sensible, the spend stays within the cap, nothing is committed without the gate, and the closing words are honest to the record. The grader reads the record — steps, plan items with their voice, model, dials and placement, costs — not the audio, and says so. Results land in `bench/agent-evals/<stamp>.json` with cost and wall clock per turn; the command exits 1 under 9 of 10. Every run spends real money (Claude and ElevenLabs); the uploads are deleted afterwards unless `--keep`.
