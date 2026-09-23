# Real Pipeline — Phased Roadmap

**Date:** 2026-09-22
**Status:** In progress — Phases 0–3.5 done; next is Phase 4
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

- [ ] **Phase 4 · Real voice (ElevenLabs)**
  - Extract the speaker's clean reference audio from the source; voice clone; TTS `new_text` → real WAV artifact
  - Prosody conditioning from the span being replaced
  - Cost guardrail: per-project budget cap + dry-run mode (every call now costs money)
  - **Exit:** the edited span is genuinely the speaker's voice saying the new words.

- [ ] **Phase 5 · Real lip-sync** *(vendor TBD — see open decisions)*
  - Face detection on the source (the missing half of spec §5.1)
  - Vendor adapter → real frames artifact for the affected range
  - **Exit:** mouth motion matches the new audio.

### Milestone C — the differentiator, and shipping it

- [ ] **Phase 6 · Real continuity engine** *(the moat — spec §6)*
  - **voice identity** — speaker-embedding cosine similarity, generated vs. original (ECAPA-TDNN / resemblyzer)
  - **prosody & energy** — F0 contour, energy, and speaking-rate delta against neighboring speech
  - **audio integration** — LUFS/peak/noise-floor match to adjacent audio + micro-crossfades at seams (auto-applied per spec)
  - **lip-sync accuracy** — AV-sync confidence over the synced frames
  - **auto-correct / auto-retry loop before the user sees the candidate** — `pipeline.py` grows the retry the spec requires
  - Calibrate thresholds against a labeled good/bad set (spec §9); the current flat 0.8 is a placeholder
  - **Exit:** scores are measured, not asserted; a deliberately bad edit reliably fails.

- [ ] **Phase 7 · Real ffmpeg render**
  - Manifest → actual composited MP4: concat, audio crossfades at splices, loudness normalization across boundaries
  - Downloadable export from the UI
  - **Exit:** you download a video file that plays and sounds seamless.

- [ ] **Phase 8 · Real intent parsing**
  - Replace the regex planner with transcript-aware LLM intent parsing — handles "make it sound more urgent", "drop the price mention", not just `change "X" to "Y"`
  - Preserve chat context across the iterate loop (spec §5.8)
  - Model selection pinned at implementation time against current model docs.

- [ ] **Phase 9 · Durability & hardening**
  - SQLite persistence replacing the in-memory store; multi-project; auth; cost tracking and quotas.

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
- OpenAI key configured in `backend/.env` (git-ignored, `0600`). ElevenLabs and a lip-sync vendor still needed for Phases 4–5.

---

## Recommended starting point

**Phase 0**, and it is not a close call. It costs nothing, needs no API keys, fixes the two blocking defects, and converts the adapter seam from decorative to load-bearing. Every later phase gets cheaper and safer because of it.
