"""G8: the error-reporting hook, behind an interface (Sentry-like).

    reporter.capture_exception(exc, context={...})   an exception, with where it happened
    reporter.capture_message(message, level="error", context={...})

Providers: `LogReporter` (the default: writes the report to the log and to
`error_reports` when a database is given, sends nothing anywhere) and
`SentryReporter`, the shape a real one takes: it reads `SENTRY_DSN` but is
NOT connected (no SDK, no network); until someone sets it up it behaves like
the log provider and says so once (SETUP_NEEDED.md). `reporter_for(dsn, db)`
picks one. A report never raises: losing a report never breaks the request.
"""
from __future__ import annotations

import json
import logging
import traceback
from typing import Protocol

from app.timefmt import now_iso

log = logging.getLogger("voltage.errors")
MAX_TEXT = 4000


class ErrorReporter(Protocol):
    name: str

    def capture_exception(self, exc: BaseException, context: dict | None = None) -> None: ...

    def capture_message(self, message: str, level: str = "error", context: dict | None = None) -> None: ...


def store(db, *, source: str, message: str, stack: str = "", location: str = "", owner: str | None = None,
          context: dict | None = None) -> None:
    """One report in `error_reports` (the admin page lists the newest)."""
    if db is None:
        return
    try:
        with db.tx() as c:
            c.execute("INSERT INTO error_reports (owner, source, message, stack, location, context, at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (owner, source, message[:MAX_TEXT], stack[:MAX_TEXT], location[:500],
                       json.dumps(context or {}, default=str)[:MAX_TEXT], now_iso()))
    except Exception:  # noqa: BLE001 - a report never breaks what it reports
        log.exception("could not store an error report")


class LogReporter:
    """The no-op provider: the log and the local table, nothing leaves the machine."""

    name = "log"

    def __init__(self, db=None) -> None:
        self.db = db

    def capture_exception(self, exc: BaseException, context: dict | None = None) -> None:
        context = dict(context or {})
        stack = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        log.error("captured %s: %s %s", type(exc).__name__, exc, json.dumps(context, default=str)[:500])
        store(self.db, source=context.pop("source", "server"), message=f"{type(exc).__name__}: {exc}", stack=stack,
              location=str(context.pop("where", "")), owner=context.pop("owner", None), context=context)

    def capture_message(self, message: str, level: str = "error", context: dict | None = None) -> None:
        context = dict(context or {})
        log.log(logging.ERROR if level == "error" else logging.WARNING, "captured message: %s", message[:500])
        store(self.db, source=context.pop("source", "server"), message=message, stack=str(context.pop("stack", "")),
              location=str(context.pop("where", "")), owner=context.pop("owner", None), context={"level": level, **context})


class SentryReporter(LogReporter):
    """Where a real Sentry client goes. NOT connected: no SDK is installed and
    nothing is sent; with a DSN set it reports locally and says once that it
    is not wired yet. To connect: install `sentry-sdk`, call
    `sentry_sdk.init(dsn)` here, and forward both methods."""

    name = "sentry (not connected)"

    def __init__(self, dsn: str, db=None) -> None:
        super().__init__(db)
        self.dsn = dsn
        self._said = False

    def _say_once(self) -> None:
        if not self._said:
            self._said = True
            log.warning("SENTRY_DSN is set but the Sentry provider is not connected; reports stay local (SETUP_NEEDED.md).")

    def capture_exception(self, exc: BaseException, context: dict | None = None) -> None:
        self._say_once()
        super().capture_exception(exc, context)

    def capture_message(self, message: str, level: str = "error", context: dict | None = None) -> None:
        self._say_once()
        super().capture_message(message, level, context)


def reporter_for(dsn: str | None, db=None) -> ErrorReporter:
    return SentryReporter(dsn, db) if dsn else LogReporter(db)
