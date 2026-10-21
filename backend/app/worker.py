"""The worker (launch item 8): the periodic maintenance, in a process of its own.

    python -m app.worker              # a pass every minute, until stopped
    python -m app.worker --once       # one pass, then exit (a check, or cron)

Each pass may do two things, each behind its own switch:

- the review digests that are due (C2), with AVE_WORKER_DIGESTS=1. The API
  process still runs its own digest scheduler (app/api/main.py), so leave this
  off until that one is switched off, or an owner can get the same digest twice.
- the Bin purge (D3/F8), with AVE_PURGE_DAILY=1: once a day, the first a day
  after start, so a restart never purges at once (as `PurgeScheduler`). Set
  AVE_PURGE_DAILY on the worker only, not on the API, or both purge.

Everything a request starts (turns, renders, exports, imports) still runs on
threads inside the API process; this worker takes none of it yet.
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("ave.worker")

DIGEST_EVERY_S = 60.0
PURGE_EVERY_S = 24 * 3600.0
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass
class Worker:
    """One pass is `tick()`. `digests` and `purge` are None when switched off."""

    digests: Callable[[], object] | None = None
    purge: Callable[[], object] | None = None
    purge_every: float = PURGE_EVERY_S
    clock: Callable[[], float] = time.monotonic
    _next_purge: float | None = None

    def tick(self) -> dict:
        """Run what is due; a failure in one task is logged and never stops the other."""
        now = self.clock()
        ran: dict = {}
        if self.digests is not None:
            try:
                sent = self.digests()
                ran["digests"] = len(sent) if isinstance(sent, list) else 0
            except Exception:  # noqa: BLE001 - the next pass tries again
                log.exception("review digests")
                ran["digests"] = "failed"
        if self.purge is not None:
            if self._next_purge is None:
                self._next_purge = now + self.purge_every
            elif now >= self._next_purge:
                self._next_purge = now + self.purge_every
                try:
                    report = self.purge()
                    log.info("daily purge: %s", getattr(report, "to_dict", lambda: report)())
                    ran["purge"] = "done"
                except Exception:  # noqa: BLE001 - tomorrow tries again
                    log.exception("daily purge")
                    ran["purge"] = "failed"
        return ran


def build(settings=None, environ: dict | None = None) -> Worker:
    """The worker as the app's settings describe it, on the app's own database."""
    from app.config import load_settings
    from app.notify import digest as digest_mod, email as email_mod
    from app.purge import _vendor_delete, purge
    from app.store import bin as bin_store
    from app.store.db import Database
    from app.store.repository import LOCAL_OWNER

    settings = settings or load_settings()
    env = os.environ if environ is None else environ
    database = Database(settings.data_dir / "ave.db")

    digests = None
    if env.get("AVE_WORKER_DIGESTS", "").strip().lower() in _TRUTHY:
        sender = email_mod.sender_for(settings.email_provider, database)

        def link_for(item: dict) -> str | None:     # as flush_review_digests in app/api/main.py
            if item.get("project_id"):
                return f"{settings.public_url}/#p/{item['project_id']}"
            return f"{settings.public_url}/#v/{item['video_id']}" if item.get("video_id") else None

        def digests() -> list:
            return digest_mod.flush(
                database, sender, digest_mod.utcnow(),
                lambda owner: email_mod.address_for(
                    database, owner, settings.notify_owner_email if owner == LOCAL_OWNER else None),
                link_for)

    purge_due = None
    if settings.purge_daily:
        def purge_due():
            return purge(database, settings.data_dir / "artifacts", bin_store.BIN_DAYS,
                         delete_voice=_vendor_delete(settings, database, settings.data_dir),
                         consent_years=settings.consent_retention_years)

    return Worker(digests=digests, purge=purge_due)


def run(worker: Worker, every: float = DIGEST_EVERY_S, stop: threading.Event | None = None) -> None:
    """A pass now, then one every `every` seconds until `stop` is set."""
    stop = stop or threading.Event()
    while True:
        worker.tick()
        if stop.wait(every):
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.worker",
                                     description="Run Voltage's periodic maintenance (digests, the daily purge).")
    parser.add_argument("--once", action="store_true", help="one pass, then exit")
    parser.add_argument("--every", type=float, default=DIGEST_EVERY_S, help="seconds between passes (default 60)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    worker = build()
    log.info("worker up: digests %s, daily purge %s",
             "on" if worker.digests else "off", "on" if worker.purge else "off")
    if args.once:
        print(worker.tick())
        return 0
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    run(worker, args.every, stop)
    log.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
