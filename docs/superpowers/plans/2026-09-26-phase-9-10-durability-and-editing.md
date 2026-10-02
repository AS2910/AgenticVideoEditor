# Phases 9–10 — Durability, cost, and editing by transcript

**Date:** 2026-09-26 · **Roadmap:** Phase 9 (durability & hardening) in full, then Phase 10 (editing UX), both chosen by the user after hands-on testing.

## Decisions (user, 2026-09-26)

- **All of Phase 9.** The app is headed for a **public product later**: auth is *designed* now (every project has an owner; one seam decides who the caller is) and *built* when it ships — provider sign-in (e.g. Google, OIDC), not passwords.
- **Editing asks:** a transcript view where each statement can be edited; a voice picker; a zoomable, scrollable timeline. **Multiple voices later** — the model is shaped for it now (a voice per edit; speakers later).

## Phase 9a — Projects survive restarts

Today every restart loses every project — the single biggest friction in testing.

- **SQLite** (`<data_dir>/ave.db`, stdlib `sqlite3`, WAL, one lock) behind the existing `ProjectRepository` interface, so callers barely change. Media stays in the content-addressed artifact store on disk.
- Tables: `projects` (owner, filename, duration, media, transcript, consent, created), `candidates`, `edits` (append-only, approval order), `messages` (the chat).
- **The chat is stored server-side.** The server records each user message and each reply/question, and reads history from there — the client no longer sends it.
- **Owner on every project.** `current_owner()` is the auth seam: `"local"` today; a verified identity when sign-in lands. Every project route checks it — someone else's project is a 404, not a 403, so ids leak nothing.
- New routes: `GET /projects` (mine, newest first), `GET /projects/{id}` (everything needed to reopen it), `DELETE /projects/{id}` (record and media — also how consent is withdrawn, spec §2).
- Jobs stay in memory: a job interrupted by a restart is lost, and the client says so.
- **Front end:** the start screen lists past projects to reopen or delete.

## Phase 9b — What it costs, and a ceiling

- **Usage ledger** (`usage` table): one row per paid call — vendor, units, unit, estimated USD.
  - Whisper: audio minutes × $0.006. ElevenLabs: billed characters (USD depends on plan — recorded as characters, USD estimated at the configured rate). Claude: input/output tokens × the model's price (Opus 5: $5 / $25 per M).
- The voice budget reads from the ledger, so it survives restarts too.
- **Project spend ceiling** `AVE_PROJECT_BUDGET_USD` (default $2.00) across all vendors: new paid work is refused once it is reached, with the reason.
- `GET /projects/{id}/usage` — totals per vendor; the editor shows the project's spend.

## Phase 9c — Auth, designed

Written down, not built: OIDC sign-in (Google first) → a session cookie → `current_owner()` returns the verified subject. Localhost stays open for development. What changes when it ships: the seam, a login page, CSRF on state-changing routes, and per-user quotas on top of per-project ones.

## Phase 10 — Editing by transcript, voices, timeline

- **Transcript panel.** Whisper's segments are kept (they carry punctuation; its words don't) as the transcript's *statements*. Each statement is shown with its time; click → edit its text in place → Preview. That is an edit of the statement's span with the new text given directly (Claude is skipped — there is nothing to interpret), through the same candidate / question / approve flow. Projects transcribed before this derive statements from word gaps.
- **Voice picker.** `GET /voices` lists ElevenLabs premade voices (name, gender, accent), cached. The chosen voice travels as the plan's `voice_profile_id` (already there); the adapter uses it. **Multi-voice later:** a voice is already per edit; the next step is speaker labels on statements (diarization) and a voice per speaker.
- **Timeline zoom & scroll.** A minimum width per second so words stay legible, zoom in/out, horizontal scroll that follows the playhead.

## Exit (each part)

Backend + frontend suites green; ruff, tsc, oxlint, build clean; README and roadmap current; live-checked — a restart keeps projects and chat; spend shows and the ceiling refuses; a statement edit and a different voice work end to end on a real clip.
