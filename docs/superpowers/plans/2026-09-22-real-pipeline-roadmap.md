# Real Pipeline — Phased Roadmap

**Date:** 2026-09-22
**Status:** Phases 0–4a, 6a, 7, 8 and 9 done and clean (8 and 9 on 2026-09-26; 9c is a design). Phases 10 (editing UX) and 11 (multiple voices) done the same day. Phases 4b and 5 moved to the **Backlog** — both are blocked on vendor access, not on code.
**Supersedes nothing.** Builds on `2026-07-14-walking-skeleton.md` and `2026-07-17-voltage-frontend.md`.

**Goal:** turn the mocked walking skeleton into a system that ingests a real video, produces a real re-voiced and lip-synced segment, verifies continuity with real signal analysis, and exports a real playable file — honoring the v1 design spec end-to-end.

> This is a **roadmap**, not a task plan. It fixes the sequence, the exit criteria, and the decisions.
> Each phase gets its own detailed TDD task plan (in the style of the two existing plans) when we start it.
> Checkboxes here track *phases*, not steps.

---

## What is actually real today

Verified by reading the code and running both suites (29 backend + 40 frontend, all passing) on 2026-09-22.

Real: the domain core, the non-destructive edit stack, word-boundary snapping, the HTTP shape, the whole Voltage UI, and the render *manifest* algorithm.

Mocked: every piece of media and every continuity number.

| Spec requirement | Today | Gap |
| --- | --- | --- |
| §5.1 ingest, extract audio, transcribe, detect face | canned 5-word transcript (`adapters/mock.py:5`) | no file, no audio, no face detection |
| §5.5 clone voice, synthesize matched prosody | `f"audio://{id}/{sha1}"` (`mock.py:25`) | no audio exists |
| §5.5 lip-sync affected frames | `f"frames://{id}/{sha1}"` (`mock.py:31`) | no frames exist |
| §6 four continuity checks | four hardcoded floats (`continuity/engine.py:21`) | **the stated differentiator is the least real part** |
| §6 auto-correct / auto-retry before preview | absent | `pipeline.py:14-16` is a straight line, no retry |
| §5.9 export composited video | segment list only (`render/renderer.py:18`) | no ffmpeg, no output file |
| §7 async job model | synchronous endpoints | will time out on real vendors |
| §7 versioning — every candidate retained | only approved edits stored | candidates are recomputed, not kept |
| §4 intent → edit plan | regex `to "X"` (`planner.py:5`) | no real intent parsing |
| §2 consent gate before generation | UI-only | backend does not enforce it |

---

## The central finding

**Every adapter returns an opaque `str`.** `VoiceAdapter.synthesize` → `str`, `LipSyncAdapter.sync` → `str`, and those strings flow through `EditCandidate`, `ApprovedEdit`, the renderer, the API, and into the frontend's types.

Real media cannot be a string. It needs a path, a duration, a codec, a sample rate — and it needs to survive a process restart. **Replacing that `str` with a real artifact type is the one change every other phase depends on**, and it touches all ten files that mention `audio_ref`/`frames_ref`.

So Phase 0 does the plumbing with *zero vendor spend*: real files, real storage, real ffmpeg — but the mocks generate silent WAVs and black frames. When ElevenLabs lands in Phase 4, it is a one-file swap, not a refactor. Doing this in the other order means rewriting the pipeline twice.

### Two blocking defects to fix on the way

1. **Approve re-runs the whole pipeline.** `api/main.py:93-98` already flags this in a comment. It is safe today only because the mocks are deterministic. ElevenLabs will not return identical audio twice, so approval would commit *different media than the user previewed* — and would double vendor cost on every approval. Fixed in Phase 0 by persisting candidates at preview and approving by `candidate_id`. This also delivers spec §7 versioning.
2. **Nothing enforces consent server-side.** Spec §2 calls it non-negotiable, and Phase 4 is the first phase that spends money cloning a real person's voice. Backend enforcement must land *before* Phase 4, not after.

---

## Phase sequence

Grouped into three milestones. Each milestone is independently useful — you can stop after any one and have something better than today.

### Milestone A — your video, your transcript (no generation yet)

- [x] **Phase 0 · Real artifacts & storage** *(no vendor cost)* — **done 2026-09-23**
  - ffmpeg 9.0.2 installed; `app/media/ffmpeg.py` wraps probe + generation with bit-exact flags
  - `MediaArtifact` (kind, sha256, path, duration, container) replaces the opaque `str` refs everywhere
  - `app/store/artifacts.py` — content-addressed store at `var/artifacts/<project>/<sha256>.<ext>`, atomic writes
  - Mocks encode **real decodable WAV/MP4** of the selected span, keyed to their inputs so distinct prompts yield distinct media
  - Candidates persisted at preview; `POST /edits` takes `candidate_id` (defect 1 fixed, §7 versioning delivered)
  - API returns content addresses, never filesystem paths
  - **Exit met:** 58 backend + 41 frontend tests pass offline; verified live that approving an *older* candidate commits its own media, that identical input deduplicates to one file, and that committed artifacts probe as real media.

- [x] **Phase 1 · Real source media** — **done 2026-09-23**
  - `POST /projects` takes a multipart upload; the file is spooled, probed, then stored immutably
  - `GET /projects/{id}/artifacts/{sha256}` serves any stored media with range requests; the address is validated as a bare hex digest, so it is not a traversal hole
  - `app/media/ingest.py` — `probe_source()` measures duration/size/fps/audio and refuses non-video, trackless and over-cap files with a reason fit to show the user
  - `Source.duration` now comes from ffprobe; `Source` carries its `MediaArtifact`
  - 180s cap enforced (spec §2); a refused upload allocates no project id and leaves nothing on disk
  - Frontend: file picker + "use the sample ad" (which uploads the bundled clip through the same path); player streams from the backend
  - Export manifest now resolves *every* span to an artifact — originals to the source — which Phase 7 composites from
  - **Exit met:** 84 backend + 46 frontend tests pass. Verified live in a real browser: uploaded the sample, backend logged `206 Partial Content` for the `<video>` range request, and the clip played in the editor. Rejections verified live for a text file, an audio-only file, and a genuine 200s video.

- [x] **Phase 2 · Real transcription (OpenAI)** — **done 2026-09-23**
  - `app/adapters/openai_whisper.py` — word-level timestamps via `verbose_json` + `timestamp_granularities[]=word`
  - `ffmpeg.extract_audio()` demuxes a 16 kHz mono WAV before the call
  - `app/config.py` — git-ignored `.env`, real env always wins; no key ⇒ falls back to the mock, so the app still runs offline and free
  - `GET /health` reports which adapters are live
  - Ingest now refuses silent video; the bundled sample was regenerated with spoken audio (`tools/gen-sample-clip.sh`) so the demo path still works
  - Tests replay a genuinely recorded whisper-1 response; the suite blanks `OPENAI_API_KEY` so it can never call the vendor
  - **Exit met:** 106 backend + 46 frontend tests pass. Verified live against the real API: the sample transcribed to `Get 20 off today only`, and an unrelated clip transcribed correctly to all 9 of its words — proving it is really listening. A mid-word drag (1.85–2.60) snapped to the true boundaries 1.64–2.82, then approved and exported.
  - **Open decision #2 resolved with evidence:** `whisper-1` is the only usable model — `gpt-4o-transcribe` rejects `verbose_json` ("use 'json' or 'text' instead"), so it cannot return word timings at all.
  - **Found:** Whisper emits an *empty* word where it strips a symbol (the `%` in `20%`), holding a real time slot. Empty words are dropped, leaving a gap rather than a blank timeline cell.

> **After Milestone A:** you load your own video and get your own real transcript with real word timings. Generation still mocked, but every byte that moves is real.

### Milestone B — real generation

- [x] **Phase 3 · Async job model** *(spec §7)* — **done 2026-09-23**
  - `app/jobs/store.py` — thread-safe job registry; jobs are immutable and terminal ones are frozen, so a worker's late progress callback cannot resurrect a finished job
  - `app/jobs/runner.py` — `ThreadPoolExecutor` + `with_retries()` with exponential backoff (spec §8); `sleep` is injectable so tests exercise backoff without waiting
  - `POST /edits/preview` now returns **202** with a job; `GET /jobs/{id}` polls. The pipeline reports real steps: *Synthesizing the new line* → *Matching mouth movement* → *Checking continuity*
  - `VendorError` base class marks failures as retryable; `TranscriptionError` extends it
  - Frontend polls with progress bar + step label, and a token guard so a newer prompt supersedes an older poll instead of racing it
  - **Exit met:** 130 backend + 53 frontend tests. Verified live: preview returned 202, the browser polled `GET /jobs/j2` to completion and rendered the candidate. A forced vendor failure retried 3× and surfaced a clean error with the pool still usable afterwards.
  - **Scoped deliberately:** ingest stays synchronous. Whisper is seconds; lip-sync is minutes, and that was the blocking case.
  - **Note:** intermediate progress is not observable live because the mock adapters finish in milliseconds — it is covered by tests, and becomes visible when vendors are real.

- [x] **Phase 3.5 · Backend consent enforcement** *(small; gates Phase 4)* — **done 2026-09-23**
  - `Consent` (granted_at) recorded per project: `POST /projects` takes a `consent` form field; `POST /projects/{id}/consent` grants it afterwards and is idempotent — re-confirming does not restamp the original time
  - `POST /edits/preview` returns **403** without consent, *before* a job is created — the last point before anything synthesizes the speaker's voice
  - Frontend `ConsentGate` is the first stage; the upload carries the user's answer to the backend
  - Closes the spec §2 non-negotiable before real voice cloning becomes possible.
  - **Exit met:** 142 backend + 56 frontend tests pass. Verified live against a running server: upload without consent → preview 403 → grant → re-grant keeps the same timestamp → preview 202, job succeeded; upload with consent is recorded directly; unknown project → 404.
  - **Not in scope:** revocation (withdrawing consent means deleting the project — arrives with persistence, Phase 9), and any verification that the attestation is true.

- [ ] **Phase 4 · Real voice (ElevenLabs)** — split in two: the account is on the free tier, which refuses voice cloning
  - [x] **4a · Stock voice** — **done 2026-09-23** (plan: `2026-09-23-phase-4a-real-voice-stock.md`)
    - `app/adapters/elevenlabs.py` — real TTS (`eleven_multilingual_v2`, premade voice Sarah) with the words either side of the selection as `previous_text`/`next_text` prosody context (free: only `text` is billed)
    - Output time-fitted to the selection with `atempo`, bounded to 0.8–1.25×; outside that the job fails once with "widen the selection", never retried
    - Cost guardrail: `app/budget.py` per-project character ceiling (`AVE_VOICE_BUDGET_CHARS`, default 2000), charged before every attempt including retries; unaffordable edits get **402** before any job exists. `AVE_DRY_RUN=1` forces every paid vendor (Whisper too) onto its mock
    - Only 429/5xx/network errors retry; bad key, exhausted quota, bad request fail once with their own message (`NonRetryableError`)
    - Candidates in a stock voice carry the warning *"Stock voice — this is not the speaker's voice yet."*; still approvable
    - `app/media/reference.py` extracts the speaker's speech outside the selection, ready for 4b
    - Candidate card plays the generated audio
    - **Exit met:** 215 backend + 58 frontend tests. Verified live: sample → `change "20% off" to "30% off"` → 0.96 s WAV for a 0.96 s selection, which Whisper transcribes as "30% off."; served as `206 audio/wav` through the frontend proxy; approved and exported. Budget of 5 → 402 with no spend; dry-run → full flow, no spend. Phase total ≈ 25 ElevenLabs characters.
    - **Not verified:** listening in a real browser — the Chrome extension was not connected. Intelligibility was checked by transcription, not by ear.
  - **4b · Speaker's own voice** → moved to the [Backlog](#backlog).

- **Phase 5 · Real lip-sync** → moved to the [Backlog](#backlog).

### Milestone C — the differentiator, and shipping it

- [ ] **Phase 6 · Real continuity engine** *(the moat — spec §6)*
  - [x] **6a · Prosody + audio integration, measured** — **done 2026-09-23** (plan: `2026-09-23-phase-6a-measured-continuity.md`)
    - `app/continuity/signals.py` (numpy): speech level, noise floor, autocorrelation pitch; `app/continuity/measured.py`: the engine
    - **Prosody** = pitch register vs. the speaker's words within 3 s either side (4 semitones = the 0.8 line). **Audio integration** = level (after correction) and clarity. Speaking rate is deliberately *not* scored: word counts on a ~1 s span are too coarse — the original line fails against its own context — and the fit to the original span already holds the rate.
    - **Auto-correct before preview:** level matched to the context (±12 dB max); the source's own room tone laid under studio-silent TTS when the room is audible. Room tone is taken only from genuinely quiet frames — Whisper's dropped `%` leaves speech in what looks like a gap, which was being mixed in as "room tone" until calibration caught it.
    - **Auto-retry:** a failing take is regenerated up to `AVE_MAX_REGENERATIONS` (default 2), each charged to the budget; best take kept; budget exhaustion or an unfittable retake keeps the best so far. Lip-sync runs once, on the winning audio.
    - Unmeasurable scores are `null`, shown as "not measured yet"; mock-engine numbers are tagged "simulated". Only measured scores gate approval.
    - **Calibrated** against a labelled set from the sample ad (`tests/continuity/test_calibration.py`): good = the speaker's own line (0.98) and the real ElevenLabs take (0.98); bad = ±6 semitones (0.73 / 0.67) and noise-drowned (integration 0.61). All separate at 0.8.
    - **Exit met:** 269 backend + 60 frontend tests. Live: Sarah → prosody 0.88, integration 1.00, passes; a deep male voice (George) → "Pitch is −8.7 semitones off", regenerated 2×, correctly fails.
    - Limits: the labelled set is one clip and synthetic bad cases — a start, not the spec §9 corpus. Measured only when the voice is real; offline/dry-run stays on the mock engine.
  - [ ] **6b** *(after 4b / 5 — see Backlog)* — voice identity and lip-sync accuracy
  - **voice identity** — speaker-embedding cosine similarity, generated vs. original (ECAPA-TDNN / resemblyzer)
  - **prosody & energy** — F0 contour, energy, and speaking-rate delta against neighboring speech
  - **audio integration** — LUFS/peak/noise-floor match to adjacent audio + micro-crossfades at seams (auto-applied per spec)
  - **lip-sync accuracy** — AV-sync confidence over the synced frames
  - **auto-correct / auto-retry loop before the user sees the candidate** — `pipeline.py` grows the retry the spec requires
  - Calibrate thresholds against a labeled good/bad set (spec §9); the current flat 0.8 is a placeholder
  - **Exit:** scores are measured, not asserted; a deliberately bad edit reliably fails.

- [x] **Phase 7 · Real ffmpeg render** — **done 2026-09-23** (plan: `2026-09-23-phase-7-real-render.md`)
  - `app/render/compose.py`: source audio decoded at 48 kHz in its own channel layout; each edited span replaced by its edit's (already level-matched) audio with 20 ms equal-power crossfades inside the span; muxed as H.264 (stream-copied when the source is H.264, re-encoded otherwise) + AAC, `+faststart`
  - **Video in edited spans is the original footage** — lip-sync is backlogged and the mock frames are a flat colour; `use_generated_frames` is the switch for Phase 5
  - Fixed: overlapping approvals now resolve last-write-wins (the manifest used to emit both); a partly-overwritten edit contributes the right part of its audio
  - Fixed on the way (found live): a take slightly *shorter* than the selection was refused; it is now slowed ≤0.8× and centred in silence, and an unfittable take is regenerated rather than failing the job
  - Export returns the render; the UI offers "Download MP4", cleared when a new edit is approved
  - **Exit met:** 287 backend + 62 frontend tests. Live: sample → "30% off" (prosody 0.97) → approve → export → a 2.300 s H.264/AAC MP4 that Whisper transcribes as **"Get 30% off today only."**; seam discontinuities 0.036/0.046 vs 0.198 for ordinary speech.

- [x] **Phase 8 · Real intent parsing** — **done 2026-09-26** (plan: `2026-09-26-phase-8-intent-and-placement.md`)
  - Claude (`claude-opus-5`, effort low, structured output) reads free-form requests with the selection's words and the chat so far (spec §5.8); non-speech requests get a plain chat reply. The regex survives as the offline `RuleInterpreter`.
  - **Asks instead of refusing:** a line that doesn't fit is placed as the user chooses — *start at the selection* or *stretch* (any amount, warned outside 0.8–1.25×); over a speech-free selection, *replace*, *layer* or *concatenate* (frame held while the line plays; the video grows). The take that prompted the question is reused, so asking costs nothing.
  - **Exit met:** 330 backend + 74 frontend tests at the time. Live on a speech-free portrait clip: "Add the line "Thirsty Thirsty"" → mix question → fit question → layered at 2.1–3.5 s with the music intact; "after this bit" read as concatenate → export 8.00 → 9.11 s, frame held; "make the background white" → a reply.
  - **Follow-ups from hands-on testing (same day):** player unmuted and wired to its slider/playhead; approving renders at once and plays the edit (Edited / Original toggle); "Approve anyway" for trials (explicit `override`, recorded on the edit); Whisper's zero-length words no longer crash the continuity check. 333 backend + 85 frontend tests.

- [x] **Phase 9 · Durability & hardening** — **done 2026-09-26** (plan: `2026-09-26-phase-9-10-durability-and-editing.md`)
  - **9a** SQLite (`var/ave.db`): projects, candidates, edits and the chat survive restarts; ids never reused; project list, reopen, delete (= consent withdrawal); the server keeps the chat. Every project has an owner, checked on every route (another's project is a 404).
  - **9b** Usage ledger: every paid call recorded with an estimated USD (Whisper minutes, ElevenLabs characters, Claude tokens); the voice budget reads it; `AVE_PROJECT_BUDGET_USD` caps new paid work per project; `GET /projects/{id}/usage`; spend shown in the editor.
  - **9c** Auth designed, not built: OIDC sign-in (Google first) → session → `current_owner()`; then a login page, CSRF on writes, per-user quotas.
  - **Exit met:** 346 backend + 94 frontend tests. Live: a project and its chat survive a restart; a real clip's spend recorded ($0.0008 Whisper, $0.0067 Claude).

- [x] **Phase 10 · Editing by transcript, voices, timeline** — **done 2026-09-26** (same plan)
  - **Statements:** Whisper is asked for segments as well as words; they are the transcript's statements (punctuated). Older projects group words at pauses. The transcript panel edits a statement in place → an edit of its span with the text given directly (no Claude call), through the usual question / candidate / approve flow.
  - **Voice picker:** `GET /voices` (ElevenLabs premade, 21 on this account); the chosen voice is the plan's `voice_profile_id`.
  - **Timeline:** zoom (−/+/Fit), horizontal scroll, follows the playhead; clips over 15 s open at a readable 110 px/s.
  - **Exit met:** 354 backend + 108 frontend tests. Live on the 49 s Bhaji Cam clip: 20 statements; the same statement rewritten in Sarah and in Brian.
  - **Found live — the case for multi-voice:** that clip has two speakers, and continuity compares the new line with *everyone* speaking nearby: Sarah measured +5.2 semitones, Brian −4.8 — the reference is a blend. Speaker labels (diarization) would let continuity compare against the same speaker only, and give each speaker a voice.

- [x] **Phase 11 · Multiple voices** — **done 2026-09-26** (plan: `2026-09-26-phase-11-multiple-voices.md`)
  - **Diarization:** spiked OpenAI `gpt-4o-transcribe-diarize` vs ElevenLabs Scribe on the two-speaker clip — both exact; OpenAI chosen alongside Whisper to keep the free ElevenLabs credits for speech (Scribe is the single-call option if the plan is upgraded). Words and statements carry a speaker; diarization failing never fails an upload; older projects detect on demand.
  - **A voice per speaker:** rename speakers, pick each one's voice; a line in one speaker's words uses theirs, else the chat's voice.
  - **Continuity per speaker:** the pitch/level reference is the edited speaker's own words.
  - **Exit met:** 368 backend + 113 frontend tests. Live on the Bhaji Cam clip: speakers A (customer) / B (shopkeeper) detected; the customer's line, blended-reference before → speaker-only now: Sarah 0.74 → 0.83, Brian 0.76 → **0.96**, both passing.

---

## Backlog

Parked 2026-09-23. Each is blocked on vendor access, not on code; nothing in the codebase is waiting half-built for them. Pick one up by writing its phase plan, as for every other phase.

- [ ] **Phase 4b · Speaker's own voice** — *unblocked by:* an ElevenLabs plan with instant voice cloning (the current key is free tier: `can_use_instant_voice_cloning: false`).
  - Clone from `app/media/reference.py`'s `extract_reference_audio` (built in 4a); pin its minimum length against the vendor (placeholder 10 s; ElevenLabs asks for ~1 min)
  - The adapter reports `identity = "clone"`, which drops the stock-voice warning; voice-clone type is open decision 3
  - **Exit:** the edited span is genuinely the speaker's voice saying the new words.
- [ ] **Phase 5 · Real lip-sync** — *unblocked by:* a lip-sync vendor key (open decision 1).
  - Vendor spike first: same 10-second clip through each candidate, compare output and price
  - Face detection on the source (the missing half of spec §5.1)
  - Vendor adapter → real frames artifact for the affected range; settle open decision 4
  - **Exit:** mouth motion matches the new audio.

**Impact of parking them on Milestone C:** Phase 6's voice-identity and lip-sync checks are only meaningful once 4b and 5 land. Its prosody and audio-integration checks, and Phases 7–9, do not depend on either.

---

## Cross-cutting rules

- **The test suite never calls a vendor.** Recorded cassettes only (spec §9). Live-vendor tests are a separate opt-in target.
- **Secrets never land in git.** `.env` + `.gitignore`, keys read at startup, absent key = clear error not a crash.
- **Cost guardrails from Phase 4 onward.** Dry-run mode and a per-project budget ceiling; an agentic retry loop that silently re-calls a paid vendor is a bill waiting to happen.
- **Mocks stay working forever.** Every real adapter keeps its mock sibling, selected by config, so the whole thing still runs offline with no keys.
- **One phase, one plan, one review.** Each phase gets its own TDD task plan before implementation starts.

---

## Open decisions

1. **Lip-sync vendor** — you said you can get a key but not which. Candidates: Sync.so, Hedra, Runway. They differ materially in quality, latency, cost, and whether they accept an arbitrary source clip. **Recommend a spike at the start of Phase 5**: same 10-second test clip through each, compare output and price, then pick. Deciding now on vibes would be guessing.
2. ~~**Transcription model**~~ — **resolved 2026-09-23.** `whisper-1`, and it is not a preference: it is the only OpenAI transcription model that accepts `verbose_json`, which is what carries word timestamps. `gpt-4o-transcribe` refuses that format outright. Tested against the live API.
3. **Voice clone type** — ElevenLabs instant clone (fast, cheap, good) vs. professional (better identity, needs much more audio, slower). Instant for v1; revisit if Phase 6 voice-identity scores come in low.
4. **Where lip-sync frames live** — full re-rendered segment vs. mouth-region composite over original frames. Vendor choice largely forces this; settle at Phase 5.

---

## Environment gaps found 2026-09-22

- ~~ffmpeg / ffprobe: not installed~~ — **resolved**, ffmpeg 9.0.2 installed via Homebrew.
- Backend venv is Python 3.11.15 (system `python3` is 3.9.6 — always use `backend/.venv/bin/python`).
- Node v22.20.0, frontend deps installed, Vite 8 binds `localhost` only (not `127.0.0.1`).
- OpenAI and ElevenLabs keys configured in `backend/.env` (git-ignored, `0600`). ElevenLabs account is **free tier** — no cloning (Phase 4b). A lip-sync vendor is still needed for Phase 5.

---

## Recommended starting point

**Phase 0**, and it is not a close call. It costs nothing, needs no API keys, fixes the two blocking defects, and converts the adapter seam from decorative to load-bearing. Every later phase gets cheaper and safer because of it.
