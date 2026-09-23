# Agentic Video Editor

Select a moment in an existing video, describe in plain English how the **spoken message** should change, and get back a re-voiced and lip-synced version that looks and sounds as if it were shot that way — iterating by chat until it's right.

The differentiator is **continuity**: splicing an AI clip into footage is easy; making it *belong* — matching voice identity, prosody, audio levels, and mouth motion — is the hard part. This repo is the agentic orchestration layer plus the continuity engine, built over swappable third-party generation models.

**Current state:** upload your own video and edit what is actually said in it. The backend ingests a real file, measures it with ffprobe, stores it immutably, serves it back with range requests, and **transcribes it for real** with OpenAI `whisper-1` — so the timeline shows your words at your timings. Generation runs as a **background job** the UI polls for progress, with retries on vendor failure. The new line is **spoken for real** by ElevenLabs, fitted to the selection's length, and playable on the candidate card — but in a *stock* voice, not the speaker's (the account's free tier cannot clone). Lip-sync is still mocked (a flat-colour MP4). Prosody and audio integration are **measured** from the audio, levels and room tone are corrected automatically, and a take that fails is regenerated within a cap. Every paid call is metered against a per-project budget, and `AVE_DRY_RUN=1` switches all vendors off. The *interaction*, *source media*, *transcript*, *pipeline* and *voice* are real; the *speaker's identity* and the *mouth* are not yet.

- `backend/` — Python 3.11 + FastAPI. Domain core, adapters, continuity engine, orchestrator, background job runner, in-memory project store, content-addressed artifact store, ffmpeg wrapper + ingest validation, renderer, HTTP API.
- `frontend/` — React 19 + Vite + TypeScript. The Voltage editor, calling the backend through a dev-server proxy.
- `docs/superpowers/specs/` — product and front-end design docs.
- `docs/superpowers/plans/` — the implementation plans each phase was built from, plus `2026-09-22-real-pipeline-roadmap.md`, the phased route from mocks to a real v1. The `- [ ]` checkboxes in the older plans were never ticked during execution; treat the code and tests as the source of truth, not the boxes.

---

## Running it

**Prerequisites**

ffmpeg (with ffprobe) must be on `PATH` — the backend encodes, probes and demuxes real media.

```sh
brew install ffmpeg
```

Transcription calls OpenAI and speech calls ElevenLabs. Put keys in `backend/.env` (git-ignored):

```sh
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=sk_...
# optional
ELEVENLABS_MODEL=eleven_multilingual_v2   # eleven_flash_v2_5 bills half
ELEVENLABS_VOICE_ID=EXAVITQu4vr4xnSDxMaL  # premade "Sarah"
AVE_VOICE_BUDGET_CHARS=2000               # per-project ElevenLabs ceiling
AVE_MAX_REGENERATIONS=2                   # extra paid takes when continuity fails
AVE_DRY_RUN=1                             # never call a paid vendor
```

Without a key the app still runs: each missing vendor falls back to its
deterministic mock, offline and free, and `AVE_DRY_RUN=1` forces every one onto
its mock whatever keys exist. `GET /health` reports which adapters are live.

Two terminals. The backend must be up first — the front end proxies to it.

### 1. Backend (port 8000)

```sh
cd backend
python3.11 -m venv .venv              # first time only; 3.11+ is required
.venv/bin/pip install -e '.[dev]'     # first time only
.venv/bin/uvicorn app.api.main:app --reload
```

The checked-out `.venv` here was created by [uv](https://docs.astral.sh/uv/) and has no
`pip`. To add a dependency to it: `VIRTUAL_ENV=$PWD/.venv uv pip install <pkg>`.

Interactive API docs land at http://127.0.0.1:8000/docs.

### 2. Front end (port 5173)

```sh
cd frontend
npm install                           # first time only
npm run dev
```

Open the URL Vite prints. Vite proxies `/api/*` → `http://127.0.0.1:8000` with the `/api` prefix stripped, so the client always calls same-origin and there are no CORS concerns.

### The journey

Consent gate → **Choose a video** (or *use the sample ad*) → drag a selection on the timeline (it snaps to word boundaries) → prompt the agent, e.g. `change "20% off" to "30% off"` → review the continuity scorecard → **Approve** → **Export**.

Your own footage works — up to 3 minutes, and it must have an audio track. The player streams it back from the backend, and the timeline shows the real words Whisper heard, at their real timings, so a drag snaps to what was actually said.

To see the continuity *failure* path, the voice profile has to be `unknown`, which forces scores below the 0.8 pass threshold and makes approval `422`. There is no UI control for this today — change `VOICE` in `frontend/src/App.tsx` to `'unknown'`, or hit `/edits/preview` directly with curl.

---

## Tests

Both suites are offline and deterministic. No running server required.

```sh
cd backend && .venv/bin/python -m pytest      # 269 tests
cd frontend && npm test                        # 60 tests, 11 files
```

Backend tests write their media to a temp dir, never to `backend/var/`. Tests that
encode media skip themselves if ffmpeg is absent. **No test ever calls a vendor:**
the suite blanks `OPENAI_API_KEY` and `ELEVENLABS_API_KEY`, so it always runs on
the mocks, and the vendor tests replay responses genuinely recorded from the real
APIs: `tests/fixtures/whisper-verbose-json.json` and `tests/fixtures/elevenlabs-tts.pcm`.

---

## The API

Generation is asynchronous (preview returns a job to poll); everything else answers directly:

| Endpoint | Method | Body | Does |
| --- | --- | --- | --- |
| `/health` | GET | — | which adapters are real in this process |
| `/projects` | POST | `multipart` `file=` | uploads a video; probes it; transcribes it; → `project_id`, `duration`, source `media`, word-level `transcript`. `422` with a reason if it is not a readable video, has no video track, has no audio track, or exceeds the 180s cap; `502` if transcription fails. |
| `/projects/{id}/consent` | POST | — | records consent for a project uploaded without it; idempotent, the first timestamp stands |
| `/projects/{id}/artifacts/{sha256}` | GET | — | serves stored media by content address, with range requests |
| `/projects/{id}/edits/preview` | POST | `{prompt, start, end, voice_profile_id}` | **`202`** — starts generation and returns a job to poll. Does not block. `403` without consent; `402` if the project's voice budget cannot cover the edit (no job is created). |
| `/jobs/{job_id}` | GET | — | job state: `status`, `progress`, `step`, `attempts`. On success `result` is the candidate (`candidate_id`, plan, `audio`/`frames` artifacts, continuity report), which is retained server-side. |
| `/projects/{id}/edits` | POST | `{candidate_id}` | approves that exact candidate; `404` if unknown, `422` if continuity failed |
| `/projects/{id}/export` | POST | — | ordered segment manifest of `original` / `edited` spans, each carrying the artifact it resolves to |

Artifacts are returned as content addresses (`sha256`, `duration`, `container`) — never
filesystem paths. Approval commits the media the preview produced rather than
regenerating it, which real vendors would not reproduce byte-for-byte.

Example:

```sh
curl -X POST http://127.0.0.1:8000/projects \
  -H 'content-type: application/json' \
  -d '{"filename":"sample-ad.mp4","duration":2.3}'
```

---

## Seams you should know about

These are deliberate and documented, not oversights:

- **Whisper drops symbols but keeps their time slot.** `"20%"` comes back as the word `20` followed by an *empty* word spanning the `%`. We drop empty words rather than render blank timeline cells, which leaves a small gap between `20` and `off`. Snapping handles gaps fine — real pauses make them anyway — but the gap is visible on the timeline.
- **Only `whisper-1` can do this.** It is the one OpenAI transcription model that accepts `response_format=verbose_json`, which is what carries word timestamps; the `gpt-4o-transcribe` family rejects verbose_json outright. Verified against the live API, not assumed.
- **Silent video is refused.** A dialogue editor has nothing to do with it — no speech to transcribe, no voice to clone, no line to change.
- **The sample clip is a generated placeholder.** `frontend/public/sample-ad.mp4` is a 2.3s H.264 title card whose soundtrack is macOS `say` reading the line on the card, so it genuinely transcribes. The "use the sample ad" button fetches it and uploads it through the same path as any other file. To regenerate it (macOS; needs ffmpeg):

  ```sh
  tools/gen-sample-clip.sh frontend/public/sample-ad.mp4
  ```

  The voice depends on the machine's TTS, so the output is not byte-stable across
  macOS versions. It is a placeholder, not a fixture.
- **The generated media is real but meaningless.** The mock voice adapter encodes a sine tone; the mock lip-sync adapter encodes a flat colour. Both are real, decodable files of the right length, keyed to their inputs so different prompts yield different media — they just are not speech or faces. Real vendors slot in behind the same adapter interfaces.
- **The voice is real but it is not the speaker.** ElevenLabs free tier refuses voice cloning, so the new line is spoken by a premade voice. Every such candidate carries the warning *"Stock voice — this is not the speaker's voice yet."* Phase 4b swaps in a clone once the plan is upgraded; the reference-audio extraction it needs is already built.
- **Speech is time-fitted, within limits.** The generated line is sped up or slowed to exactly fill the selection, but only within 0.8–1.25×. Beyond that the job fails once with a message to widen or narrow the selection — ElevenLabs' output length varies per call, so a borderline edit can land either side. Note the paid call has already been made and charged by then.
- **The candidate card plays audio only.** The generated frames are still a flat colour until lip-sync is real (Phase 5).
- **Half the continuity scorecard is measured.** With a real voice, prosody (pitch register against the surrounding speech) and audio integration (level and clarity) are measured from the audio, after automatic level and room-tone correction; a failing take is regenerated up to `AVE_MAX_REGENERATIONS` times (default 2 — each one a paid call, charged to the budget). Voice identity and lip-sync read "not measured yet" until Phases 4b and 5. Offline and in dry-run the scores are the mock engine's, tagged *simulated*. Thresholds were calibrated on one clip — expect to tune them on real footage.
- **Consent is a checkbox attestation, not verification.** The backend records it per project (at upload, or later via `POST /projects/{id}/consent`) and refuses generation with a 403 without it — but it trusts the uploader's word. There is no way to withdraw it yet: by design, withdrawing means deleting the project, and there is no delete endpoint until persistence (Phase 9). A server restart is the only reset.
- **Project metadata is in-memory; artifacts are on disk.** Restarting the server loses every project but leaves its media in `backend/var/artifacts/`, orphaned. A failed transcription orphans an upload the same way. Persistence (Phase 9) closes the mismatch; until then `rm -rf backend/var` is a safe reset.
- **Ingest is still synchronous.** Generation runs as a background job, but upload+transcription does not: a 3-minute upload blocks the request for as long as Whisper takes. Whisper is seconds, so this is liveable; lip-sync would not have been, which is why generation went first.
- **The voice budget is in memory.** It is per project and resets when the server restarts, like everything else until Phase 9. It meters ElevenLabs only; Whisper is not metered (dry-run does switch it off).
- **Jobs live in memory and are never evicted.** They accumulate for the life of the process and vanish on restart, along with everything else.

## Not built yet

Deferred by design: the speaker's own cloned voice (Phase 4b) and real lip-sync (Phase 5) — both in the roadmap's backlog, blocked on vendor access — plus real continuity measurement, real ffmpeg compositing on export, multi-project persistence, and auth. See `docs/superpowers/plans/2026-09-22-real-pipeline-roadmap.md` for the phased route through them. Product-level, v1 is dialogue changes only — visual detail swap (Phase 2), pacing/filler edits, multi-speaker crosstalk, and non-English are all out of scope.
