# Overnight progress: Voltage Projects Build Plan

Branch `overnight/projects-plan` (from main `217db2d`). Spec: docs/overnight/PLAN.md. Agent brief: docs/overnight/BRIEF.md.

| Step | Item | Status | Commit | What to check |
|---|---|---|---|---|
| 0 | Migration runner, flags, workspace_id | in progress | | |
| 0 | M0 · Numbered migration runner | done | (M0) | `python -m app.store.migrate status --db backend/var/ave.db` on your live DB lists 0001 to 0006 applied after the next server start (it records them, changes nothing). Live-copy proof below. |

### M0 live-DB copy proof (copy of `ave.db`, never the original)
Row counts per table before, after `up`, after `down`, after `up` again (all equal):
candidates 49, edits 41, jobs 11, messages 165, meta 10, plans 9, projects 2, turns 193, usage 225, videos 5.
- `up` on the copy ran 0001 to 0006, schema unchanged (column sets identical), every row identical.
- `down 1` (0006) then `up`: every row identical.
- `down 5` (0006 to 0002): counts equal, the later columns dropped (videos speakers/settings/project_id, messages kind/cost/data, usage folder_id/turn_id); `up` again restores the identical shape (values in those columns come back as their defaults, as a down must).
