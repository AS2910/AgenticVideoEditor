# One processing model: the API contract (2026-10-20)

Every surface (status strip, Activity drawer, row chips, player badge, chat step list,
toasts, tab title) reads from this. Backend in `jobs-backend`, UI in `jobs-ui`.

Note: there was no SSE channel before this; the editor polled `/jobs/{id}` and
`/messages`. `GET /videos/{id}/events` is new.

## Job

```json
{
  "job_id": "J12",                 // string, unique per server
  "video_id": "p61",
  "turn_id": "j40" | null,         // the turn that caused it (spend scopes' turn id)
  "kind": "voice_line" | "design_voice" | "clone" | "mix" | "render_preview" | "export",
  "status": "queued" | "running" | "done" | "failed" | "cancelled",
  "step_label": "Voicing" | "Checking fit" | "Retake at 1.08x" | "Rendering preview v4" | ...,  // plain words, no em dashes
  "progress": 0.0,                 // 0..1
  "line_ids": ["i3"],              // plan item ids ("i3") and/or edit ids ("e2") the job is about
  "created_at": "ISO", "started_at": "ISO" | null, "finished_at": "ISO" | null,
  "eta_s": 12 | null,              // whole seconds >= 1 while queued/running; null when terminal or unknown
  "error_code": null | "vendor_failed" | "too_long" | "budget" | "timeout" | "interrupted" | "render_failed" | "unknown",
  "error_text": null | "Too long for its gap after a retake at 1.10x.",
  "cost_usd": 0.02 | null,
  "retryable": true,               // failed voice_line and render jobs
  "detail": {                       // optional, by kind
    "text": "words being voiced", "voice_name": "Jeevan", "chars": 54,           // voice_line
    "version": 5, "mode": "final" | "proposals", "render_id": "r9",               // render_preview / export
    "includes": {"candidate_ids": [...], "edit_ids": [...], "item_ids": [...]},  // render_preview / export: the takes it carries
    "manual": true                                                                 // started from the editor, not a turn
  }
}
```

Transitions: queued -> running -> done | failed | cancelled; queued -> cancelled.
Terminal states never change. A running job with no update past its kind's
timeout becomes failed (error_code "timeout"); jobs left running by a restarted
server become failed ("interrupted"). Nothing stays running forever.

ETA: median seconds of recent finished jobs of the same kind (per character
for voice_line), times this job's characters; null when the kind has no
finished job yet (no guessed numbers); always >= 1, rounded up.

## Turn view

```json
{ "turn_id": "j40", "status": "running" | "done" | "failed" | "stopping",
  "step": "Thinking", "started_at": "ISO", "finished_at": "ISO" | null,
  "spent_usd": 0.09, "lines_voiced": 5, "render": {"version": 5, "mode": "proposals"} | null }
```

## Endpoints

- `GET /videos/{id}/jobs?active=1` -> `{"jobs": [Job...], "turn": Turn | null}`. Newest first.
  `active=1`: queued/running only, plus the jobs of the active (or most recent, if finished in the last 10 min) turn.
  Without it: the last 50 jobs (Activity drawer).
- `GET /videos/{id}/events` -> `text/event-stream`. Events:
  - `event: job.updated` data: Job
  - `event: turn.updated` data: Turn
  - `event: render.updated` data: RenderState (below)
  - `: ping` comment every 15 s.
- `POST /videos/{id}/jobs/{job_id}/retry` -> new Job (queued/running). 409 when not retryable.
  A failed voice_line retries the same item with the same words and voice, outside a turn
  (detail.manual = true), through the same job flow.
- `POST /videos/{id}/jobs/stop` -> `{"cancelled": n}`. Queued jobs cancelled; running ones finish;
  the active turn stops after its current tool call (turn status "stopping" then "done").
- `GET /videos/{id}/renders/latest?mode=final|proposals` -> RenderState:

```json
{ "mode": "final",
  "current_hash": "ab12...",              // edit set as it is now
  "latest": { "render_id": "r9", "version": 4, "edit_set_hash": "...", "created_at": "ISO",
              "mode": "final", "render": {artifact dict}, "manifest": {the export payload},
              "includes": {"candidate_ids": [...], "edit_ids": [...], "item_ids": [...]} } | null,
  "in_progress": { "render_id": "r10", "version": 5, "edit_set_hash": "...", "started_at": "ISO",
                   "eta_s": 8, "job_id": "J20", "includes": {...} } | null,
  "stale": true }                          // latest.edit_set_hash != current_hash and nothing in progress
```

- `POST /videos/{id}/export` (existing) also returns `render_id`, `version`, `includes`; body gains
  `purpose: "preview" | "export"` (default preview -> job kind render_preview; the Export page sends export).
- `POST /videos/{id}/renders` body `{"mode": "final"|"proposals"}` -> Job (render_preview), runs in the background.

Versions: one counter per video; a render gets a new version only for an edit_set_hash
never rendered before (any mode). Same hash again reuses its version.

## The turn's own jobs

- On a "Go" (approve) or under Just do it, the turn creates queued voice_line jobs at once
  for every planned, enabled item not yet voiced, so rows say Queued immediately.
- `synthesize_take` claims its item's queued job (or makes one), running -> done/failed.
- At the end of a turn that voiced or shipped anything, the turn renders a preview
  (render_preview job, turn_id set): mode "proposals" when the plan has ready items, else "final".
- Leftover queued jobs of a finished turn -> cancelled.
- Turn result gains `turn_usd` (everything the turn spent) and `render: {version, mode, render_id}`.

## `includes`

Every render record (RenderState.latest, RenderState.in_progress, the POST /export
response, render_preview/export job detail) carries
`includes: {"candidate_ids": [...], "edit_ids": [...], "item_ids": [...]}`: the takes
the render carries. `edit_ids` are kept edits; `item_ids` are proposals in a
proposals render. A render job's `line_ids` are `item_ids + edit_ids`.

## Notes from the backend build

- `POST /videos/{id}/renders` and `POST .../jobs/{job_id}/retry` answer 202 with the Job.
  Retry: 404 for an unknown job, 409 when the job is not a failed line or render,
  or when the line is already being voiced.
- A cached render (same edit set already rendered) creates no job from `/export`
  (nothing ran); from `/renders` or a retry the job goes straight to done ("v4 ready").
- Turn view also carries `step` while running ("Thinking", a tool's step, "Rendering preview")
  and `step: "Stopping after this step"` while `status: "stopping"`. A turn the server lost
  (restart mid-turn) reads as `status: "failed", step: "Interrupted"`.
- On Stop, the turn's closing message is "Stopped. N lines voiced, M cancelled." (no question).
- `plan_lines` (the agent's tool) now puts every line it plans with words that fit into the
  plan as a `planned` item before anything is voiced, so a Check-with-me gate ("Voice all
  five?") has rows to show and a Go has items to queue. Before this, items were created only
  when a line was voiced, so a Go had nothing to queue.
- Kinds in use: voice_line (agent and retry), clone (first clone of a speaker), design_voice,
  mix (role/level change: "Mix changed"; Undo: "Took the line out", line_ids = the edit ids),
  render_preview (editor renders, Add it, the turn's closing render), export (`purpose: "export"`).
- No ETA before a kind has history (eta_s null; the UI shows no time). Timeouts (no update):
  voice_line/clone/design_voice 300 s, mix 120, render_preview 900, export 1800.
- `job.updated` events carry the same Job dict as GET jobs. The stream opens with the active
  view (oldest first) and the turn, then live events; `?limit=N` ends it after N events.
