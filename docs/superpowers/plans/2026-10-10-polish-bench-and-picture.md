# Everything that is left: the polish pass, the bench, and picture that flexes

**Written:** 2026-10-10. **Asked for:** "yes lets do everything and then I will move to the upgraded plan" — build every unblocked item, each phase committed and merged, then the user moves ElevenLabs to the Starter plan for Phase 15.

## Where it starts

Every planned phase is on main (0–14, 13b, 9c, UX-1..UX-7, UX-5). 514 backend / 239 frontend tests, lint and `tsc -b` clean. What is left is the natural-fit roadmap (`2026-10-03-natural-fit-roadmap.md`, Phases 15–19) and the small leftovers each as-built note recorded.

Blocked on the user, left out of this plan and reported at the end: Phase 15 (ElevenLabs Starter), Phase 17 (a sync.so key), Phase 18 (a GPU box), the `tools/env-lock.sh` step (a passphrase), the real Google sign-in round-trip (an OAuth web client), and every listening-panel exit (people).

## Phase P · The polish pass

The leftovers, as one branch `polish-pass`, one commit each where they touch different code.

- **P-1 Takes voiced on the receipt.** The plan response gets `takes_voiced`: ElevenLabs calls recorded since the plan was made (`Ledger.calls_since`). The ship sheet's tiles gain "N takes voiced" and the stand-in-voice sentence stays. Nothing is stored; the receipt shows what the ledger knows.
- **P-2 A tighter reading.** `READ_SYSTEM` asks for one sentence under ~30 words when two are not needed, names nothing the person can see for themselves (line counts come from the UI), and leads with the one thing worth knowing. Offline reading unchanged.
- **P-3 Word timestamps on takes** (Phase 14's open item). ElevenLabs `…/with-timestamps` returns the audio with per-character times; the adapter asks for them, folds characters into words, and the candidate's audio carries `words` (text, start, end, relative to the take). Fitting uses them: a pause is now the quiet *between two words*, so a breathy consonant is never trimmed as a gap; `fit_notes` unchanged. Exposed on the candidate; the caption shows a take's words lit as they are said while the take plays in place.
- **P-4 The spend meter's breakdown as a popover.** The meter is a button (`aria-expanded`); its popover lists vendor lines, voice characters against their ceiling, and with sign-in on the person's spend across projects. Escape and a click outside close it; focus returns. The `title` goes.
- **P-5 Review rows: a player and keys.** "Play the seam" is a toggle that says *Stop* while its seam plays, with a thin progress line across the row's foot (the Player reports `onPlayingChange`); the bare `<audio>` becomes *Hear the take alone*, a second toggle. Rows are focusable (`tabIndex=0`): ↑↓ move, Space plays the seam, K keeps, H holds, A asks another take, U undoes a shipped line; a `kbd` legend at the foot of the review, as the transcript has.
- **P-6 The phone strip has a composer.** Under 960px, when Voltage is tucked away, the strip at the foot carries the composer (input + send); sending opens the panel so the reply is seen. Desktop rail unchanged.

Exit: tests for each; lint, `tsc -b`, pytest clean; MASTER.md's component list updated.

## Phase 19 · The bench (v1)

Branch `phase-19-bench`. "Every metric computed in CI; a quality gate per rung so the ladder chooses by predicted score."

- `backend/app/bench/`: a **corpus** (`bench/corpus.json`): synthetic clips made by ffmpeg (tone + solid video, a two-speaker synthetic with pauses) plus any real clip dropped in `backend/bench/clips/` (git-ignored) with labelled edits — each edit a take (a generated WAV of a given length) against a slot, labelled `good`/`bad` by construction (fits / needs 1.4× tempo / has a 2 dB level jump at the seam).
- **Metrics**, every one already in the product or added here: prosody, audio integration (the measured engine), the **seam discontinuity** (new: RMS level and spectral-centroid jump across each seam of a rendered export, in dB and semitones; `continuity/seam.py`), fit outcome per rung (pauses moved, tempo applied, model speed, picture flex once Phase 16 lands), and the render's frozen-frame seconds.
- **Runner**: `python -m app.bench run` writes `bench/results/<date>.json` and a markdown table; `python -m app.bench gate` compares against `bench/baseline.json` and exits non-zero when any metric on any labelled edit gets worse than its tolerance. `python -m app.bench accept` writes the new baseline.
- **Ladder by predicted score**: the bench also writes `bench/rungs.json` — mean score per rung per ratio band (how far the take was from the slot). `fit.choose()` consults it when present: for a given ratio the rung with the best predicted score goes first; without the file the fixed order stands.
- **CI**: `.github/workflows/ci.yml` runs pytest, the frontend lint/test/build, and `bench gate` on every push.

Exit: the gate fails a deliberately broken fit in a test; CI file present; results reproducible run to run (bit-exact ffmpeg flags).

## Phase 16 · Picture that flexes

Branch `phase-16-picture`. No frozen frame unless there is nothing else left, and then it is said.

- **Shots** (`media/shots.py`): cut times via ffmpeg's scene detection (`select='gt(scene,0.35)'`), cached in the project's settings. A flex never crosses a cut.
- **Motion** (`media/motion.py`): mean absolute frame difference per 0.25 s chunk from a 64-px grey decode, so time is added where the picture moves least.
- **Retime** (`render/retime.py`): a `Retime(start, end, out_duration, chunks)` — a source window stretched or squeezed to a new length, the stretch allocated across chunks in inverse proportion to motion, each chunk clamped to `MAX_FLEX` (1.12 by default, the roadmap's undetectable band) for a replace, `MAX_LIVING` (1.6) for a living hold. Frames are re-synthesised at the source frame rate with ffmpeg `minterpolate` (motion-compensated); `AVE_INTERPOLATOR=rife` shells out to a `rife-ncnn-vulkan` binary when one is on the PATH (seam only; not exercised here).
- **The living hold replaces the frozen frame.** An inserted line (`concatenate`) stretches the pause after its point — bounded by the next statement and the next cut — by the line's length at up to `MAX_LIVING`; the room's own sound from that pause sits under the line; what the pause cannot absorb is held at its end, and the candidate's note says "the picture holds for 0.8 s" only then. `compose` builds one video graph for the whole timeline (copy / retime / hold pieces, concat) and the audio from the same pieces.
- **Flex for a replaced line.** A new rung in the fit ladder between pauses and speech tempo: the slot's picture slows or speeds by up to `MAX_FLEX` before any speech tempo is applied (`EditPlan.flex`, the factor; the selection is the slot as shot). The renderer turns it into a `Retime`; the timeline after shifts by the difference, as inserts already do. `renderTime`/`sourceTime` in the frontend learn retimes.
- **Bench**: the rungs table gains `flex`; the frozen-frame metric must read zero on the corpus.
- **Front end**: the hold copy ("the picture holds while it plays") becomes "the picture slows a touch so it fits" with the factor on the row note and the receipt; the Export bar's inserts sentence says what flexed.

Exit: on the Bhaji Cam clip an added line after 0:09 ships with no frozen frame and the pause slowed ≤ 1.6×; a replaced line 10% long ships at natural speech with the picture at 1.10×; tests cover allocation, graph construction, time mapping, and the fallback hold. The 5-person panel is the user's.

## Order and rules

P → 19 → 16, each on its own branch, merged to main with a merge commit, as-built notes appended here per phase, counts recorded. Lint, `tsc -b`, pytest clean before advancing; anything blocked goes to the backlog list above rather than being half-built.
