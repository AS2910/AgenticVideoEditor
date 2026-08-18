# Agentic Video Editor

Select a moment in an existing video, describe in plain English how the **spoken message** should change, and get back a re-voiced and lip-synced version that looks and sounds as if it were shot that way — iterating by chat until it's right.

The differentiator is **continuity**: splicing an AI clip into footage is easy; making it *belong* — matching voice identity, prosody, audio levels, and mouth motion — is the hard part. This repo is the agentic orchestration layer plus the continuity engine, built over swappable third-party generation models.

**Current state:** a walking-skeleton backend and the full "Voltage" editor UI, both complete and wired together. Generation is mocked — deterministic adapters stand in for real transcription/voice/lip-sync vendors, so the whole thing runs offline. The *interaction* is real; the *media* is not.

- `backend/` — Python 3.11 + FastAPI. Domain core, adapters, continuity engine, orchestrator, in-memory store, renderer, HTTP API.
- `frontend/` — React 19 + Vite + TypeScript. The Voltage editor, calling the backend through a dev-server proxy.
- `docs/superpowers/specs/` — product and front-end design docs.
- `docs/superpowers/plans/` — the implementation plans both halves were built from. The `- [ ]` checkboxes in them were never ticked during execution; treat the code and tests as the source of truth, not the boxes.

---

## Running it

Two terminals. The backend must be up first — the front end proxies to it.

### 1. Backend (port 8000)

```sh
cd backend
python3 -m venv .venv                 # first time only
.venv/bin/pip install -e '.[dev]'     # first time only
.venv/bin/uvicorn app.api.main:app --reload
```

Interactive API docs land at http://127.0.0.1:8000/docs.

### 2. Front end (port 5173)

```sh
cd frontend
npm install                           # first time only
npm run dev
```

Open the URL Vite prints. Vite proxies `/api/*` → `http://127.0.0.1:8000` with the `/api` prefix stripped, so the client always calls same-origin and there are no CORS concerns.

### The journey

Consent gate → **Load sample ad** → drag a selection on the timeline (it snaps to word boundaries) → prompt the agent, e.g. `change "20% off" to "30% off"` → review the continuity scorecard → **Approve** → **Export**.

To see the continuity *failure* path, the voice profile has to be `unknown`, which forces scores below the 0.8 pass threshold and makes approval `422`. There is no UI control for this today — change `VOICE` at `frontend/src/App.tsx:14` to `'unknown'`, or hit `/edits/preview` directly with curl.

---

## Tests

Both suites are offline and deterministic. No running server required.

```sh
cd backend && .venv/bin/python -m pytest      # 29 tests
cd frontend && npm test                        # 40 tests, 11 files
```

---

## The API

Four synchronous endpoints, all `POST`:

| Endpoint | Does |
| --- | --- |
| `/projects` | `{filename, duration}` → `project_id` + a canned transcript |
| `/projects/{id}/edits/preview` | prompt + selection → edit plan, opaque media refs, continuity report |
| `/projects/{id}/edits` | approves a candidate; `422` if continuity failed |
| `/projects/{id}/export` | ordered segment manifest of `original` / `edited` spans |

Example:

```sh
curl -X POST http://127.0.0.1:8000/projects \
  -H 'content-type: application/json' \
  -d '{"filename":"sample-ad.mp4","duration":2.3}'
```

---

## Seams you should know about

These are deliberate and documented, not oversights:

- **The transcript is canned.** Every project comes back as `Get 20% off today only`, words spanning 0.0–2.3s, regardless of the file you name.
- **The sample clip is a generated placeholder.** `frontend/public/sample-ad.mp4` is a 2.3s H.264 title card with no audio, built to match the canned transcript's word timings so the timeline and the picture agree. Replace it with real footage whenever you like — `App.tsx` points at `/sample-ad.mp4`. To regenerate the placeholder (macOS, no dependencies):

  ```sh
  swift tools/gen-sample-clip.swift frontend/public/sample-ad.mp4
  ```
- **A candidate has no playable preview.** Generation returns opaque `audio://` / `frames://` refs, so "review the candidate" is a continuity scorecard. That is the shape the real preview card will take once media exists.
- **Consent is enforced only in the UI.** There is no backend consent field yet.
- **Storage is in-memory.** One project per server process; restarting loses everything.

## Not built yet

Deferred by design: real async job polling, backend-enforced consent, real video upload/storage/serving, real generation vendors behind the adapter interfaces, real ffmpeg rendering, multi-project persistence, and auth. Product-level, v1 is dialogue changes only — visual detail swap (Phase 2), pacing/filler edits, multi-speaker crosstalk, and non-English are all out of scope.
