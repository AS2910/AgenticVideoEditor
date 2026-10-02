# Phases 12–13 — The agentic editor

**Date:** 2026-09-28 · **Status:** Phase 12 built 2026-10-02 (see *Phase 12 — as built* below); **resume with Phase 13.**

## Where this came from

After the 2026-09-26 redesign (an edit bay around a screenplay-style script page, `docs/superpowers/specs/2026-09-26-editor-ui-redesign.md`), the user asked for a UI that is **more agentic and modern**, and chose:

> **a + b as a more controlled option** — the agentic editor, with hands-on editing kept inside it, and the user in control of how much the agent does on its own.

**Mocks:** a private design canvas, https://claude.ai/artifact/LhccYtUyhe2YAipTQ6Nyp7 (page "Agentic direction", screens A–E; page "Next steps" holds the earlier mocks 1–4: everyday fixes, own voice, lip-sync, sign-in).

| Screen | What it shows |
|---|---|
| A. Start from a goal | Upload, then "What should your video say?" — a goal in your own words, example prompts, recent projects |
| B. The agent at work | Transcript with inline tracked changes and a status per line; agent panel with the plan (done / working / needs you), its own fix for a "needs you" case (a shorter line), an unprompted suggestion |
| C. Review and ship | Before/after per change with Compare and Redo, "Approve all and export", a "What Voltage did" log with cost |
| D. Controlled | The autonomy switch on **Ask before running**: the plan waits, each change can be unticked or reworded, cost and time estimated, nothing spent until **Run** |
| E. Hands-on | Click a transcript line and edit it in place: voice, what to do if it runs long, "Ask Voltage for wording", Preview; the agent stays out of it |

## Decisions

- **The agentic editor replaces the script-page editor**; hands-on line editing lives inside it (screen E).
- **Autonomy switch per project:** *Ask before running* (default — the controlled option) and *Draft everything*.
- **Modern look:** one sans (Instrument Sans), dark neutral surfaces, rounded panels, one blue accent, amber for "needs you"; no red/green status pairs. Tokens in the mocks: bg `#0E0F11`, surface `#16171A`, raised `#1E2024`, line `#2A2C31`, text `#ECECEA`, muted `#9A9CA2`, accent `#8AAAFF` (fill `#3F6FE8`), amber `#E3A33D`, speakers `#2BB3A0` / `#D66BA0`.
- The screenplay page's ideas that carry over: changes shown as revisions (now inline tracked changes), speaker identity on every line.

## Phase 12 — The new editor (mostly front end)

- New layout and visual system (screens B/E without the planning agent): monitor + transport; transcript as a document with speaker avatars, inline tracked changes (struck old words, highlighted new ones) and a status chip per changed line; agent panel on the right with the chat, takes and questions.
- **Hands-on inline editing** (screen E): wording, voice, "if it runs long" (use the pause after it / speed up / ask me), Preview; "Ask Voltage for wording" calls Claude for a rewrite.
- **Everyday fixes** (canvas "Next steps" screen 1):
  - A longer line runs into the pause after it without asking when there is room; ask only when there is not. The answer is remembered per project, with "ask me each time" to undo that.
  - **Revert** an approved edit (backend: mark an edit reverted; the render skips it; the transcript shows it undone).
- Start screen from screen A's look (goal box may be inert until Phase 13).
- Exit: suites green; lint/build clean; checked by screenshot at 1470 px and a narrow width; live on a real clip.

## Phase 12 — as built (2026-10-02)

What landed, and where:

- **Visual system** — `frontend/src/styles/theme.css`: the mock's tokens (`--bg`, `--surface`, `--raised`, `--line`, `--text`, `--muted`, `--accent` / `--accent-fill`, `--amber`, speakers a–d), Instrument Sans only. Older components keep working through aliases.
- **Layout** — `App.tsx` / `App.module.css`: header (← Projects / file · length, speakers · spend · Export MP4), main column (monitor with change markers on the progress bar, word timeline, cast, transcript), the Voltage panel on the right (chat bubbles, generating state, question, take, composer with the default-voice picker). Stacks under 960 px.
- **Transcript as a document** — `components/TranscriptDoc.tsx`: time, speaker avatar (once per change of speaker), words. An approved edit shows as inline tracked changes (`<del>` / `<ins>`), computed by `transcript/changes.ts` — a word-level LCS diff that compares words without punctuation so "only." stays "only.", and reconstructs a partial revision from the timed words either side. Status chip per pending line: Working / Ready / Needs you. **Revert** beside a changed line.
- **Hands-on editing** (screen E) — click a line: textarea, Voice (defaults to the speaker's own), If it runs long (Use the pause after it / Speed it up / Ask me — the choice is remembered for the project), Ask Voltage for wording, Cancel, Preview. Enter previews, Esc cancels.
- **Everyday fixes** (canvas "Next steps" screen 1):
  - Backend `_long_line_fit` in `app/api/main.py`: on a `SpanMismatch` with no `fit`, a *long* line is placed by the project's `long_lines` setting (or the request's `on_long`): `pause` → `fit="start"` when `room_after(selection)` + 50 ms holds the overrun; `stretch` → `fit="stretch"`; `ask` → the fit question as before. The held take is reused, so no extra spend. The take card says "Ran 0.4 s into the pause after it", with "Ask me each time instead" underneath.
  - `PUT /projects/{id}/settings`, `settings` JSON column (migration), `settings` on `GET /projects/{id}`.
  - **Revert**: `ApprovedEdit.reverted`, `repo.revert_edit`, `POST /projects/{id}/edits/{edit_id}/revert`; `render()` drops reverted edits; the project list counts only live ones; reopening hides them.
  - **Ask Voltage for wording**: `POST /projects/{id}/lines/reword` → Claude via the existing interpreter, metered as anthropic/`wording`; 503 offline.
- **Start screen** (screen A's look): wordmark, headline, upload card, Recent list. The goal box waits for Phase 13.
- **Gone:** `TranscriptPanel`, Courier Prime, the paper page.

**Exit:** 387 backend + 134 frontend tests (18 files); `npm run lint` and `npm run build` clean. Live on the Bhaji Cam clip (p3): the "Bajicam" line rewritten in place came back 1.86 s against 1.48 s and ran 0.38 s into the 0.36 s pause after it (within the slack) without a question; approved (overridden — Brian's stock voice is 6 semitones under the customer), exported at 7.54–9.40, reverted, exported again to a single original segment; Claude reworded a line. Screenshots: headless Chrome at 1470 px and 420 px. Phase cost ≈ $0.035.

**Not in Phase 12, on purpose:** the autonomy switch and the goal box (Phase 13); the Chrome-extension walkthrough (the extension was not connected during the build — the layout was checked with headless Chrome instead).

## Phase 13 — The agent

- **Planning across the whole video:** Claude reads the goal with the full transcript and speakers and returns a plan — a list of edits (line, new wording, mix, speaker/voice) — via structured output / tool use.
- **Autonomy switch:** *Ask before running* shows the plan with a cost and time estimate (voice characters from the ledger's rates) and runs only the ticked, possibly reworded, items; *Draft everything* runs the plan straight away.
- **Plan jobs:** one job running several edits, a status per item (planned / working / ready / needs you / failed), all recorded in the chat and ledger.
- **Needs-you with the agent's own fix first:** when a line cannot fit, Claude proposes a shorter rewrite ahead of speed-up / overlap.
- **Unprompted suggestions:** lines the goal implies but did not name (e.g. "regular ones" in a sale ad) — add to plan or leave.
- **Review screen** (C): before/after, Compare, Redo, Approve all and export; the activity log built from the chat, jobs and usage ledger.
- Exit: as Phase 12, plus a live run of a multi-change goal on the Bhaji Cam clip.

## Still blocked (roadmap backlog)

- **4b — the speaker's own voice:** needs an ElevenLabs plan with instant voice cloning (free tier can't). Mock: canvas screen 2.
- **5 — real lip-sync:** needs a vendor key; spike Sync.so / Hedra / Runway on one clip first. Mock: canvas screen 3.
- **9c — sign-in:** designed; build when going public. Mock: canvas screen 4.

## Picking this up (Phase 13)

1. Start the app (README → *Running it*): backend `cd backend && .venv/bin/uvicorn app.api.main:app --reload`, front end `cd frontend && npm run dev`.
2. Open the mocks link above — screens A, B, C and D are Phase 13's.
3. Write Phase 13's detailed task list from this file, then build. Phase 12 left the hooks it needs: `pending` / `LineStatus` on the transcript, `on_long` on preview requests, the `settings` column for the autonomy switch, and the usage ledger's `wording` line for the cost estimate.
