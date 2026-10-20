# Decisions made overnight

Each: what, why, how to undo.

- Phase flags are on for owner `local` only (auth is off locally, so `local` is your account). Undo: the flag store.
- No real paid smoke runs unless noted below with their cost.
- M0: migration 0001 is the schema as it stood minus the columns added later; 0002 to 0005 are those column adds (each `down` drops its columns with SQLite DROP COLUMN), 0006 is the times_v2 data rewrite. Why: every step's `down` then restores exactly the shape before it. A database made before the runner is recognised because every `up` is idempotent (create-if-missing, add-column-if-missing, the times marker), so they run, change nothing and are recorded. Undo: revert the M0 commit (the `schema_migrations` table is harmless to the old code).
- M0: 0001's `down` refuses while any table holds rows (it never deletes data); 0006's `down` is a no-op that keeps the `times_v2` marker (the time rewrite is one-way; re-running it after a down would rewrite rows written since). Undo: edit those `down` functions.
- M0: the runner runs at every `Database(...)` open; each step is one transaction and is skipped if another process recorded it meanwhile.
