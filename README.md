# Agentic Video Editor

Select a moment in an existing video, describe in plain English how the **spoken message** should change, and get back a re-voiced and lip-synced version that looks and sounds as if it were shot that way — iterating by chat until it's right.

The differentiator is **continuity**: splicing an AI clip into footage is easy; making it *belong* — matching voice identity, prosody, audio levels, and mouth motion — is the hard part. This repo is the agentic orchestration layer plus the continuity engine, built over swappable third-party generation models.

**Current state:** upload your own video and Voltage, having read every line, asks what it should say. **The agent plans across the whole video:** Claude reads the goal with every line and who says it, tells you what it noticed as it read, asks at most one thing it genuinely needs to know (with its own guess, so you can just say "go"), and proposes the changes that carry the goal out, each with a reason in plain words, plus any it would suggest. Under **Check with me**, the default, the plan waits: each change ticked, its wording editable, with a cost and time estimate, and nothing is voiced or charged until **Go ahead**. Under **Just do it** it runs straight away. One job voices the plan line by line and narrates each take as it goes ("Take 1: pitch is 6 semitones off. Trying again"); when a line runs long with nowhere to go, Voltage recommends its own fix first, a shorter wording, ahead of speeding up or overlapping. **Review** shows every change before and after, lets you hear each seam, and **Ship it** renders the video; a receipt of what Voltage did records it all with the plan's cost. The look is a warm dark room: cream text, one amber accent, a serif for headings, and Voltage present as a soft glowing orb. **The line is the unit** (UX-1): every line in the transcript carries its own state and actions — change the words, change the delivery, add a line after, remove, play original — and its editor, take, verdict, Keep / Another take and Undo all live in the row. An added line plays **over the picture** by default; the picture is held only when there is no room, and the line says so. A removed line leaves the room's own sound in its place. **Any take or kept line can be moved anywhere on the timeline**: "Starts at 0:04.96 · Move" drags a block of its length along the monitor's bar, or takes a typed time, and nothing is voiced again; an added line can be given a start time of its own instead of following its line. Underneath, the editor is built around the transcript. The **transcript is a document**: one row per line with its time and speaker; an approved change shows **inline as tracked changes** (old words struck, new ones highlighted) with **Revert** beside it; a line being worked on carries a status (Working, Ready, Needs you). **Click any line to edit it yourself**: new wording, the voice, what to do if the line runs long, or **Ask Voltage for wording** (Claude suggests a rewrite you can edit before previewing). A longer line **runs into the pause after it without asking** when there is room; the choice is remembered per project, with "Ask me each time" to undo it. The conversation with Voltage sits in a panel on the right.

Underneath that: The backend ingests a real file, measures it with ffprobe, stores it immutably, serves it back with range requests, and **transcribes it for real** with OpenAI `whisper-1` — so the timeline shows your words at your timings; click, shift-click or drag across them to select; the timeline zooms and scrolls for longer clips. The **transcript panel** lists every statement (Whisper's sentences, with punctuation): click a time to jump there, click the words to rewrite them and preview the change. A **voice picker** chooses which ElevenLabs premade voice speaks new lines. **Speakers** are detected (OpenAI diarization alongside Whisper) and labelled on the transcript; each can be renamed and given a voice, a line in one speaker's words is spoken in theirs, and continuity is measured against that speaker's own speech only. Requests are **free-form**: Claude reads what you type ("add the line "Thirsty!" over the music", "make it 30%"), answers in the chat when a request isn't about speech, and when a line doesn't fit the selection — or the selection holds no speech — the editor **asks** how to place it (start at the selection or stretch it; replace, layer over, or add after the sound there) rather than refusing. Generation runs as a **background job** the UI polls for progress, with retries on vendor failure. The new line is **spoken for real** by ElevenLabs, fitted to the selection's length, and playable on the candidate card — but in a *stock* voice, not the speaker's (the account's free tier cannot clone). Approving renders straight away and the player switches to the edited version (an Edited / Original toggle compares them); a candidate that fails continuity can still be approved on purpose ("Approve anyway") for trials. Export renders a real MP4 with the new line spliced in — over the original video, since lip-sync is still mocked. Prosody and audio integration are **measured** from the audio, levels and room tone are corrected automatically, and a take that fails continuity is regenerated within a cap. Every paid call is metered against a per-project budget, and `AVE_DRY_RUN=1` switches all vendors off. The *interaction*, *source media*, *transcript*, *pipeline* and *voice* are real; the *speaker's identity* and the *mouth* are not yet.

- `backend/` — Python 3.11 + FastAPI. Domain core, adapters, continuity engine, orchestrator, background job runner, SQLite project store (projects, edits, chat, spend), content-addressed artifact store, ffmpeg wrapper + ingest validation, renderer, HTTP API.
- `frontend/` — React 19 + Vite + TypeScript. The Voltage editor, calling the backend through a dev-server proxy. Its design — the agentic editor: transcript as a document with inline tracked changes, hands-on editing in place, the Voltage panel — follows the mocks in `docs/superpowers/plans/2026-09-28-phase-12-13-agentic-editor.md` (the earlier script-page design, `docs/superpowers/specs/2026-09-26-editor-ui-redesign.md`, is superseded). A project's id is in the URL (`#p3`), so a reload reopens it.
- `docs/superpowers/specs/` — product and front-end design docs.
- `docs/superpowers/plans/` — the implementation plans each phase was built from, plus `2026-09-22-real-pipeline-roadmap.md`, the phased route from mocks to a real v1. The `- [ ]` checkboxes in the older plans were never ticked during execution; treat the code and tests as the source of truth, not the boxes.

---

## Running it

**Prerequisites**

ffmpeg (with ffprobe) must be on `PATH` — the backend encodes, probes and demuxes real media.

```sh
brew install ffmpeg
```

Transcription calls OpenAI, speech calls ElevenLabs, and Claude reads free-form
edit requests. Put keys in `backend/.env` (git-ignored):

```sh
OPENAI_API_KEY=sk-...
ELEVENLABS_API_KEY=sk_...
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_WORKSPACE_ID=wrkspc_...         # needed when the key is not workspace-scoped
# optional
ELEVENLABS_MODEL=eleven_multilingual_v2   # eleven_flash_v2_5 bills half
ELEVENLABS_VOICE_ID=EXAVITQu4vr4xnSDxMaL  # premade "Sarah"
AVE_VOICE_BUDGET_CHARS=2000               # per-project ElevenLabs ceiling
AVE_MAX_REGENERATIONS=2                   # extra paid takes when continuity fails
AVE_PROJECT_BUDGET_USD=2.00               # per-project ceiling on estimated spend, all vendors
AVE_ELEVENLABS_USD_PER_1K=0.30            # rate for ElevenLabs cost estimates (plan-dependent)
AVE_TAKES_PER_LINE=3                      # takes voiced when the first misses its slot; the nearest is kept
AVE_FIT_TOLERANCE=0.05                    # how far off the slot counts as a miss
AVE_DRY_RUN=1                             # never call a paid vendor
```

Without a key the app still runs: each missing vendor falls back to its
deterministic mock, offline and free, and `AVE_DRY_RUN=1` forces every one onto
its mock whatever keys exist. `GET /health` reports which adapters are live.

**Keys on another machine.** The keys travel with the repo *encrypted*: `backend/.env.enc` is `backend/.env` locked with a passphrase you choose (AES-256, PBKDF2), and only the ciphertext is committed — `.env` itself is git-ignored. The passphrase is the one thing you keep outside git (a password manager, or the server's own secret store).

```sh
tools/env-lock.sh                            # here, after changing a key: prompts for the passphrase, writes backend/.env.enc
AVE_ENV_PASSPHRASE='…' tools/env-unlock.sh   # on a fresh clone: writes backend/.env (mode 600)
```

Anyone with the repo but not the passphrase has nothing. Rotate a key by editing `backend/.env`, running `tools/env-lock.sh` again and committing the new `.env.enc`.

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

Consent gate → **Choose a video** (or *use the sample ad*) → drag a selection on the timeline (it snaps to word boundaries) → prompt the agent, e.g. `change "20% off" to "30% off"` → review the continuity scorecard and listen to the new line → **Approve** → **Export** → **Download MP4**.

Your own footage works — up to 3 minutes, and it must have an audio track. The player streams it back from the backend, and the timeline shows the real words Whisper heard, at their real timings, so a drag snaps to what was actually said.

To see the continuity *failure* path, the voice profile has to be `unknown`, which forces scores below the 0.8 pass threshold and makes approval `422`. There is no UI control for this today — change `VOICE` in `frontend/src/App.tsx` to `'unknown'`, or hit `/edits/preview` directly with curl.

---

## Tests

Both suites are offline and deterministic. No running server required.

```sh
cd backend && .venv/bin/python -m pytest      # 469 tests
cd frontend && npm test                        # 173 tests, 19 files
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
| `/projects/{id}/speakers` | GET | — | the project's speakers: `label`, display `name`, `voice_id` (null = the chat's voice) |
| `/projects/{id}/speakers/{label}` | PUT | `{name?, voice_id?, clear_voice?}` | renames a speaker or sets their voice |
| `/projects/{id}/speakers/detect` | POST | — | detects speakers for a project transcribed before they were (paid; counts toward spend) |
| `/voices` | GET | — | the voices a new line can be spoken in, and the `default`; pass one's `voice_id` as `voice_profile_id` |
| `/projects` | GET | — | the caller's projects, newest first (`project_id`, `filename`, `duration`, `created_at`, `edits`) |
| `/projects/{id}` | GET | — | reopens a project: its upload and transcript, approved `edits` (each with `reverted`), the chat `messages`, and its `settings` |
| `/projects/{id}/settings` | PUT | `{long_lines?, autonomy?}` | `long_lines`: how a line that runs long is placed — `pause` (run into the pause after it when there is room, the default), `shorten` (ask Claude for a shorter wording and voice that, without asking you), `stretch`, or `ask`. `autonomy`: `ask` (a plan waits for Run, the default) or `draft` (it runs at once) |
| `/projects/{id}/plans` | POST | `{goal, mode?}` | the agent plans edits across the whole video: → the plan (`summary`, `items` each with the line, its new words, `mix`, `reason`, `kind` planned / suggestion, `status`), an `estimate` (voice characters, USD, seconds) and a `log`. Under `draft` it also returns the `job_id` already voicing it. Planning is a Claude call, metered as `planning` |
| `/projects/{id}/plans/{plan_id}` | GET | — | the plan with its `findings`, open `question`, `spend_usd`, and each item's status, `progress` (what is happening to it now), question, take (`candidate`) and `edit_id` |
| `/projects/{id}/plans/{plan_id}/clarify` | POST | `{answer?}` | answers the planner's one question (empty = its guess); it plans again with the answer. `409` when there is no open question. A plan with an open question is `clarifying` and cannot run |
| `/projects/{id}/plans/{plan_id}/items/{item_id}` | PUT | `{enabled?, new_text?, include?}` | untick or reword an item; `include` adds a suggestion to the plan (or leaves it) |
| `/projects/{id}/plans/{plan_id}/run` | POST | `{items?}` | **`202`** — one job voicing the ticked items; each goes `working` → `ready` / `needs-you` / `failed`. A line that runs long with nowhere to go becomes `needs-you` with the agent's own fix first: a shorter wording from Claude (metered as `wording`), then speed up / run past |
| `/projects/{id}/plans/{plan_id}/items/{item_id}/answer` | POST | `{text?, fit?, mix?}` | **`202`** — answers a `needs-you` item and voices it again |
| `/projects/{id}/plans/{plan_id}/items/{item_id}/redo` | POST | — | **`202`** — another take of one item |
| `/projects/{id}/plans/{plan_id}/approve` | POST | `{items?, override?}` | approves every `ready` item and renders → `approved`, `skipped` (a take that failed continuity, unless `override`), the `export` manifest and the plan |
| `/projects/{id}/edits/{edit_id}/revert` | POST | — | undoes an approved edit: it is kept and marked `reverted`, the render skips it, the transcript shows the line as shot |
| `/projects/{id}/candidates/{candidate_id}/move` | POST | `{start, mix?}` | the same take placed somewhere else on the timeline — nothing is voiced again; → a new candidate covering its own length from `start` (a held line's insert point moves) |
| `/projects/{id}/edits/{edit_id}/move` | POST | `{start, mix?}` | a kept line placed somewhere else: the old edit is reverted and the same take kept at the new place, in one step |
| `/projects/{id}/lines/remove` | POST | `{start, end}` | takes the line out: its words go, the room's own quiet (from the recording's gaps) fills the span, the picture is untouched. Approved at once as an edit with mix `remove`; undone with revert. `422` when nothing is said there |
| `/projects/{id}/lines/reword` | POST | `{start, end, draft?, instruction?}` | asks Claude for a new wording of the line in that span (the draft so far, if any, is improved); → `{text, selection}`. Nothing is spoken. `503` without Claude, `422` if it cannot answer |
| `/projects/{id}` | DELETE | — | **`204`** — deletes the project and all its media; also how consent is withdrawn |
| `/projects/{id}/usage` | GET | — | estimated spend: `spent_usd` / `ceiling_usd`, ElevenLabs characters against their budget, and per-vendor `lines` |
| `/projects/{id}/consent` | POST | — | records consent for a project uploaded without it; idempotent, the first timestamp stands |
| `/projects/{id}/artifacts/{sha256}` | GET | — | serves stored media by content address, with range requests |
| `/projects/{id}/edits/preview` | POST | `{prompt, start, end, voice_profile_id, text?, fit?, mix?, on_long?, delivery?}` | **`202`** — starts a job to poll. Does not block. `403` without consent. The request is read (Claude, or the offline quoted-text rule) inside the job; the job's `result` is tagged by `type`: a `candidate`; a `reply` (a request the editor can't do, or a clarifying question); or a `question` with `options` — how to mix the line with the sound (`replace` / `layer` / `concatenate`), or how to fit it (`start` / `stretch`). `mix: over` adds the line *after* the selection, over the picture that follows (layered on the pause there, or the picture held when there is no room). `delivery` is how it is said: `warmer`, `more excited`, `calmer`, `slower`, `firmer`. Answer by re-sending with `text` and the chosen `fit` / `mix`. A line that runs *long* is placed without asking when the project's `long_lines` setting (or this request's `on_long`) says how: into the pause after the selection if the pause can hold the overrun, or sped up; only when it cannot does the fit question come back. A job the project's voice budget cannot cover fails with the reason. |
| `/jobs/{job_id}` | GET | — | job state: `status`, `progress`, `step`, `attempts`. On success `result` is the candidate (`candidate_id`, plan, `audio`/`frames` artifacts, continuity report), which is retained server-side. |
| `/projects/{id}/edits` | POST | `{candidate_id, override?}` | approves that exact candidate; `404` if unknown, `422` if continuity failed — unless `override: true`, which approves it for a trial and records the edit as `overridden` |
| `/projects/{id}/export` | POST | — | renders the edited video and returns it as `render` (an MP4 artifact, downloadable from the artifacts endpoint), plus the ordered `original` / `edited` segment manifest and any `inserts` (concatenated lines: the frame is held while they play, so the export is longer). A later approval on an overlapping span replaces the earlier one. |

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
- **Silent video is refused, and invented speech is dropped.** A file with no audio track is refused outright. A file with an audio track but no speech (wind, music, a beach) is worse: Whisper *invents* speech on it, and the same few phrases every time — "Thank you for watching." was planned, voiced and added to a silent beach clip on 2026-10-03. So a transcribed segment is dropped when Whisper's own numbers say it is probably not speech (`no_speech_prob`, `avg_logprob`, `compression_ratio`), when it is one of the known invented sign-offs and Whisper is not sure of it, or when the audio under it has no speech energy above the recording's noise floor. A clip that ends up with no words is told so in the editor: nothing to change, but a voice-over can be dragged onto the timeline.
- **The sample clip is a generated placeholder.** `frontend/public/sample-ad.mp4` is a 2.3s H.264 title card whose soundtrack is macOS `say` reading the line on the card, so it genuinely transcribes. The "use the sample ad" button fetches it and uploads it through the same path as any other file. To regenerate it (macOS; needs ffmpeg):

  ```sh
  tools/gen-sample-clip.sh frontend/public/sample-ad.mp4
  ```

  The voice depends on the machine's TTS, so the output is not byte-stable across
  macOS versions. It is a placeholder, not a fixture.
- **The generated media is real but meaningless.** The mock voice adapter encodes a sine tone; the mock lip-sync adapter encodes a flat colour. Both are real, decodable files of the right length, keyed to their inputs so different prompts yield different media — they just are not speech or faces. Real vendors slot in behind the same adapter interfaces.
- **The voice is real but it is not the speaker.** ElevenLabs free tier refuses voice cloning, so the new line is spoken by a premade voice. Every such candidate carries the warning *"Stock voice — this is not the speaker's voice yet."* Phase 4b swaps in a clone once the plan is upgraded; the reference-audio extraction it needs is already built.
- **Lines are written and voiced to fit (Phase 14).** Every line the planner sees carries a syllable budget — how many fit its slot at that speaker's own rate — and the planner and the reword prompt write to it. A take that misses the slot by more than 5% is voiced again (up to `AVE_TAKES_PER_LINE`, default 3) and the nearest kept, each take charged; when all are too long for a tempo change but within reach of the model's own `speed` control, one more is spoken faster. A take is then fitted **pauses first**: silence between words and at the edges is trimmed (or opened, for a short line) before any speech is sped up or slowed, so the words themselves barely move. A long line may also start up to 150 ms early, into the pause before it, when the pause after is not quite enough.
- **A longer line runs into the pause after it.** When a take is longer than the words it replaces and the pause before the next word (plus 50 ms of slack) can hold the overrun, the edit grows to cover the whole line and nobody is asked — the take that did not fit is held by the voice adapter, so placing it costs nothing more. A shorter line still asks (silence or a slowed line is a real choice), as does a long one with nowhere to go. Per project: `pause` (default), `stretch`, or `ask`.
- **Speech is time-fitted, within limits.** A line too long for the selection is sped up by at most 1.25×; one too short is slowed by at most 0.8× and centred in a little silence (which room tone then fills). ElevenLabs' take length varies per call, so a take that cannot be fitted is regenerated like one that fails continuity; the job fails — asking you to widen or narrow the selection — only if no take fits. Every take is a paid call.
- **The export re-voices the audio; the video is the original.** Lip-sync is backlogged (Phase 5), and the mock frames are a flat colour, so the render keeps the source's own frames everywhere: the new words play over the old mouth movements. H.264 sources are stream-copied; anything else is re-encoded to H.264 so the download plays everywhere. Seams get 20 ms equal-power crossfades; everything outside an edit is the source's audio, re-encoded to AAC.
- **Export is synchronous and renders on every click.** Seconds for a 3-minute source, since only the audio is re-encoded; renders are content-addressed, so re-exporting unchanged edits stores nothing new.
- **Half the continuity scorecard is measured.** With a real voice, prosody (pitch register against the surrounding speech) and audio integration (level and clarity) are measured from the audio, after automatic level and room-tone correction; a failing take is regenerated up to `AVE_MAX_REGENERATIONS` times (default 2 — each one a paid call, charged to the budget). Voice identity and lip-sync read "not measured yet" until Phases 4b and 5. Offline and in dry-run the scores are the mock engine's, tagged *simulated*. Thresholds were calibrated on one clip — expect to tune them on real footage.
- **Consent is a checkbox attestation, not verification.** The backend records it per project (at upload, or later via `POST /projects/{id}/consent`) and refuses generation with a 403 without it — but it trusts the uploader's word. Withdrawing it means deleting the project (`DELETE /projects/{id}`, or Delete on the start screen), which removes the record and all its media.
- **The plan is Claude's reading of the goal, and the estimate is rough.** Characters are counted from the planned wording at one take each; a take that fails continuity is regenerated (up to the cap), so the real spend can be a few times the estimate. Time is 12 s per line. Offline the planner only understands `change "X" to "Y"`.
- **Reverting keeps the edit.** Edits only ever append; Revert marks one `reverted` rather than deleting it, so the record of what was tried survives, the render skips it, and reverting again is harmless.
- **Projects persist in SQLite (`backend/var/ave.db`); media on disk.** Projects, approved edits, candidates, the chat and spend survive restarts. Jobs do not: one interrupted by a restart is lost and must be re-run. A failed transcription still orphans its upload's media.
- **Ingest is still synchronous.** Generation runs as a background job, but upload+transcription does not: a 3-minute upload blocks the request for as long as Whisper takes. Whisper is seconds, so this is liveable; lip-sync would not have been, which is why generation went first.
- **Spend is estimated, and capped.** Every paid call (Whisper minutes, ElevenLabs characters, Claude tokens) is recorded with a USD estimate from list prices — ElevenLabs's depends on your plan, so it is a configurable rate. New paid work stops at `AVE_PROJECT_BUDGET_USD` per project; the ElevenLabs character budget is separate and also persisted.
- **No sign-in yet (Phase 9c is designed, not built).** Every project has an owner and every route checks it, but today everyone is the one local owner — keep the server on localhost. Sign-in will be OIDC (Google first) behind `current_owner()` in `app/api/main.py`.
- **Jobs live in memory and are never evicted.** They accumulate for the life of the process and vanish on restart.

## Not built yet

Deferred by design: the speaker's own cloned voice (Phase 4b) and real lip-sync (Phase 5) — both in the roadmap's backlog, blocked on vendor access — plus voice-identity and lip-sync scoring (Phase 6b, after those), sign-in (Phase 9c, designed), and more than premade voices — each speaker's *own* voice needs cloning (Phase 4b). See `docs/superpowers/plans/2026-09-22-real-pipeline-roadmap.md` for the phased route through them. Product-level, v1 is dialogue changes only — visual detail swap (Phase 2), pacing/filler edits, multi-speaker crosstalk, and non-English are all out of scope.
