"""One edit at a time per video (2026-10-25): the video lock.

A video is Ready (no row) or Working (one row in `video_locks`). Working
starts when an action that changes the video starts (a Voltage turn, an Add,
a Discard, an undo...) and ends when it lands, fails or is stopped. A turn
that waits for the user's go keeps it.

    take(video_id, holder, action, ...)      raises VideoBusy while someone else holds it
    take_in(c, ...)                          the same, inside the caller's transaction
    hand(video_id, old, new, ...)            a request's lock passed to the job or turn it started
    release(video_id, holder, outcome)       only the holder releases; `on_release` hears it
    renew(video_id, holder) / renew_live()   the lease, pushed on while the holder runs
    sweep()                                  expired leases cleared (the stuck-job sweep calls it)

A lease is LEASE seconds and renewed every RENEW while its holder is alive in
this process (`alive(holder)`); a server that dies stops renewing, and the
sweep clears the row once the lease runs out. A turn waiting for the user's
go holds a `gate:` lock with a long lease (nothing runs while it waits).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

from app.store.db import Database
from app.timefmt import now_iso

log = logging.getLogger("voltage.locks")

LEASE = 90.0
RENEW = 30.0
GATE_LEASE = 7 * 24 * 3600.0       # a go waits as long as the user takes; Stop or an answer ends it
GATE = "gate:"
REQUEST = "req-"


@dataclass(frozen=True)
class Lock:
    video_id: str
    holder: str
    action: str
    started_by: str | None = None
    started_by_name: str | None = None
    tab: str | None = None
    started_at: str = ""
    lease_expires_at: float = 0.0
    stoppable: bool = True
    snapshot: dict | None = field(default=None, compare=False)

    @property
    def gate(self) -> bool:
        return self.holder.startswith(GATE)

    def to_dict(self) -> dict:
        """What the editor reads (the snapshot stays on the server)."""
        return {"video_id": self.video_id, "holder": self.holder, "action": self.action,
                "started_by": self.started_by, "started_by_name": self.started_by_name, "tab": self.tab,
                "started_at": self.started_at, "stoppable": self.stoppable, "waiting": self.gate,
                "lease_expires_at": datetime.fromtimestamp(self.lease_expires_at, timezone.utc).isoformat().replace("+00:00", "Z")}


class VideoBusy(RuntimeError):
    """Someone else holds the video. `lock` is what holds it."""

    def __init__(self, lock: Lock) -> None:
        super().__init__(f"{lock.video_id} is busy with {lock.action}")
        self.lock = lock


def _row(r) -> Lock:
    return Lock(video_id=r["video_id"], holder=r["holder"], action=r["action"], started_by=r["started_by"],
                started_by_name=r["started_by_name"], tab=r["tab"], started_at=r["started_at"],
                lease_expires_at=float(r["lease_expires_at"]), stoppable=bool(r["stoppable"]),
                snapshot=json.loads(r["snapshot"]) if r["snapshot"] else None)


class VideoLocks:
    """The locks, persisted. `on_change(video_id, lock_or_None, outcome)` hears every
    take, hand and release (the event bus and the queue); it runs after the transaction."""

    def __init__(self, db: Database, clock: Callable[[], float] = time.time,
                 on_change: Callable[[str, Lock | None, str | None], None] | None = None) -> None:
        self.db = db
        self.clock = clock
        self.on_change = on_change
        self._renewer: threading.Thread | None = None
        self._stop = threading.Event()

    # ── reading ──────────────────────────────────────────────────────────
    def get(self, video_id: str) -> Lock | None:
        """The lock in force, or None. An expired one reads as none (the sweep clears it)."""
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM video_locks WHERE video_id = ?", (video_id,)).fetchone()
        lock = _row(r) if r else None
        return lock if lock is not None and lock.lease_expires_at > self.clock() else None

    def all(self) -> list[Lock]:
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_locks").fetchall()
        return [_row(r) for r in rows]

    # ── taking ───────────────────────────────────────────────────────────
    def take_in(self, c, video_id: str, holder: str, action: str, *, started_by: str | None = None,
                started_by_name: str | None = None, tab: str | None = None, lease: float = LEASE,
                stoppable: bool = True, snapshot: dict | None = None,
                over: Callable[[Lock], bool] | None = None) -> Lock:
        """Take the lock inside the caller's transaction. Free, expired, already
        ours, or one `over(lock)` says may be taken over (a turn answering the
        go its own gate waits for): taken. Anything else raises VideoBusy."""
        now = self.clock()
        r = c.execute("SELECT * FROM video_locks WHERE video_id = ?", (video_id,)).fetchone()
        held = _row(r) if r else None
        if held is not None and held.lease_expires_at > now and held.holder != holder and not (over and over(held)):
            raise VideoBusy(held)
        lock = Lock(video_id=video_id, holder=holder, action=action, started_by=started_by,
                    started_by_name=started_by_name, tab=tab, started_at=now_iso(),
                    lease_expires_at=now + lease, stoppable=stoppable, snapshot=snapshot)
        if held is not None:
            c.execute("DELETE FROM video_locks WHERE video_id = ?", (video_id,))
        c.execute("INSERT INTO video_locks (video_id, holder, action, started_by, started_by_name, tab, started_at, "
                  "lease_expires_at, stoppable, snapshot, workspace_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                  "(SELECT workspace_id FROM videos WHERE id = ?))",
                  (video_id, holder, action, started_by, started_by_name, tab, lock.started_at, lock.lease_expires_at,
                   1 if stoppable else 0, json.dumps(snapshot) if snapshot is not None else None, video_id))
        return lock

    def take(self, video_id: str, holder: str, action: str, **kw) -> Lock:
        try:
            with self.db.tx() as c:
                lock = self.take_in(c, video_id, holder, action, **kw)
        except VideoBusy:
            raise
        except Exception as exc:  # noqa: BLE001 - checked below: only a lost race on the row is busy
            # Addendum 3: two servers (Postgres, several workers) racing for a Ready video: both read no
            # row, one INSERT wins and the other hits the primary key. The loser is busy, never a 500.
            if "unique" not in str(exc).lower() and "integrity" not in type(exc).__name__.lower():
                raise
            held = self.get(video_id)
            raise VideoBusy(held or Lock(video_id=video_id, holder="?", action=action)) from None
        self._tell(video_id, lock, None)
        return lock

    def hand_in(self, c, video_id: str, old: str, new: str, *, action: str | None = None, lease: float | None = None,
                stoppable: bool | None = None, snapshot: dict | None = None) -> Lock | None:
        """The lock passed from `old` to `new` inside the caller's transaction
        (the job that takes it over is made in the same step). None when `old`
        no longer holds it."""
        r = c.execute("SELECT * FROM video_locks WHERE video_id = ? AND holder = ?", (video_id, old)).fetchone()
        if r is None:
            return None
        sets = {"holder": new, "lease_expires_at": self.clock() + (lease if lease is not None else LEASE)}
        if action is not None:
            sets["action"] = action
        if stoppable is not None:
            sets["stoppable"] = 1 if stoppable else 0
        if snapshot is not None:
            sets["snapshot"] = json.dumps(snapshot)
        c.execute(f"UPDATE video_locks SET {', '.join(f'{k} = ?' for k in sets)} WHERE video_id = ? AND holder = ?",
                  (*sets.values(), video_id, old))
        return _row(c.execute("SELECT * FROM video_locks WHERE video_id = ?", (video_id,)).fetchone())

    def hand(self, video_id: str, old: str, new: str, **kw) -> Lock | None:
        """The lock passed from `old` to `new` (a request's lock to the turn it
        started; a turn's to its gate). None when `old` no longer holds it."""
        with self.db.tx() as c:
            lock = self.hand_in(c, video_id, old, new, **kw)
        if lock is not None:
            self._tell(video_id, lock, None)
        return lock

    def told(self, video_id: str) -> None:
        """Tell the listeners what holds the video now (after a hand made inside another transaction)."""
        self._tell(video_id, self.get(video_id), None)

    def set_snapshot(self, video_id: str, holder: str, snapshot: dict) -> bool:
        with self.db.tx() as c:
            n = c.execute("UPDATE video_locks SET snapshot = ? WHERE video_id = ? AND holder = ?",
                          (json.dumps(snapshot), video_id, holder)).rowcount
        return bool(n)

    def relabel(self, video_id: str, holder: str, action: str) -> bool:
        """The action's words changed ("Voltage is planning" -> "Voicing line 2 of 5")."""
        with self.db.tx() as c:
            r = c.execute("SELECT action FROM video_locks WHERE video_id = ? AND holder = ?", (video_id, holder)).fetchone()
            if r is None or r["action"] == action:
                return False
            c.execute("UPDATE video_locks SET action = ? WHERE video_id = ? AND holder = ?", (action, video_id, holder))
        lock = self.get(video_id)
        if lock is not None:
            self._tell(video_id, lock, None)
        return True

    # ── releasing ────────────────────────────────────────────────────────
    def release(self, video_id: str, holder: str, outcome: str = "done") -> bool:
        """Only the holder releases. `outcome` (done | failed | stopped |
        expired) is what the queue hears: after a success it runs the next item."""
        with self.db.tx() as c:
            n = c.execute("DELETE FROM video_locks WHERE video_id = ? AND holder = ?", (video_id, holder)).rowcount
        if n:
            self._tell(video_id, None, outcome)
        return bool(n)

    def release_in(self, c, video_id: str, holder: str, outcome: str = "done") -> Callable[[], None] | None:
        """Release inside the caller's transaction (a job's end): returns the news to tell after it."""
        n = c.execute("DELETE FROM video_locks WHERE video_id = ? AND holder = ?", (video_id, holder)).rowcount
        return (lambda: self._tell(video_id, None, outcome)) if n else None

    def release_any(self, video_id: str, outcome: str = "stopped") -> Lock | None:
        """Stop: whatever holds the video lets go. Returns what held it."""
        with self.db.tx() as c:
            r = c.execute("SELECT * FROM video_locks WHERE video_id = ?", (video_id,)).fetchone()
            if r is None:
                return None
            c.execute("DELETE FROM video_locks WHERE video_id = ?", (video_id,))
        self._tell(video_id, None, outcome)
        return _row(r)

    # ── the lease ────────────────────────────────────────────────────────
    def renew(self, video_id: str, holder: str, lease: float = LEASE) -> bool:
        with self.db.tx() as c:
            n = c.execute("UPDATE video_locks SET lease_expires_at = ? WHERE video_id = ? AND holder = ?",
                          (self.clock() + lease, video_id, holder)).rowcount
        return bool(n)

    def renew_live(self, alive: Callable[[Lock], bool]) -> int:
        """Every lock whose holder still runs here gets a fresh lease (a gate's is long already)."""
        n = 0
        for lock in self.all():
            if not lock.gate and lock.lease_expires_at > self.clock() and alive(lock):
                n += self.renew(lock.video_id, lock.holder)
        return n

    def sweep(self) -> list[Lock]:
        """Expired leases cleared: the holder died (a crash, a hung worker) and nobody renewed it."""
        now = self.clock()
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_locks WHERE lease_expires_at <= ?", (now,)).fetchall()
            for r in rows:
                c.execute("DELETE FROM video_locks WHERE video_id = ? AND holder = ?", (r["video_id"], r["holder"]))
        gone = [_row(r) for r in rows]
        for lock in gone:
            log.warning("lock on %s (%s, %s) expired; cleared", lock.video_id, lock.holder, lock.action)
            self._tell(lock.video_id, None, "expired")
        return gone

    def clear_leftovers(self) -> list[Lock]:
        """At startup: a previous server's running work can never land now; its
        locks go (a gate waiting for the user's go is kept: nothing was running)."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM video_locks").fetchall()
            gone = [_row(r) for r in rows if not str(r["holder"]).startswith(GATE)]
            for lock in gone:
                c.execute("DELETE FROM video_locks WHERE video_id = ? AND holder = ?", (lock.video_id, lock.holder))
        return gone

    def start_renewing(self, alive: Callable[[Lock], bool], every: float = RENEW) -> None:
        if self._renewer is not None:
            return

        def loop() -> None:
            while not self._stop.wait(every):
                try:
                    self.renew_live(alive)
                except Exception:  # noqa: BLE001 - a missed renewal is retried next tick
                    log.exception("lock renewal failed")
        self._renewer = threading.Thread(target=loop, name="ave-lock-renew", daemon=True)
        self._renewer.start()

    def _tell(self, video_id: str, lock: Lock | None, outcome: str | None) -> None:
        if self.on_change is not None:
            try:
                self.on_change(video_id, lock, outcome)
            except Exception:  # noqa: BLE001 - a listener never breaks the lock
                log.exception("lock listener failed for %s", video_id)
