# Overnight progress: Voltage Projects Build Plan

Branch `overnight/projects-plan` (from main `217db2d`). Spec: docs/overnight/PLAN.md. Agent brief: docs/overnight/BRIEF.md.

| Step | Item | Status | Commit | What to check |
|---|---|---|---|---|
| 0 | Migration runner, flags, workspace_id | done | 68e9c22, e4a627a, (WS) | see the three rows below |
| 0 | M0 · Numbered migration runner | done | 68e9c22 | `python -m app.store.migrate status --db backend/var/ave.db` on your live DB lists 0001 to 0006 applied after the next server start (it records them, changes nothing). Live-copy proof below. |
| 0 | FLAGS · Feature flags per owner | done | e4a627a | `GET /api/me/flags` returns the four phase flags and golive.g1 to g8 for `local`. Frontend: `useFlags()` in `frontend/src/flags/useFlags.ts` (`enabled('projects.batch')`). No UI yet. Live-copy proof: up 0007 adds `feature_flags` (0 rows), every other table's counts and rows identical; down drops it (shape identical to before); up again. |
| 0 | WS · Workspaces and workspace_id | done | (WS) | Migration 0008: `workspaces(id, name, owner, created_at)`, `workspace_id` on videos, projects, candidates, edits, messages, turns, plans, usage, jobs. Every write sets it (repository, ledger, voice budget, Activity jobs); reads unchanged (no RLS until G5). Live-copy proof: one workspace `w1` ("My workspace", owner `local`); every row of all nine tables backfilled to `w1` (videos 5, projects 2, candidates 49, edits 41, messages 165, turns 193, plans 9, usage 225, jobs 11), 0 left NULL; counts and original rows identical after up, down and up again; down removes the table, columns and indexes. |

### M0 live-DB copy proof (copy of `ave.db`, never the original)
Row counts per table before, after `up`, after `down`, after `up` again (all equal):
candidates 49, edits 41, jobs 11, messages 165, meta 10, plans 9, projects 2, turns 193, usage 225, videos 5.
- `up` on the copy ran 0001 to 0006, schema unchanged (column sets identical), every row identical.
- `down 1` (0006) then `up`: every row identical.
- `down 5` (0006 to 0002): counts equal, the later columns dropped (videos speakers/settings/project_id, messages kind/cost/data, usage folder_id/turn_id); `up` again restores the identical shape (values in those columns come back as their defaults, as a down must).
