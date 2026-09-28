# Phases 12–13 — The agentic editor (planned, not started)

**Date:** 2026-09-28 · **Status:** direction decided, mocks approved in principle; **resume here with Phase 12.**

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

## Picking this up

1. Start the app (README → *Running it*): backend `cd backend && .venv/bin/uvicorn app.api.main:app --reload`, front end `cd frontend && npm run dev`.
2. Open the mocks link above.
3. Write Phase 12's detailed task list from this file, then build.
