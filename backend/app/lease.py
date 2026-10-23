"""One API process per database (rehearsal item 1, launch blocker 8).

Rate limits, the day cap's pause and the job runner live in the API's own
memory, so a second API process on the same data would double them and run
jobs the first cannot see. At start the API takes a lease in `meta`
(`api_lease`: who, where, when last seen) and renews it every RENEW seconds.
A second process refuses to start while the lease is held by a live process:
on another host, one seen in the last TTL seconds; on this host, one whose pid
is still running. A crashed process's lease is taken over at once on the
same host (a container restart) and after TTL seconds elsewhere.
AVE_ALLOW_SECOND_API=1 skips the check (for a deliberate move to Redis).

    acquire(db) -> Lease      raises LeaseHeld with a sentence
    lease.release()
"""
from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
import uuid

from app.store.db import Database

log = logging.getLogger("voltage.lease")
KEY = "api_lease"
TTL = 90.0
RENEW = 30.0


class LeaseHeld(RuntimeError):
    pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read(db: Database) -> dict | None:
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (KEY,)).fetchone()
    try:
        return json.loads(row["value"]) if row else None
    except (TypeError, ValueError):
        return None


def _write(c, value: dict) -> None:
    c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
              (KEY, json.dumps(value)))


def holder_is_live(held: dict, me_host: str, now: float, ttl: float = TTL) -> bool:
    if held.get("host") == me_host:
        pid = int(held.get("pid") or 0)
        return pid != os.getpid() and pid > 0 and _alive(pid)
    return now - float(held.get("seen") or 0) < ttl


class Lease:
    def __init__(self, db: Database, lease_id: str, host: str) -> None:
        self.db, self.id, self.host = db, lease_id, host
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _value(self) -> dict:
        return {"id": self.id, "host": self.host, "pid": os.getpid(), "seen": time.time()}

    def renew(self) -> None:
        with self.db.tx() as c:
            _write(c, self._value())

    def start(self) -> None:
        def loop() -> None:
            while not self._stop.wait(RENEW):
                try:
                    self.renew()
                except Exception:  # noqa: BLE001 - a missed renewal only shortens the lease
                    log.exception("could not renew the API lease")
        self._thread = threading.Thread(target=loop, name="api-lease", daemon=True)
        self._thread.start()

    def release(self) -> None:
        self._stop.set()
        try:
            held = _read(self.db)
            if held and held.get("id") == self.id:
                with self.db.tx() as c:
                    c.execute("DELETE FROM meta WHERE key = ?", (KEY,))
        except Exception:  # noqa: BLE001 - shutting down
            log.exception("could not release the API lease")


def acquire(db: Database, host: str | None = None, now: float | None = None) -> Lease:
    host = host or socket.gethostname()
    now = time.time() if now is None else now
    if os.environ.get("AVE_ALLOW_SECOND_API", "").strip().lower() in {"1", "true", "yes", "on"}:
        lease = Lease(db, uuid.uuid4().hex, host)
        log.warning("AVE_ALLOW_SECOND_API is on: not checking for another API process")
        return lease
    with db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (KEY,)).fetchone()
        try:
            held = json.loads(row["value"]) if row else None
        except (TypeError, ValueError):
            held = None
        if held and holder_is_live(held, host, now):
            raise LeaseHeld(
                f"Another Voltage API process (host {held.get('host')}, pid {held.get('pid')}) is using this database. "
                "Run one API process only: rate limits, the spend pause and jobs live in its memory. "
                "Stop the other one, or wait 90 seconds if it has crashed.")
        lease = Lease(db, uuid.uuid4().hex, host)
        _write(c, lease._value())
    return lease
