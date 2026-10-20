# Decisions made overnight

Each: what, why, how to undo.

- Phase flags are on for owner `local` only (auth is off locally, so `local` is your account). Undo: the flag store.
- No real paid smoke runs unless noted below with their cost.
- M0: migration 0001 is the schema as it stood minus the columns added later; 0002 to 0005 are those column adds (each `down` drops its columns with SQLite DROP COLUMN), 0006 is the times_v2 data rewrite. Why: every step's `down` then restores exactly the shape before it. A database made before the runner is recognised because every `up` is idempotent (create-if-missing, add-column-if-missing, the times marker), so they run, change nothing and are recorded. Undo: revert the M0 commit (the `schema_migrations` table is harmless to the old code).
- M0: 0001's `down` refuses while any table holds rows (it never deletes data); 0006's `down` is a no-op that keeps the `times_v2` marker (the time rewrite is one-way; re-running it after a down would rewrite rows written since). Undo: edit those `down` functions.
- M0: the runner runs at every `Database(...)` open; each step is one transaction and is skipped if another process recorded it meanwhile.
- FLAGS: a flag is on for an owner when a `feature_flags` row says so; with no row, the four phase flags and any `golive.*` flag default on for the owners in `AVE_FLAG_OWNERS` (default `local`), off for everyone else; unknown flags default off. A row always wins (turn off for `local`, or on for a beta tester) via `FlagStore.set`. No admin UI or API to toggle (not asked for); set rows with `flags.set(...)` or SQL. Undo: revert the FLAGS commit; `down` drops the table.
- FLAGS: the frontend reads `GET /me/flags` once per page load and caches it; a failed read leaves every flag off (features stay hidden rather than half-shown).
- Test note: `tests/api/test_allow_more.py::test_allow_more_raises_this_turns_cap_and_carries_the_turn_on` timed out (10 s job wait) in two full-suite runs on the loaded machine but passes alone, with tests/api (227 passed) and after tests/agent; treated as load flakiness, not caused by Step 0.
- WS: workspace ids are `w<n>` named "My workspace", one per owner (the owner's own), made on first write or by the backfill for every owner of a video or project. `meta` (per-owner voice lists, prefs) and `feature_flags` are keyed by owner already and get no column. Undo: `python -m app.store.migrate down --db ...` (0008) or revert the WS commit.
- WS: child rows (takes, edits, chat, turns, plans, charges, jobs) take their video's workspace; a project-level charge (no video) takes its project's; a row whose video and project are both gone keeps NULL (no owner to give it). Writers stamp the row right after the insert, in the same transaction (`app/store/workspaces.py: stamp_last`), so no call site needed the owner passed in.
- WS: `DELETE /account` leaves the owner's (now empty) workspace row; it holds no data. G5 should delete it with the account.
