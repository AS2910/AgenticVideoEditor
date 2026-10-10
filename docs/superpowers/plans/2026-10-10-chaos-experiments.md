# Chaos experiments for Voltage

**Written:** 2026-10-10, from the `/chaos-engineer` pass. Voltage is one process on one machine — FastAPI under `uvicorn --reload`, a two-worker job pool, SQLite in WAL mode, ffmpeg, and three paid vendors over HTTPS (ElevenLabs, OpenAI, Anthropic) — so the chaos worth rehearsing is not pods and zones but *a vendor that misbehaves, a tool that is missing, a disk that is full, a process that is restarted mid-job.*

## 1. System map and failure modes

| Component | Depends on | How it fails | Who notices |
|---|---|---|---|
| Job pool (`JobRunner`, 2 threads, retries 3× with 0.5/1/2 s backoff on `VendorError`) | vendors, ffmpeg, disk | a hung vendor call holds a worker (no per-job timeout); two of them stall every later job | the frontend's poll runs to its 5-minute timeout |
| Job store (in memory) | the process | a reload or crash loses every running job | the poll gets a 404 |
| ElevenLabs adapter (`httpx`, 60 s timeout) | network, key, plan | 429 / 5xx / reset; each attempt is charged *before* the call | the budget and the receipt |
| Anthropic client (SDK) | network, key, workspace | the SDK's default timeout was 600 s with 2 retries of its own | a planner job that sits at "Starting" |
| Whisper adapter | network, key | 4xx/5xx/timeout on upload | the upload fails |
| SQLite (`Database`, one connection, `RLock`) | the file | a second process holding a write lock made a request fail at once | any write |
| ffmpeg | PATH, disk | missing binary, full disk | a job failing with "Something went wrong." |
| Export (`_export`) | ffmpeg, pieces | synchronous on the request thread; a long `minterpolate` window can run minutes | the browser's fetch waits |

## 2. Steady state

Before any fault: `GET /health` answers with `jobs: {workers: 2, running: 0, queued: 0}` and `chaos: null`; a preview on the sample ad succeeds within 15 s (mock voice) or 60 s (ElevenLabs); the project's spend meter equals the ledger; `python -m app.bench gate` is open.

## 3. The experiments

Each is one variable, with the smallest blast radius (this process, a scratch project) and a scripted rollback under 30 seconds: unset `AVE_CHAOS` and `touch backend/app/api/main.py` (the reloader restarts the worker), or restore the PATH.

| # | Hypothesis | Injection | Steady state kept? | Finding |
|---|---|---|---|---|
| E1 | A rate-limit storm costs nothing | `AVE_CHAOS=elevenlabs=status:429` | **No** at first: three retries left three charges on the ledger and three "takes voiced" on the receipt | **Fixed**: `VoiceBudget.refund` (a negative ledger row) on any failed call; call counts cancel a refund against its charge |
| E2 | Two hung vendor calls stall the pool | `AVE_CHAOS=anthropic=hang:120` and two plans | **No**: the third job queues until a worker frees; nothing says so | **Partly fixed**: `/health.jobs` shows running/queued; the Anthropic client's timeout is now 60 s with one SDK retry (was 600 s, two). A per-job deadline is left as a backlog item |
| E3 | A restart loses running jobs; the client learns it | `touch` a backend file during a preview | Yes for the client (404, "Could not load the job"); spend survives because the ledger is in the database | Documented; persisting jobs is a public-product item |
| E4 | A missing ffmpeg or a full disk is said plainly | `PATH` without ffmpeg; `OSError(ENOSPC)` | **No**: "Something went wrong." | **Fixed**: the runner reports `Could not process the media: …` with the system's own words |
| E5 | A second process's momentary write lock does not fail a request | a second `sqlite3` connection holding `BEGIN IMMEDIATE` for 0.4 s | **No**: `database is locked` at once | **Fixed**: `PRAGMA busy_timeout=5000` |
| E6 | The fault seam itself is safe | bad specs, sign-in on | — | Refuses bad specs; refuses to run with `AVE_AUTH=google` unless `AVE_CHAOS_FORCE=1`; logs every injected fault |
| E7 | Health shows the pool and the faults | `GET /health` | — | `jobs` and `chaos` fields added |

Not run, documented: a slow export (`minterpolate` on a long window) blocks the request thread; the fix is an export job, which the frontend already knows how to poll — a public-product item.

## 4. Implementation

- `backend/app/chaos.py`: `AVE_CHAOS="vendor=kind[:arg][@rate];…"` with kinds `status:<code>`, `hang:<s>`, `slow:<s>`, `reset`; wrappers at the seams the adapters already expose (`post=` for ElevenLabs and Whisper, `client=` for Claude), so nothing leaves the machine and nothing is charged. `selection.py` applies them; `/health` reports them.
- Fixes: `VoiceBudget.refund`, refund on failure in `ElevenLabsVoiceAdapter._take`, call counts that net refunds (`Ledger.lines`, `Ledger.calls_since`), `busy_timeout`, `JobRunner.snapshot`, plain media-failure messages, one Anthropic client with a 60 s timeout.
- `backend/tests/chaos/test_experiments.py`: every experiment as a test, in CI.

## 5. Game day runbook (the live process)

1. Steady state: `curl localhost:8000/health`; run one preview on a scratch project; note the spend meter.
2. One fault at a time: `AVE_CHAOS=elevenlabs=status:429@0.5 .venv/bin/uvicorn app.api.main:app --reload`; ask for a take; watch the log for `CHAOS:` lines, the job's `attempts`, the spend meter (must not move on failures), the receipt's takes.
3. `AVE_CHAOS=anthropic=hang:90`: start two plans, then a third; `/health.jobs` must read `running: 2, queued: 1`; the third starts when the first times out at 60 s.
4. Restart mid-job: `touch backend/app/api/main.py` while a take is voicing; the row must say "Could not load the job", not sit at Working.
5. `PATH=/usr/bin:/bin` (no ffmpeg) and upload: the error must name ffmpeg.
6. Rollback after each step: unset the variable, `touch` the file, `curl /health` shows `chaos: null`. Abort at once if a real vendor call is observed in the log while chaos is on.
7. Write the learning summary below; file one improvement per surprise.

## 6. Learning summary

Three of seven hypotheses failed and were fixed the same day (refunds, lock waits, media messages); one was made visible (pool starvation) and bounded (the Anthropic timeout); two are design limits recorded for the public product (job persistence, export as a job). The seam stays in the codebase so the next game day costs one environment variable.

## Backlog from this pass

- A per-job deadline in `JobRunner` (fail the job, free the worker) — the pool is still starvable by a slow-but-not-timed-out vendor.
- Persist jobs (SQLite) so a reload resumes or fails them cleanly.
- Export as a job with progress, so a long picture retime cannot hold a request.
- An uptime check on `/health.jobs` once the product is public.
