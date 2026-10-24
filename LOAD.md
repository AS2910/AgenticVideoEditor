# Load test (launch rehearsal, item 3)

**Safe on one 4 vCPU / 6 GB VM, for 60 s videos: about 10 people editing at once with no
slowdown (2 to 3 if a render takes as long as it did on the shared laptop's VM).** The 30
below held for the 2.3 s test clip, whose render is almost free; a real 60 s render takes
one core for 30 s to 2 min (run 4, "One real 60 s render"), and renders, not requests, are
the limit. For short clips (10 s and under) the 30 / 50 / 75 below still stand: 30 people
working at once with no slowdown; 50 at once with no errors but voicing slows (renders
queue); 75 breaks. Ship with the new defaults
(AVE_JOB_WORKERS=16, AVE_WORK_WORKERS=4, AVE_HTTP_THREADS=100). If most signed-up people
are idle at any moment (5 to 10% active is common for a tool like this), 30 active is
roughly 300 to 600 accounts; watch the queue (`/api/health` jobs.queued) rather than
trusting that ratio.

## How it was run

- The shipped compose stack on this laptop (Colima VM: 4 vCPU, 6 GB), Postgres 16 as the
  database, the public profile, password accounts (`scripts/rehearsal.sh` with
  `RH_NAME=voltage-load RH_PORT=8090`).
- Mocked vendors that wait like the real ones: Claude 1 to 3 s a call (two calls a turn),
  a voiced line 2 to 6 s, a render 5 to 20 s (plus the real ffmpeg render of a 2.3 s clip).
  The waits are sleeps, so the CPU a real Claude or ElevenLabs call costs is absent
  (none: they are remote) and a long real clip's render CPU is not measured (see Limits).
- k6 (`tools/load/voltage.js`): each virtual user is one new person's full session, over
  and over: sign in, Home, upload, a turn that proposes a line, the go-ahead that voices
  it, Add (renders), export, Billing, with 2 to 10 s of thinking between steps. Ramp to
  the peak over 2 minutes, hold 4 minutes. Users made with `tools/load/seed.sh`
  (verified through the dev outbox). For the test only: the sign-in rate limit raised
  (all users share one address) and the day cap off.
- CPU and memory: `docker stats` every 5 s (`tools/load/stats.sh`); `docker stats`
  counts 100% per vCPU, so 400% is the whole VM (single samples above 400% are its
  sampling noise; read the averages).
- Raw results: `docs/rehearsal/load/run<N>-summary.json` and `-stats.csv`;
  `python3 tools/load/report.py <summary> <stats>` prints these tables.
- Caveat: runs 2 to 5 shared the laptop with five agents running test suites (load
  average 60 to 140), so their absolute numbers are worse than a VM would see. Runs 6 to
  8 ran on a quiet laptop.

## What was found and fixed

1. **First bottleneck: one upload froze the whole API.** `POST /videos` was an async
   route that probed, stored and transcribed the file on the event loop. While any upload
   ran, every other request waited (at 50 users even `GET /auth/me` had a p95 of 8 s and
   `GET /videos` 21 s). With real Whisper (seconds to minutes per upload) one upload would
   stall everyone. Fixed: the slow part of every async upload route (videos, your voice,
   word clips, project files, liveness) runs in the thread pool; the bytes still stream in
   on the loop. Test: `backend/tests/launch/test_event_loop.py` (fails without the fix).
2. **Second: four job threads.** Turns, voicing and upload processing shared 4 threads,
   so at 50 users a turn waited 2 minutes (p50 123 s) to start. Now AVE_JOB_WORKERS,
   default 16: queue wait p50 under 5 s at 50 users.
3. **Third: Add renders inside the request.** `POST /plans/{id}/approve` held an HTTP
   thread for the whole render (5 to 30 s). With anyio's 40 threads, 50 users' Adds left
   nothing for sign-in (login p95 60 s, 15 timeouts). Then AVE_HTTP_THREADS, default 100:
   0 failures. **Fixed for good in run 4 (item 3a):** Add (and a batch's Add all that
   passed) answers at once with a render job; the render runs on the work pool with every
   other render, so no request holds a thread for one. Still rendering inside a request:
   `POST /videos/{id}/export` (the editor's own re-render after an undo, a move or a role
   change, the with-proposals preview, and the Export page's export). Moving those is the
   next step of the same change (the editor would start `/renders` and wait for the job).
4. **What is left at 50: the render queue.** Renders and previews run 4 at a time
   (AVE_WORK_WORKERS=4, about one per vCPU since a real render is ffmpeg on every core).
   At 50 users the go-ahead (voice + preview) p50 stays 28 s but p95 grows to 6 minutes.
   More VM cores, not more threads, is the next step.

## Runs

| Run | Peak users | Settings | Host | Sessions | Failed requests | Turn queue wait p50 / p95 | Turn ready p50 / p95 | `GET /videos` p95 |
|---|---|---|---|---|---|---|---|---|
| 2 | 50 | before the fixes (4 job threads, upload on the loop) | busy | 21 | 0 (but most sessions unfinished) | n/a | 98.8 s / 133 s | 20.9 s |
| 3 | 50 | upload off the loop, 4 job threads | busy | 36 | 10 checks | 123 s / 252 s | 126 s / 259 s | 39.2 s |
| 4 | 50 | + 16 job threads | busy | 172 | 0 | 6.6 s / 20.1 s | 11.5 s / 26.3 s | 5.5 s |
| 5 | 75 | 16 job threads, 4 render threads | busy | 120 | 65 | 32.1 s / 119 s | 37.5 s / 160 s | 60 s (timeouts) |
| 6 | 30 | 16 / 4 / 40 HTTP threads | quiet | 157 | 0 | 39 ms / 278 ms | 4.0 s / 4.3 s | 452 ms |
| 7 | 50 | 16 / 4 / 40 | quiet | 186 | 15 (sign-in timeouts) | 2.1 s / 19.7 s | 6.0 s / 22.9 s | 19.3 s |
| 8 | 50 | 16 / 4 / **100 HTTP threads** (the new defaults) | quiet | 242 | **0** | 4.0 s / 31.2 s | 6.1 s / 37.1 s | 2.2 s |

### 30 people at once (run 6): the comfortable load

| Call | p50 | p95 | calls |
|---|---|---|---|
| `POST /auth/password/login` | 68 ms | 151 ms | 157 |
| `GET /auth/me` | 5 ms | 25 ms | 157 |
| `GET /me/flags` | 6 ms | 32 ms | 157 |
| `GET /videos` | 81 ms | 452 ms | 157 |
| `GET /projects` | 13 ms | 71 ms | 157 |
| `POST /videos (upload)` | 97 ms | 324 ms | 157 |
| `GET /videos/{id}` | 14 ms | 77 ms | 157 |
| `GET /videos/{id}/messages` | 7 ms | 34 ms | 157 |
| `POST /videos/{id}/turns` | 31 ms | 214 ms | 314 |
| `GET /jobs/{id}` | 6 ms | 29 ms | 2387 |
| `GET /videos/{id}/jobs` | 11 ms | 42 ms | 157 |
| `POST /plans/{id}/approve (renders)` | 14.30 s | 20.29 s | 157 |
| `POST /videos/{id}/export` | 106 ms | 299 ms | 157 |
| `GET /billing` | 18 ms | 73 ms | 157 |
| Turn: queue wait (until running) | 39 ms | 278 ms | 314 |
| Turn: proposal ready | 4.03 s | 4.27 s | 157 |
| Go-ahead: line voiced and previewed | 24.11 s | 30.54 s | 157 |

Sessions finished: 157; failed requests: 0 of 4585; failed checks: 0.
- app: CPU avg 93%, max 394% (of 400%); memory max 657 MiB
- postgres: CPU avg 8%, max 24% (of 400%); memory max 51 MiB
- web: CPU avg 0%, max 2% (of 400%); memory max 5 MiB
- worker: CPU avg 0%, max 0% (of 400%); memory max 19 MiB

### 50 people at once (run 8): the edge, with the new defaults

| Call | p50 | p95 | calls |
|---|---|---|---|
| `POST /auth/password/login` | 45 ms | 1.18 s | 242 |
| `GET /auth/me` | 3 ms | 262 ms | 242 |
| `GET /me/flags` | 3 ms | 444 ms | 242 |
| `GET /videos` | 66 ms | 2.15 s | 242 |
| `GET /projects` | 8 ms | 72 ms | 242 |
| `POST /videos (upload)` | 68 ms | 241 ms | 242 |
| `GET /videos/{id}` | 7 ms | 35 ms | 242 |
| `GET /videos/{id}/messages` | 4 ms | 22 ms | 242 |
| `POST /videos/{id}/turns` | 20 ms | 1.07 s | 484 |
| `GET /jobs/{id}` | 4 ms | 120 ms | 4423 |
| `GET /videos/{id}/jobs` | 7 ms | 120 ms | 242 |
| `POST /plans/{id}/approve (renders)` | 14.44 s | 95.81 s | 242 |
| `POST /videos/{id}/export` | 76 ms | 343 ms | 242 |
| `GET /billing` | 11 ms | 71 ms | 242 |
| Turn: queue wait (until running) | 4.03 s | 31.15 s | 484 |
| Turn: proposal ready | 6.11 s | 37.05 s | 242 |
| Go-ahead: line voiced and previewed | 28.10 s | 380.96 s | 242 |

Sessions finished: 242; failed requests: 0 of 7811; failed checks: 0.
- app: CPU avg 129%, max 685% (of 400%); memory max 672 MiB
- postgres: CPU avg 11%, max 58% (of 400%); memory max 60 MiB
- web: CPU avg 1%, max 10% (of 400%); memory max 5 MiB
- worker: CPU avg 0%, max 0% (of 400%); memory max 19 MiB

## One real 60 s render (run 4, item 3b)

The runs above rendered a 2.3 s clip plus a sleep. This measures the real thing, through
the app's own render path (`_export` -> `_render_now` -> `render` + `compose`, the code
an Add or a turn's preview runs), with `tools/load/render_bench.py`:

- Source: a phone clip with speech from the dev data (8 s), looped to 60 s and scaled to
  1080x1920, 30 fps, H.264 12 Mb/s, AAC 192k; its own words tiled over the 60 s.
- Edits: 4 replaced lines (one every 16 s) and an 8 s layered voice-over; mock voice
  takes (no vendor cost). Every run renders from scratch (the render cache cleared).
- Raw numbers: `docs/rehearsal/load/render60-results.json`.

| Where | Run | Wall | CPU (all processes) | of which ffmpeg / children | Cores busy | Peak memory (app + children) |
|---|---|---|---|---|---|---|
| Laptop, macOS, 8 cores shared (load 98 to 140) | 1 | 341.1 s | 31.7 s | 16.2 s | 0.09 | 1,132 MB |
| | 2 | 98.3 s | 32.4 s | 12.6 s | 0.33 | 753 MB |
| | 3 | 73.7 s | 28.5 s | 9.8 s | 0.39 | 601 MB |
| The api image in the Colima VM, 4 vCPU / 6 GB (host load 90 to 150) | 1 | 107.8 s | 108.8 s | 22.3 s | 1.01 | 618 MB |
| | 2 | 162.4 s | 164.6 s | 33.9 s | 1.01 | 630 MB |
| | 3 | 133.4 s | 135.7 s | 22.9 s | 1.02 | 630 MB |

What it says:

- **A render is one core, not every core.** In the VM it kept exactly 1.0 core busy for
  the whole render. Most of it is Python, not ffmpeg: the video is stream-copied (every
  piece a copy), and a profile (laptop) puts about two thirds of the render in the export
  loudness pass (`media/loudness.py`: `normalize` and `limit`, whose true-peak check
  4x-oversamples the whole mix by FFT, twice). The laptop also ran demucs stems (installed
  in its venv, about 26 s of a profiled run); the api image has no demucs.
- **The time is 30 s to 2 minutes.** Both hosts were shared with seven builders (load 90
  to 175 on 8 cores), so the wall times are slow and noisy. The laptop's CPU time, about
  30 s, is what one quiet core would take (and less without demucs); the VM's 108 to
  165 s is the conservative figure, measured where the app runs. Memory is not a limit:
  about 630 MB for the whole app process tree while it renders one (the load runs' app
  peaked near 670 MiB).
- Render time grows with the video's length (the loudness pass and the audio decode are
  linear in it): a 30 s video takes about half.

### The safe user count, from the measured render

The render queue is the limit: AVE_WORK_WORKERS=4 renders at once on 4 vCPU, each one
core, so the VM finishes `4 x 60 / T` renders a minute for a render of T seconds.

An active person makes about one render every 2 minutes (r = 0.5 a minute): every turn
that voices a line ends with a preview, every Add renders the video, with listening and
typing between. (The load test's sessions ran four times faster, about 2 renders a
minute each: a stress pace, not a person.) No slowdown means the queue stays short,
which wants the renders busy at most 70% of the time:

    safe people = 0.7 x (4 x 60 / T) / r

| Render time T (60 s video) | Renders a minute the VM can do | Safe people at once (r = 0.5) | Where T comes from |
|---|---|---|---|
| 30 s | 8.0 | 0.7 x 8.0 / 0.5 = **11** | the laptop's CPU time: one quiet core |
| 133 s | 1.8 | 0.7 x 1.8 / 0.5 = **2.5** | the VM's median, measured on a busy host |

So: **plan on about 10 people editing 60 s videos at once on one 4 vCPU VM**, and check
`render done ... seconds=` in the log on the real VM in the first week; if it says over a
minute, the safe number is 2 to 5 until the loudness pass is made cheaper. At 30 people
(15 renders a minute) the queue grows without end even at T = 30 s: every Add would wait
minutes. What raises it, cheapest first:

1. Make the export loudness pass cheaper (one true-peak pass, polyphase oversampling of
   short windows rather than a whole-mix FFT, or ffmpeg's `loudnorm` doing it in C):
   about two thirds of the render.
2. More vCPUs, with AVE_WORK_WORKERS equal to the vCPU count (a render is one core, so
   more workers than cores only makes every render slower). 8 vCPU doubles each number.
3. Skip the render when only the proposals changed and the user is not playing them
   (a turn's preview, with the proposals in it, is one of the two renders a session makes).

## Limits of this test

- The load runs rendered a 2.3 s clip plus a sleep; the 60 s render above is measured one
  at a time, not under the load test, and on a busy host. The safe count from it is
  arithmetic, not a load run with 60 s videos (the next run should upload one).
- Memory stayed under 820 MiB for the app in every run, so 4 GB of RAM is ample for the app
  plus Postgres; disk and render CPU are what grow.
- One API process is the design (`app/lease.py`): rate limits and the pause live in its
  memory. Past one VM, those move to Redis first.
