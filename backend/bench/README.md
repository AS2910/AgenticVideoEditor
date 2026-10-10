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
