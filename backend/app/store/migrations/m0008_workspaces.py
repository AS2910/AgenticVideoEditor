"""0008 (WS): workspaces. One per owner for now (their own); every user-data
table gets a `workspace_id`, backfilled to the owner's workspace. Reads do
not filter on it yet (row-level security waits for G5).

Backfill: a workspace for every owner of a video or project; videos and
projects take their owner's; rows keyed by a video take that video's, and a
project-level charge (no video) takes its project's. A row whose video and
project are both gone keeps NULL: there is no owner to give it to.
Returns how many rows were backfilled.
"""
from __future__ import annotations

from app.store.migrations._util import add_column, drop_column, tables

# Every table that holds a user's data. `meta` and `feature_flags` are keyed by owner already.
OWNED = ("videos", "projects")
BY_VIDEO = ("candidates", "edits", "messages", "turns", "plans", "usage", "jobs")
INDEXES = (("videos_by_workspace", "videos"), ("projects_by_workspace", "projects"))


def up(conn) -> int:
    from app.timefmt import now_iso
    conn.execute("""CREATE TABLE IF NOT EXISTS workspaces (
    id         TEXT PRIMARY KEY,       -- w<n>
    name       TEXT NOT NULL,
    owner      TEXT NOT NULL,          -- whose own workspace it is
    created_at TEXT NOT NULL
)""")
    conn.execute("CREATE INDEX IF NOT EXISTS workspaces_by_owner ON workspaces (owner)")
    for table in (*OWNED, *BY_VIDEO):
        add_column(conn, table, "workspace_id", "TEXT")
    for name, table in INDEXES:
        conn.execute(f"CREATE INDEX IF NOT EXISTS {name} ON {table} (workspace_id)")

    owners = [r[0] for r in conn.execute(
        "SELECT owner FROM videos UNION SELECT owner FROM projects ORDER BY owner")]
    for owner in owners:
        ensure(conn, owner, now_iso())
    changed = 0
    for table in OWNED:
        changed += conn.execute(
            f"UPDATE {table} SET workspace_id = (SELECT id FROM workspaces w WHERE w.owner = {table}.owner "
            f"ORDER BY w.created_at, w.id LIMIT 1) WHERE workspace_id IS NULL").rowcount
    for table in BY_VIDEO:
        changed += _backfill(conn, table)
    return changed


def _backfill(conn, table: str) -> int:
    folder = "COALESCE(t.folder_id, '')" if table == "usage" else "''"
    return conn.execute(
        f"UPDATE {table} AS t SET workspace_id = COALESCE("
        f"(SELECT workspace_id FROM videos v WHERE v.id = t.project_id), "
        f"(SELECT workspace_id FROM projects p WHERE p.id = {folder})) "
        f"WHERE t.workspace_id IS NULL AND COALESCE("
        f"(SELECT workspace_id FROM videos v WHERE v.id = t.project_id), "
        f"(SELECT workspace_id FROM projects p WHERE p.id = {folder})) IS NOT NULL").rowcount


def ensure(conn, owner: str, at: str) -> str:
    """The owner's own workspace, made if it is not there yet."""
    row = conn.execute("SELECT id FROM workspaces WHERE owner = ? ORDER BY created_at, id LIMIT 1", (owner,)).fetchone()
    if row:
        return row[0]
    n = conn.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM workspaces WHERE id = ?", (f"w{n}",)).fetchone():
        n += 1
    conn.execute("INSERT INTO workspaces (id, name, owner, created_at) VALUES (?, ?, ?, ?)",
                 (f"w{n}", "My workspace", owner, at))
    return f"w{n}"


def down(conn) -> None:
    for name, _ in INDEXES:
        conn.execute(f"DROP INDEX IF EXISTS {name}")
    for table in reversed((*OWNED, *BY_VIDEO)):
        drop_column(conn, table, "workspace_id")
    if "workspaces" in tables(conn):
        conn.execute("DROP INDEX IF EXISTS workspaces_by_owner")
        conn.execute("DROP TABLE workspaces")
