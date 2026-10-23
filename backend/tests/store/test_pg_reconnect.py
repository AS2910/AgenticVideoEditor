"""Rehearsal item 4: Postgres restarted under a running app. The next
transaction opens the connection again instead of failing every request
until the app restarts."""
import threading

import pytest

from app.store import pg
from app.store.db import Database


class DeadSocket(Exception):
    pass


class FakeRaw:
    """Enough of a psycopg connection: answers until the 'server' restarts."""
    def __init__(self, server):
        self.server, self.generation, self.closed, self.broken = server, server["generation"], False, False
        self.sent = []

    def execute(self, sql, params=None):
        if self.closed:
            raise DeadSocket("the connection is closed")
        if self.generation != self.server["generation"]:
            self.broken = True
            raise DeadSocket("server closed the connection unexpectedly")
        self.sent.append(sql)
        return type("Cur", (), {"description": None, "rowcount": 0, "fetchall": lambda self: []})()

    def close(self):
        self.closed = True


def pg_database(monkeypatch, server):
    monkeypatch.setattr(pg, "_open", lambda url, schema: FakeRaw(server))
    db = Database.__new__(Database)
    db.dialect = "postgres"
    db._conn = pg.connect("postgresql://x/y")
    db._lock = threading.RLock()
    return db


def test_the_first_transaction_after_a_restart_reconnects(monkeypatch):
    server = {"generation": 1}
    db = pg_database(monkeypatch, server)
    with db.tx() as c:
        c.execute("SELECT 1")
    first = db._conn.raw
    server["generation"] = 2                        # Postgres restarted: the old socket is dead
    with db.tx() as c:
        c.execute("SELECT 1")
    assert db._conn.raw is not first and first.closed
    assert db._conn.raw.sent[-1].strip().upper() == "COMMIT"


def test_a_transaction_cut_off_midway_fails_once_and_the_next_one_works(monkeypatch):
    server = {"generation": 1}
    db = pg_database(monkeypatch, server)
    with pytest.raises(DeadSocket):
        with db.tx() as c:
            server["generation"] = 2
            c.execute("SELECT 1")                   # dies here; ROLLBACK cannot be sent either
    with db.tx() as c:
        c.execute("SELECT 1")
    assert db._conn.raw.generation == 2
