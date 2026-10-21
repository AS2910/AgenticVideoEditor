"""G8: the error-reporting hook, behind an interface (Sentry-like).

    reporter.capture_exception(exc, context={...})   an exception, with where it happened
    reporter.capture_message(message, level="error", context={...})

Providers: `LogReporter` (the default: writes the report to the log and to
`error_reports` when a database is given, sends nothing anywhere) and, item
7, `SentryReporter`: the same, plus an event posted to the DSN's envelope
endpoint over httpx (no SDK), scrubbed of secrets. `reporter_for(dsn, db)`
picks Sentry only when `SENTRY_DSN` is set. A report never raises: losing a
report never breaks the request.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlparse

import httpx

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


_SECRET_KEYS = re.compile(r"cookie|authori[sz]ation|password|passwd|secret|token|api[_-]?key|session|signature|dsn|body|payload",
                          re.IGNORECASE)
_SECRET_TEXT = re.compile(r"\b(?:sk|rk|pk|whsec)_(?:live|test)?_?[A-Za-z0-9]{8,}|\brzp_(?:live|test)_[A-Za-z0-9]+"
                          r"|\bBearer\s+\S+|\bBasic\s+\S+|\bre_[A-Za-z0-9_]{16,}", re.IGNORECASE)


def scrub(value, depth: int = 0):
    """A copy safe to send: secret-looking keys dropped, key-shaped strings masked."""
    if depth > 4:
        return "[deep]"
    if isinstance(value, dict):
        return {str(k): ("[removed]" if _SECRET_KEYS.search(str(k)) else scrub(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [scrub(v, depth + 1) for v in list(value)[:50]]
    if isinstance(value, str):
        return _SECRET_TEXT.sub("[removed]", value[:MAX_TEXT])
    if value is None or isinstance(value, (int, float, bool)):
        return value
    return scrub(str(value), depth + 1)


@dataclass(frozen=True)
class Dsn:
    key: str
    envelope_url: str

    @classmethod
    def parse(cls, dsn: str) -> Dsn | None:
        """`https://<key>@<host>/<project_id>` (a path before the id is kept)."""
        u = urlparse(dsn or "")
        project = u.path.rstrip("/").rsplit("/", 1)
        if u.scheme not in ("http", "https") or not u.username or not u.hostname or len(project) != 2 or not project[1]:
            return None
        host = u.hostname + (f":{u.port}" if u.port else "")
        return cls(u.username, f"{u.scheme}://{host}{project[0]}/api/{project[1]}/envelope/")


class SentryReporter(LogReporter):
    """Item 7: Sentry without the SDK. Every report is still logged and kept
    locally, then posted to the DSN's envelope endpoint over httpx, in the
    background (a report never slows or breaks a request). No request
    bodies, cookies, authorization or secret-looking values go out."""

    name = "sentry"
    TIMEOUT = 5.0

    def __init__(self, dsn: str, db=None, client: httpx.Client | None = None,
                 submit: Callable[[Callable[[], None]], None] | None = None, environment: str = "production") -> None:
        super().__init__(db)
        self.dsn = Dsn.parse(dsn)
        if self.dsn is None:
            self.name = "sentry (bad DSN: local only)"
            log.warning("SENTRY_DSN does not look like https://<key>@<host>/<project_id>; reports stay local.")
        self.client = client
        self.environment = environment
        self.submit = submit or (lambda send: threading.Thread(target=send, daemon=True, name="sentry-send").start())

    def _event(self, level: str, context: dict) -> dict:
        context = dict(context)
        tags = {k: str(context.pop(k))[:200] for k in ("source", "where") if context.get(k)}
        owner = context.pop("owner", None)
        event = {"event_id": uuid.uuid4().hex, "timestamp": now_iso(), "platform": "python", "level": level,
                 "logger": "voltage", "environment": self.environment, "tags": scrub(tags), "extra": scrub(context)}
        if owner:
            event["user"] = {"id": str(owner)}
        return event

    def _post(self, event: dict) -> None:
        if self.dsn is None:
            return
        head = {"event_id": event["event_id"], "sent_at": now_iso()}
        payload = json.dumps(event, default=str)
        envelope = "\n".join((json.dumps(head), json.dumps({"type": "event", "length": len(payload.encode())}), payload)) + "\n"
        auth = f"Sentry sentry_version=7, sentry_key={self.dsn.key}, sentry_client=voltage/1.0"
        url = self.dsn.envelope_url

        def send() -> None:
            try:
                client = self.client or httpx.Client()
                r = client.post(url, content=envelope.encode(), timeout=self.TIMEOUT,
                                headers={"Content-Type": "application/x-sentry-envelope", "X-Sentry-Auth": auth})
                if r.status_code >= 300:
                    log.warning("sentry answered %s; the report is kept locally", r.status_code)
            except Exception:  # noqa: BLE001 - losing a report never breaks anything
                log.warning("could not reach sentry; the report is kept locally")
        try:
            self.submit(send)
        except Exception:  # noqa: BLE001
            log.warning("could not queue a sentry report")

    def capture_exception(self, exc: BaseException, context: dict | None = None) -> None:
        super().capture_exception(exc, context)
        try:
            event = self._event("error", context or {})
            frames = [{"filename": f.filename.rsplit("/app/", 1)[-1], "function": f.name, "lineno": f.lineno}
                      for f in traceback.extract_tb(exc.__traceback__)][-50:]
            event["exception"] = {"values": [{"type": type(exc).__name__, "value": scrub(str(exc)),
                                              "stacktrace": {"frames": frames}}]}
            self._post(event)
        except Exception:  # noqa: BLE001
            log.warning("could not build a sentry report")

    def capture_message(self, message: str, level: str = "error", context: dict | None = None) -> None:
        super().capture_message(message, level, context)
        try:
            context = dict(context or {})
            stack = context.pop("stack", None)
            event = self._event(level if level in ("fatal", "error", "warning", "info", "debug") else "error", context)
            event["message"] = {"formatted": scrub(message)}
            if stack:
                event["extra"]["stack"] = scrub(str(stack))
            self._post(event)
        except Exception:  # noqa: BLE001
            log.warning("could not build a sentry report")


def reporter_for(dsn: str | None, db=None) -> ErrorReporter:
    return SentryReporter(dsn, db) if dsn else LogReporter(db)
