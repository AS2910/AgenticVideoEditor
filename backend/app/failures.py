"""Run 5 item 1: honest error messages, one classifier for every failure a person can read.

Every place a failure reaches a person (an API answer, a job's reason, a line
in the chat, a toast) asks `say` (or `http`) for the sentence, and nothing
else. A failure is one of three things:

- our side: a bad or missing key, a vendor refusing our account, a quota, an
  outage, a timeout, a bug. The person reads OUR_END (the owner's words; a bug
  of ours where the spend is not known reads OUR_END_REPORTED instead); the
  real cause goes to the log, to `error_reports` (Admin > Feedback > Errors
  reported, and Sentry when SENTRY_DSN is set) and to every admin's bell and
  email digest as a `vendor_failure` notice, at most once per vendor and cause
  every ALERT_EVERY_S, so an outage is one notice, not hundreds.
- a vendor's safety filter refused the content (`SafetyRefused`): it says so
  and names the line, by its words and its time when known.
- the person's input (a file too big or of the wrong kind, a spending
  ceiling, a rate limit): the exception's own sentence, which is written for
  them and says what to change. These are the app's own exception types; a
  bare ValueError from a library is a bug, so it is ours.

Vendor and SDK text (status lines, docs links, "Check ANTHROPIC_API_KEY")
never reaches a person; it is in the log and the admin's report.

"Nothing was charged" must be true. A vendor call that fails is not billed
(ElevenLabs charges are held and refunded, budget.py; Claude and Whisper are
recorded only after a successful call). Work that paid for an earlier step
before failing passes what it spent (`spent_usd`) and the sentence says so.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.errors import NonRetryableError, SafetyRefused

log = logging.getLogger("voltage.failures")

OUR_SIDE, SAFETY, USER_INPUT = "our_side", "safety", "user_input"
OUR_END = "Something went wrong on our end. Nothing was charged. Try again in a minute."
# A bug of ours (not a vendor's failed call) where what was spent is not known: no promise about money.
OUR_END_REPORTED = "Something went wrong on our end. It has been reported. Try again in a minute."
ALERT_EVERY_S = 1800.0
ALERT_KEY = "vendor_alert:"
VENDOR_NAMES = {"anthropic": "Claude (Anthropic)", "elevenlabs": "ElevenLabs", "openai": "OpenAI transcription",
                "ffmpeg": "ffmpeg", "network": "the network", "server": "the server", "vendor": "A vendor"}
_WHAT = {"elevenlabs": "voice service", "anthropic": "AI service", "openai": "transcription service"}


@dataclass(frozen=True)
class Failure:
    kind: str              # OUR_SIDE, SAFETY or USER_INPUT
    text: str              # what the person reads
    cause: str = ""        # the real cause, for the log and the admins (never shown to the person)
    vendor: str | None = None
    status: int | None = None

    @property
    def key(self) -> str:
        """What counts as the same cause, for one admin notice per outage."""
        return f"{self.vendor or 'server'}:{self.reason}"

    @property
    def reason(self) -> str:
        """The cause in a few words, for the admin's notice."""
        low = self.cause.lower()
        if "is not set on this server" in low:
            return "no key is set"
        if self.status in (401, 403) or "api key" in low or "authentication" in low or "permission" in low:
            return "the key was refused"
        if "quota" in low or "voice slot" in low or "credit balance" in low:
            return "the account's quota is used up"
        if self.status == 429 or "ratelimit" in low or "overloaded" in low:
            return "rate limited"
        if self.status is not None and self.status >= 500:
            return "an outage"
        if "timeout" in low or "timed out" in low:
            return "a timeout"
        if "connect" in low or "unavailable" in low or "reset" in low:
            return "could not connect"
        if self.status is not None:
            return f"refused the request ({self.status})"
        return "an error"


# ── the classifier ───────────────────────────────────────────────────────────

_STATUS_IN_TEXT = re.compile(r"\((\d{3})\)")


def _status(exc: BaseException) -> int | None:
    code = getattr(exc, "status_code", None)
    if isinstance(code, int):
        return code
    found = _STATUS_IN_TEXT.search(str(exc))
    return int(found.group(1)) if found else None


def _vendor(exc: BaseException) -> str | None:
    if type(exc).__module__.startswith("anthropic"):
        return "anthropic"
    from app.adapters.claude_planner import PlannerConfigError, PlannerError
    from app.adapters.elevenlabs import VoiceConfigError, VoiceError
    from app.adapters.openai_whisper import TranscriptionError
    from app.media.ffmpeg import FFmpegError
    if isinstance(exc, (VoiceError, VoiceConfigError)):
        return "elevenlabs"
    if isinstance(exc, TranscriptionError):
        return "openai"
    if isinstance(exc, (PlannerError, PlannerConfigError)):
        return "anthropic"
    if isinstance(exc, FFmpegError):
        return "ffmpeg"
    from app.adapters.base import VendorError
    if isinstance(exc, VendorError):
        return "vendor"
    if type(exc).__module__.startswith(("httpx", "httpcore")):
        return "network"
    return None


def _cause(exc: BaseException) -> str:
    from app.errors_report import scrub
    text = " ".join(str(exc).split())[:400]
    return scrub(f"{type(exc).__name__}: {text}" if text else type(exc).__name__)


def safety_sentence(vendor: str | None, line_text: str | None, at: float | None) -> str:
    """The safety refusal, naming the line: its time and its words when known."""
    what = _WHAT.get(vendor or "", "voice service")
    words = " ".join((line_text or "").split())
    quoted = f"“{words[:80]}{'…' if len(words) > 80 else ''}”" if words else ""
    if at is not None:
        s = int(round(max(0.0, at)))
        where = f"the line at {s // 60}:{s % 60:02d}" + (f" ({quoted})" if quoted else "")
    elif quoted:
        where = f"the line {quoted}"
    else:
        where = "one of the new lines"
    return f"The {what}'s safety filter refused {where}. Nothing was charged. Reword that line and try again."


def request_refused(text: str) -> str:
    """The agent's own refusal (Claude's safety filter on what the person asked)."""
    words = " ".join((text or "").split())
    quoted = f" (“{words[:80]}{'…' if len(words) > 80 else ''}”)" if words else ""
    return f"The AI service's safety filter refused this request{quoted}, so nothing was changed. Reword it and try again."


def classify(exc: BaseException) -> Failure:
    """Which of the three a failure is, and the sentence the person reads."""
    from fastapi import HTTPException
    from app.budget import BudgetExceeded
    from app.diskroom import DiskFull
    from app.usage import SpendCeilingReached
    from app.adapters.elevenlabs import VoiceInputError
    if isinstance(exc, SafetyRefused):
        return Failure(SAFETY, safety_sentence(exc.vendor, exc.line_text, exc.at), cause=f"{exc.vendor}: {exc.detail}"[:400],
                       vendor=exc.vendor)
    if isinstance(exc, HTTPException):
        if exc.status_code < 500 and isinstance(exc.detail, str):
            return Failure(USER_INPUT, exc.detail, status=exc.status_code)
        return Failure(OUR_SIDE, OUR_END_REPORTED, cause=f"HTTP {exc.status_code}: {exc.detail}"[:400], vendor="server",
                       status=exc.status_code)
    if isinstance(exc, DiskFull) or (isinstance(exc, OSError) and getattr(exc, "errno", None) == 28):
        # Ours, but the disk's own sentence is the honest one: uploads and renders wait for room.
        from app.diskroom import SHORT
        return Failure(OUR_SIDE, SHORT, cause="disk full", vendor="server")
    if isinstance(exc, (BudgetExceeded, SpendCeilingReached, VoiceInputError)):
        return Failure(USER_INPUT, str(exc))
    vendor = _vendor(exc)
    if vendor is not None or isinstance(exc, OSError):
        # A vendor's call that failed was not billed; ffmpeg or the disk failing may come after a paid step.
        text = OUR_END if vendor not in (None, "ffmpeg") else OUR_END_REPORTED
        return Failure(OUR_SIDE, text, cause=_cause(exc), vendor=vendor or "server", status=_status(exc))
    if isinstance(exc, NonRetryableError) or (isinstance(exc, (ValueError, LookupError))
                                               and type(exc).__module__.startswith("app.")):
        # The app's own refusals are written for the person: what and how to fix it.
        text = str(exc).strip()
        if text:
            return Failure(USER_INPUT, text)
    return Failure(OUR_SIDE, OUR_END_REPORTED, cause=_cause(exc), vendor="server", status=_status(exc))


def charged_sentence(spent_usd: float) -> str:
    """Our side, when an earlier step of the same work was paid for before the failure."""
    cost = f"${spent_usd:.2f}" if spent_usd >= 0.005 else "less than a cent"
    return (f"Something went wrong on our end. The step that failed was not charged; the steps before it cost "
            f"{cost}. Try again in a minute.")


def say(exc: BaseException, *, where: str, owner: str | None = None, video_id: str | None = None,
        line: tuple[str | None, float | None] | None = None, spent_usd: float | None = None,
        captured: bool = False) -> str:
    """The sentence a person reads for `exc`; our side is logged and reported to the admins first
    (`captured`: the error reporter already has it, so only the admins' notice is added)."""
    if line is not None and isinstance(exc, SafetyRefused):
        exc = exc.on_line(*line)
    failure = classify(exc)
    if failure.kind == OUR_SIDE:
        report(failure, exc, where=where, owner=owner, video_id=video_id, captured=captured)
        if spent_usd is not None and failure.text in (OUR_END, OUR_END_REPORTED):
            # What this work spent is known: say it, or say that nothing was.
            return charged_sentence(spent_usd) if spent_usd > 1e-9 else OUR_END
    elif failure.kind == SAFETY:
        log.warning("safety refusal at %s (%s): %s", where, video_id, failure.cause)
    return failure.text


def unconfigured(vendor: str, setting: str, *, where: str, owner: str | None = None, video_id: str | None = None) -> str:
    """A vendor this server has no key for (or is switched off): ours, said as ours, with the
    setting named for the admins only."""
    failure = Failure(OUR_SIDE, OUR_END, cause=f"{setting} is not set on this server", vendor=vendor)
    report(failure, RuntimeError(failure.cause), where=where, owner=owner, video_id=video_id)
    return OUR_END


def http(exc: BaseException, *, where: str, owner: str | None = None, video_id: str | None = None,
         line: tuple[str | None, float | None] | None = None, captured: bool = False):
    """`say`, as the HTTPException an endpoint raises: 402 over a spending ceiling,
    422 for the person's input or a safety refusal, 503 for our side."""
    from fastapi import HTTPException
    from app.budget import BudgetExceeded
    from app.usage import SpendCeilingReached
    text = say(exc, where=where, owner=owner, video_id=video_id, line=line, captured=captured)
    kind = classify(exc).kind
    if isinstance(exc, (BudgetExceeded, SpendCeilingReached)):
        status = 402
    elif isinstance(exc, HTTPException):
        status = exc.status_code
    else:
        status = 503 if kind == OUR_SIDE else 422
    return HTTPException(status_code=status, detail=text)


# ── telling the admins ───────────────────────────────────────────────────────

_reporter = None
_db = None
_admins: Callable[[], list[str]] | None = None
_clock: Callable[[], float] = time.time


def configure(*, reporter=None, database=None, admins: Callable[[], list[str]] | None = None,
              clock: Callable[[], float] | None = None) -> None:
    """Wired once by the app: the error reporter, and who the admins are."""
    global _reporter, _db, _admins, _clock
    _reporter, _db, _admins = reporter, database, admins
    if clock is not None:
        _clock = clock


def report(failure: Failure, exc: BaseException, *, where: str, owner: str | None = None,
           video_id: str | None = None, captured: bool = False) -> None:
    """Our side: the real cause in the log and the error reports, and an admin
    notice the first time this cause is seen in ALERT_EVERY_S. Never raises."""
    log.error("our side at %s (%s, %s): %s", where, owner, video_id, failure.cause)
    try:
        if _reporter is not None and not captured:
            _reporter.capture_exception(exc, {"source": "vendor", "where": where, "owner": owner, "video_id": video_id,
                                              "vendor": failure.vendor, "cause": failure.reason})
        _alert(failure, where, video_id)
    except Exception:  # noqa: BLE001 - telling the admins never breaks what failed
        log.exception("could not alert the admins")


def _alert(failure: Failure, where: str, video_id: str | None) -> None:
    if _db is None or _admins is None:
        return
    from app.notify import inbox
    now = _clock()
    key = ALERT_KEY + failure.key
    with _db.tx() as c:
        row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        if row is not None and now - float(json.loads(row["value"]).get("at", 0.0)) < ALERT_EVERY_S:
            return
        c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                  (key, json.dumps({"at": now})))
        name = VENDOR_NAMES.get(failure.vendor or "server", failure.vendor or "the server")
        title = f"{name} failed: {failure.reason}. People see “something went wrong on our end”."
        body = f"{where}{f' on {video_id}' if video_id else ''}: {failure.cause}"
        for admin in _admins():
            inbox.add_in(c, admin, "vendor_failure", title, body=body, link="#admin")
