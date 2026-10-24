"""The database behind videos, projects (folders), chat and spend (Phase 9):
SQLite by default, Postgres when the path is a postgres:// URL (launch, item 6;
see `app.store.pg`).

One connection, shared across request and job-worker threads under a lock —
the write volume is a handful of rows per edit, so contention is not a
concern, and one connection keeps `:memory:` databases (tests) coherent.
"""
from __future__ import annotations

import os
import sqlite3
import threading
import weakref
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.store import migrate, pg

# The tables keyed by a video's id (their `project_id` column is the video id,
# from before projects were folders).
PROJECT_TABLES = ("candidates", "edits", "messages", "usage", "plans", "turns", "jobs")
# The projects plan's own tables (F2 on), emptied by reset() too.
EXTRA_TABLES = ("project_briefs", "project_rules", "project_events", "purged_items",
                "project_checks", "project_issues", "project_issue_ignores", "share_tokens",
                "export_presets", "review_comments", "notify_queue", "notify_outbox", "pins",
                "project_templates", "proposal_decisions", "learned_items",
                "workspace_members", "workspace_invites", "login_links",
                "notifications", "notification_settings", "spend_alerts",
                "analytics_events", "feedback", "error_reports",
                "billing_accounts", "credit_grants", "invoices",
                "liveness_attempts", "abuse_reports", "data_requests", "provenance_marks",
                "member_shares", "accounts", "auth_tokens", "content_cache")


def location(default: str | Path) -> str | Path:
    """Where the app's database is: `DATABASE_URL` when it is a postgres://
    URL, else `default` (the SQLite file)."""
    url = os.environ.get("DATABASE_URL", "")
    return url if pg.is_url(url) else default


class Database:
    def __init__(self, path: str | Path = ":memory:") -> None:
        on_pg = pg.target(path)
        self.dialect = "postgres" if on_pg else "sqlite"
        if on_pg:
            url, schema, throwaway = on_pg
            self._conn = pg.connect(url, schema)
            weakref.finalize(self, self._conn.close, throwaway)
        else:
            if path != ":memory:":
                Path(path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            if path != ":memory:" and not on_pg:
                self._conn.execute("PRAGMA journal_mode=WAL")
            # The chaos pass: another process on the same file (a second server,
            # a script) holds a write lock for a moment; wait up to 5 s rather
            # than failing the request with "database is locked".
            self._conn.execute("PRAGMA busy_timeout=5000")
            # Step 0 (M0): the schema is the numbered migrations, applied in
            # order and recorded; a database made before them is recognised
            # (each step is idempotent) and marked applied.
            ran = migrate.up(self._conn)
            self.migrated_projects_to_videos = bool(ran.get(1))
            self.migrated_times = ran.get(6) or 0

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """One transaction, exclusive to the calling thread."""
        with self._lock:
            if self.dialect == "postgres":
                self._begin_pg()
            else:
                self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except BaseException:
                try:
                    self._conn.execute("ROLLBACK")
                except Exception:  # noqa: BLE001 - the connection died mid-transaction; the next tx reconnects
                    if self.dialect != "postgres":
                        raise
                raise
            self._conn.execute("COMMIT")

    def _begin_pg(self) -> None:
        """BEGIN on Postgres, opening the connection again first when the server
        restarted (rehearsal item 4): the request after a restart succeeds."""
        self._conn.ensure()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
        except Exception:  # noqa: BLE001 - psycopg.OperationalError: the socket died while idle
            if self._conn.alive():
                raise
            self._conn.raw.close()
            self._conn.ensure()
            self._conn.execute("BEGIN IMMEDIATE")

    def reset(self) -> None:
        """Empty every table. Intended for test isolation."""
        with self.tx() as c:
            for table in ("meta", "videos", "projects", "feature_flags", "workspaces", *EXTRA_TABLES, *PROJECT_TABLES):
                c.execute(f"DELETE FROM {table}")
