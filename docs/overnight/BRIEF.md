# Overnight brief (read this first, every agent)

You are building one slice of the "Voltage Projects Build Plan" (full text: docs/overnight/PLAN.md) in the
AgenticVideoEditor repo, unattended, overnight. The user is asleep; never ask questions.

## Where
- Worktree (work ONLY here): `/Users/ashish.sinha/Documents/Ashish - Personal/Ashish - Personal Experimentation/AgenticVideoEditor-overnight`, branch `overnight/projects-plan`.
- NEVER touch the main checkout `.../AgenticVideoEditor` (uvicorn --reload serves the user's live data from it). Never push to main, never force-push. Push the branch after each commit: `git push -u origin overnight/projects-plan`.
- Live DB is never to be modified. A copy for migration tests: `/private/tmp/claude-503/-Users-ashish-sinha-Documents-Ashish---Personal-Ashish---Personal-Experimentation/1902eaf6-ef88-4cc8-ba66-8c7eca511622/scratchpad/dbcopy/ave.db` (copy it again to your own temp file before migrating; never migrate the original copy in place more than once).

## Commands
- Backend tests (from `backend/`): `../../AgenticVideoEditor/backend/.venv/bin/python -m pytest -q -p no:cacheprovider` (4 to 10 min; machine is loaded; rerun a flaky file alone before concluding).
- Frontend (from `frontend/`): `npx tsc --noEmit -p tsconfig.app.json`, `npx vitest run`, `npx oxlint src` (baseline 10 warnings; do not add), `npx playwright test` (uses installed Chrome, API mocked with page.route).
- Run the FULL suites (backend + vitest + tsc + lint; playwright when you touched UI) before every commit. If an item cannot be made green in reasonable time, `git revert`/reset that item's changes, record it as skipped in PROGRESS.md, move on.

## Rules (from the user)
- One commit per plan item, message starts with the plan ID, e.g. `A1: brief versions and stale videos`. End every commit message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Never block on a question: use the plan's recommendation or the simplest easy-to-undo choice; log it in `DECISIONS.md` (repo root) with the reason.
- Update `PROGRESS.md` (repo root) after every item: done (commit hash), skipped, blocked, what to check.
- Every new feature behind its phase flag (`projects.consistency` A, `projects.batch` B incl. F4, `projects.review` C, `projects.reuse` D; go-live items under `golive.<id>` e.g. `golive.g2`), on for owner `local` only (the user's account; auth is off locally). Foundations F2/F3/F5/F7/F8 are schema+services, not user-visible, no flag needed, but any UI they get goes behind the phase flag that uses it.
- No real money: vendors (ElevenLabs, OpenAI, Claude) mocked in tests. Do not run real paid turns (the orchestrator decides smoke runs, not you).
- No real accounts, keys or infra (Stripe, Razorpay, email, Postgres hosting): stub behind interfaces with a fake provider; list what the user must set up in `SETUP_NEEDED.md`.
- Don't delete user data or real files. Every migration reversible (up and down), tested on a copy of the live DB (above): up, check data intact, down, check schema restored, up again.
- No em dashes in UI copy, prompts or model output (there is a lint test for this; keep it green). Keep copy plain, sentence case, the user's next action last.
- Screens with no design board: match the nearest existing screen and list them in `NEEDS_DESIGN.md`.
- UI work follows `design-system/voltage/MASTER.md` (read it). Use the existing class layer (.btn, .act, .stamp, .tag, .row, .pane, tokens); no raw colours, no gradients/shadows outside the system.
- Reuse what exists (plan's working rule 1): the Phase 20 agent loop (backend/app/agent/), guards, artifacts, spend/ledger (app/usage.py, budget), the Activity job model (backend/app/jobs/activity.py, events.py, contract docs/superpowers/plans/2026-10-20-jobs-contract.md), the frontend jobs model (frontend/src/jobs/). Every long action is an Activity job. Match the surrounding code's style and comment density.
- Definition of done per item (plan): schema + API + UI behind flag; unit tests for logic, one integration test for the main flow, one browser e2e test (Playwright with mocked API, like frontend/e2e/go-run.spec.ts) for items with UI; costs via spend guard; loading/empty/error/in-progress states; a Help article updated or added (backend/app/help/) and a tour tip where one fits; analytics event names (once G7 exists; before that, list them in the item's PROGRESS entry).

## Codebase pointers
- Backend: FastAPI `backend/app/api/main.py` (big), store `backend/app/store/{db.py,repository.py}` (SQLite), "projects" table = folders of videos (renamed from earlier "projects" which became "videos"). Owner = `current_owner` dependency; LOCAL_OWNER = "local".
- Frontend: React + Vite + Tailwind v4, `frontend/src/App.tsx` (editor), `frontend/src/pages/` (ProjectsPage = Home, ProjectPage = a project/folder page, etc.), `frontend/src/api.ts`, `frontend/src/types.ts`.
- Help articles: `backend/app/help/`. Tours: `frontend/src/tour/`.

## Report back
End with: commits (hash + message), test counts for every suite, what was skipped and why, decisions logged, anything the orchestrator should check.

## Notes from earlier steps
- Run backend commands from the worktree's `backend/` dir; standalone scripts need `PYTHONPATH=<worktree>/backend` (the shared .venv otherwise imports the main checkout's `app`).
- Schema changes are numbered migrations in `backend/app/store/migrations/mNNNN_<name>.py` (up and down), run by `backend/app/store/migrate.py`; CLI `python -m app.store.migrate up|down|status --db PATH`. `AVE_LIVE_DB_COPY=<path>` enables the live-copy test.
- Flags: `backend/app/flags.py` `flags.enabled(flag, owner)`; frontend `useFlags()` in `frontend/src/flags/useFlags.ts`.
- Workspaces: `backend/app/store/workspaces.py`; every new user-data table gets `workspace_id` set on write.
- Known load flake: tests/api/test_allow_more.py::test_allow_more_raises_this_turns_cap_and_carries_the_turn_on (passes alone).
- Step 1 services: briefs `app/store/briefs.py` (routes GET /projects/{id}/briefs, /briefs/diff), rules `app/store/rules.py` (CRUD /projects/{id}/rules, read into context.py opening), stages `app/store/stages.py` (`move`, `history`, `after_new_edit` not yet wired: C1 wires it), actors `app/store/actors.py`, events `app/store/events.py` (`record(c, verb, actor, ...)` in the caller's transaction; GET /projects/{id}/events, /videos/{id}/events/log), soft delete + `app/purge.py`. Live-copy check script: scratchpad/livecheck.py.
- Owed fixes: D3 must change Home's "Delete for good" copy (ProjectsPage.tsx ~295) to the Bin wording, and exclude deleted videos from /usage by-project counts. G6 should add "withdraw consent now" (purge a clone immediately).
- Analytics event names so far (G7 wires them): brief.saved, rule.added, rule.changed, rule.removed, stage.moved, video.moved_in, video.moved_out, edit.shipped, edit.undone, video.deleted, project.deleted. Each later item lists its own in PROGRESS.md.
