"""Voice consent V1, step 2: the voice guard. Every rule about cloned voices
lives here, and every path that clones, voices, saves or exports a voice asks
it first (step 3 wires them; `GuardedVoice` keeps the vendor behind it).

    can_clone(owner, video_id, speaker_label, speaker_name)    clone_not_allowed + reason
    require_attestation(owner, video_id, voice_id, speaker)    attestation_required (the UI opens the modal)
    check_scope(voice_id, video_id)                            voice_out_of_scope, voice_unavailable
    check_line(owner, video_id, voice_id, text)                line_blocked + category, line_in_review
    log_synthesis(...)                                         never fails the user; alerts on a write error
    require_export_attestation(owner, video_ids)               export_confirm_required
    strike(owner, category)                                    3 blocked lines in 24 h suspend cloned voices

and what the routes do with them: `attest`, `confirm_export`, `promote`,
`withdraw`, `suspend` / `restore`, `set_limits`. Every refusal is a
`VoiceGuardError` with a machine `code`, a plain `message` for the person, an
HTTP `status` and the facts the front end needs (`data`).

Everything is behind `voices.cloning_verified`, per owner: with it off, every
check passes at once and nothing is written (`enabled`). The records are
migration 0048's tables; `voice_records` holds each vendor voice's scope.

The seams later steps fill:

    LineChecker   step 4: the rules and the check model (app.safety.line_checks,
                  `LineChecks`; `PassThroughLines` is the stand-in the tests may use)
    NoGoCheck     step 5: the speaker embedding against `no_go_voices`
                  (`app.safety.no_go.VoiceListNoGo`, which also keeps the
                  built-in public-figure name list, `NameListNoGo`)
    export_label  step 7: whether the export carries the "AI voice" label;
                  `export_facts` (what a file carries), `trace` (Admin: Trace),
                  `cloning_state` (Admin: suspend cloning / restore)
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol

from app.timefmt import iso

log = logging.getLogger("voltage.voice_guard")

FLAG = "voices.cloning_verified"

# The one source of the attestation and export reminder wording and its version (the front end's
# consent/copy.ts mirrors the words; its test reads them from this file). Bump STATEMENT_VERSION
# whenever any word of STATEMENT or EXPORT_STATEMENT changes, and pin the new wording's
# `statement_hash()` in tests/safety/test_statement_version.py: everyone confirms again on next
# use. RUNBOOK.md, "Changing the consent wording".
STATEMENT_VERSION = "2026-10-31"
STATEMENT = {
    "version": STATEMENT_VERSION,
    "title": "Use {speaker}'s voice?",
    "body": "Voltage will make new lines in this person's voice. Tell us whose voice it is.",
    "choices": [{"choice": "my_voice", "label": "This is my voice"},
                {"choice": "have_permission", "label": "I have permission from this person to change what they say"}],
    "confirm": ("I confirm I have the rights and consent to use this voice. I won't use it to deceive, impersonate "
                "or harm anyone, and I'm responsible for how it's used."),
    "warning": "Using someone's voice without their consent can be illegal.",
    "cancel": "Cancel",
    "accept": "Use this voice",
}
EXPORT_STATEMENT = {
    "version": STATEMENT_VERSION,
    "title": "This video has AI changes to {speaker}'s voice",
    "label": "Add an \"AI voice\" label to the video (recommended)",
    "confirm": "I have permission from everyone whose voice was changed",
    "back": "Back",
    "accept": "Export",
}
CHOICES = ("my_voice", "have_permission")


def statement_hash() -> str:
    """A fingerprint of the words a person confirms (both statements, the version left out),
    pinned to its version by tests/safety/test_statement_version.py."""
    words = {"attest": {k: v for k, v in STATEMENT.items() if k != "version"},
             "export": {k: v for k, v in EXPORT_STATEMENT.items() if k != "version"}}
    return hashlib.sha256(json.dumps(words, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

# The plan's open decision 2: 5 a day, 30 a month; an admin can raise them per person.
DAY_LIMIT, MONTH_LIMIT = 5, 30
STRIKES, STRIKE_HOURS = 3, 24
# A vendor clone of a person's voice: from a speaker in a video, or (step 7) from a recording
# uploaded to My voices. A suspension disables both.
CLONE_KINDS = ("cloned", "recorded")

# ── the codes and the words ──────────────────────────────────────────────────

CLONE_NOT_ALLOWED = "clone_not_allowed"
ATTESTATION_REQUIRED = "attestation_required"
VOICE_OUT_OF_SCOPE = "voice_out_of_scope"
VOICE_UNAVAILABLE = "voice_unavailable"
LINE_BLOCKED = "line_blocked"
LINE_IN_REVIEW = "line_in_review"
EXPORT_CONFIRM_REQUIRED = "export_confirm_required"
OWN_VOICE_CHECK_REQUIRED = "own_voice_check_required"
STATEMENT_CHANGED = "statement_changed"
NOT_YOURS = "voice_not_found"
GUARD_BYPASSED = "guard_bypassed"

OUT_OF_SCOPE = "This voice can only be used in the video it came from."
WITHDRAWN = "This voice was withdrawn, so it can no longer be used. Pick another voice."
VOICE_PAUSED = "This voice is paused while we review it. Pick another voice, or contact support if this is a mistake."
SUSPENDED = ("Voicing with cloned voices is paused on your account while we review recent lines. "
             "Contact support if this is a mistake.")
HELD = "This line is held for a quick check. You'll get a notification when it's cleared."
# Step 4: the block names the category in plain words (the plan's fraud sentence, the same shape for the rest).
BLOCKED = {
    "fraud": "I can't voice this line. It asks for payment details, which we don't allow.",
    "impersonation": "I can't voice this line. It pretends to be a real person or an official, which we don't allow.",
    "political": "I can't voice this line. It's about a political party, a candidate or an election, which we don't allow.",
    "minors": "I can't voice this line. It's sexual content involving a child, which we don't allow.",
    "sexual": "I can't voice this line. It's sexual content, which we don't allow.",
    "hate": "I can't voice this line. It has hate, threats or harassment, which we don't allow.",
}
BLOCKED_ANY = "I can't voice this line. It breaks the rules on what Voltage voices."
# The order a block's copy is picked in when a line hits more than one category.
BLOCK_ORDER = ("minors", "fraud", "impersonation", "hate", "sexual", "political")
REVIEW_HOURS = 48
CLEARED = "Your held line was cleared. You can voice it now."
NOT_CLEARED = "Your held line was not cleared."
EXPIRED = "Your held line was not checked within 48 hours, so it was not cleared. Edit the line and try again."
CATEGORY_WORDS = {"fraud": "fraud or payment details", "impersonation": "impersonation", "political": "political content",
                  "sexual": "sexual content", "minors": "a child", "hate": "hate, threats or harassment",
                  "claims": "a medical or money claim", "unclear": "something the check was not sure about"}
ATTEST_FIRST = "Tell us whose voice this is before Voltage makes new lines in it."
CONFIRM_EXPORT = "Confirm the AI voice reminder before you export this video."
PROVE_IT = "Prove it's your voice first: read the phrase on screen in your own voice."
REASONS = {
    "email_unverified": "Verify your email address before you clone a voice.",
    "suspended": SUSPENDED,
    "daily_limit": "You have cloned {n} voices today, the most for one day. Try again tomorrow.",
    "monthly_limit": "You have cloned {n} voices in the last 30 days, the most for a month. Contact support if you need more.",
    "no_go_review": "This voice is held for a quick check before it can be cloned. You'll get a notification when it's cleared.",
    # Step 5: a voice that matches (or an admin matched) an entry of the no-go list. The entry is never named.
    "no_go_voice": ("This voice is on the list of voices Voltage does not clone. Pick a voice from the catalogue, "
                    "or design one from words."),
}


class VoiceGuardError(Exception):
    """A refusal of the guard: `code` for the machine, `message` for the person,
    `status` for HTTP, `data` for whatever the front end shows with it."""

    def __init__(self, code: str, message: str, status: int = 403, **data: Any) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.data = code, message, status, data

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, **self.data}

    @property
    def pauses(self) -> bool:
        """The agent's turn pauses on a card for this one (the attestation modal), never prose."""
        return self.code == ATTESTATION_REQUIRED


def block_copy(categories) -> str:
    have = set(categories or ())
    for c in BLOCK_ORDER:
        if c in have:
            return BLOCKED[c]
    return BLOCKED_ANY


# ── the seams later steps fill ───────────────────────────────────────────────

@dataclass(frozen=True)
class LineVerdict:
    verdict: str                                  # pass | block | review
    categories: tuple[str, ...] = ()
    model: str = ""
    rule_hits: tuple[str, ...] = ()
    reason: str = ""
    model_failed: bool = False                    # the check model did not answer (the guard picks the default)
    model_ms: int | None = None


class LineChecker(Protocol):
    """Step 4: the rules (English, Hindi, Hinglish) then the check model."""
    name: str

    def check(self, text: str, *, owner: str, video_id: str | None, voice_id: str | None) -> LineVerdict: ...


class PassThroughLines:
    name = "pass-through"

    def check(self, text: str, *, owner: str, video_id: str | None, voice_id: str | None) -> LineVerdict:
        return LineVerdict("pass", model=self.name)


@dataclass(frozen=True)
class NoGoVerdict:
    verdict: str                                  # pass | block | review
    match: str | None = None
    score: float | None = None
    how: str = ""
    hold_id: str | None = None                    # step 5: the borderline queue item a review waits on


class NoGoCheck(Protocol):
    """Step 5: the speaker's embedding against `no_go_voices` (block at 0.92, review from 0.84).
    `reference` None: the caller has no audio yet (it asks again with it, `check_no_go`).
    `context` is who and what is cloned: owner, video_id, speaker_label, speaker_name."""
    name: str

    def check(self, *, name: str | None, reference: Path | None, **context) -> NoGoVerdict: ...


class NameListNoGo:
    """The built-in public-figure name list (app.safety.figures)."""
    name = "name list"

    def __init__(self, figures) -> None:
        self.figures = figures

    def check(self, *, name: str | None, reference: Path | None, **context) -> NoGoVerdict:
        found = self.figures.match(name or "") if name else None
        return NoGoVerdict("block", found, None, self.name) if found else NoGoVerdict("pass", how=self.name)


# ── the vendor pass ──────────────────────────────────────────────────────────
# The guard opens a pass for exactly the call it checked; `GuardedVoice` lets a
# vendor call through only inside one (for an owner with the flag on).

_PASSES: ContextVar[tuple[str, ...]] = ContextVar("voice_guard_passes", default=())


@contextmanager
def vendor_pass(*keys: str) -> Iterator[None]:
    token = _PASSES.set(_PASSES.get() + keys)
    try:
        yield
    finally:
        _PASSES.reset(token)


def has_pass(key: str) -> bool:
    return key in _PASSES.get()


def synth_key(video_id: str) -> str:
    return f"synth:{video_id}"


def clone_key(owner: str) -> str:
    return f"clone:{owner}"


@dataclass(frozen=True)
class Ticket:
    """What `before_synthesis` checked, for the synthesis log after the vendor call."""
    owner: str
    video_id: str
    voice_id: str
    text: str
    enabled: bool
    attestation_id: str | None = None
    line_check_id: str | None = None


def _hash(text: str) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


_WORKSPACE = "(SELECT id FROM workspaces WHERE owner = ? ORDER BY created_at, id LIMIT 1)"


@dataclass
class VoiceGuard:
    """The rules, over the app's database and repository. Built once by the
    app (`app.api.main.voice_guard`); tests build one from the same pieces."""

    database: Any
    repo: Any
    enabled_for: Callable[[str], bool]
    no_go: Any = None
    lines: Any = field(default_factory=PassThroughLines)
    vendor_delete: Callable[[str], None] | None = None
    # (video_id) -> (a key for what the video's export holds now, the voice ids its live edits speak in)
    export_content: Callable[[str], tuple[str, set[str]]] = lambda video_id: ("", set())
    account_verified: Callable[[str], bool] = lambda owner: True
    alert: Callable[[str, BaseException], None] | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    # Step 4: (event, facts) for the people to tell: "held" (admins: a line to review),
    # "minor" (admins: a report), "decided" (the owner: their held line cleared or not).
    tell: Callable[[str, dict], None] | None = None

    # ── basics ──

    def enabled(self, owner: str | None) -> bool:
        return bool(owner) and bool(self.enabled_for(owner))

    def _now(self) -> str:
        return iso(self.clock())

    def _since(self, hours: float) -> str:
        return iso(self.clock() - timedelta(hours=hours))

    def record(self, voice_id: str | None) -> dict | None:
        if not voice_id:
            return None
        with self.database.tx() as c:
            row = c.execute("SELECT * FROM voice_records WHERE voice_id = ?", (voice_id,)).fetchone()
        return dict(row) if row else None

    def records_of(self, owner: str) -> list[dict]:
        with self.database.tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM voice_records WHERE owner = ? ORDER BY created_at, voice_id",
                                               (owner,))]

    def describe(self, voice_id: str) -> dict | None:
        """A voice's scope as a chip shows it (step 6: "This video only")."""
        rec = self.record(voice_id)
        if rec is None:
            return None
        return {"voice_id": voice_id, "scope": rec["scope"], "status": rec["status"], "kind": rec["kind"],
                "source_video_id": rec["source_video_id"], "speaker_label": rec["speaker_label"],
                "video_only": rec["scope"] == "video", "verified": bool(rec["verified_consent_id"])}

    def _video(self, video_id: str) -> dict | None:
        """The video's owner and parents, read from the table itself (the Bin included)."""
        with self.database.tx() as c:
            row = c.execute("SELECT owner, master_id, settings FROM videos WHERE id = ?", (video_id,)).fetchone()
        if row is None:
            return None
        try:
            settings = json.loads(row["settings"] or "{}")
        except (TypeError, ValueError):
            settings = {}
        return {"owner": row["owner"], "parent": row["master_id"] or settings.get("variant_of")}

    def family_root(self, video_id: str) -> str:
        """The first video of a family: up the language versions (master_id) and variants (variant_of)."""
        seen: set[str] = set()
        current = video_id
        while current and current not in seen and len(seen) < 64:
            seen.add(current)
            found = self._video(current)
            if found is None or not found["parent"]:
                break
            current = found["parent"]
        return current

    def in_family(self, source_video_id: str | None, video_id: str) -> bool:
        if not source_video_id:
            return False
        return source_video_id == video_id or self.family_root(source_video_id) == self.family_root(video_id)

    def _owner_of(self, video_id: str) -> str | None:
        found = self._video(video_id)
        return found["owner"] if found is not None else None

    def _speaker_name(self, video_id: str | None, label: str | None) -> str:
        if label in (None, "", "_"):
            return "the speaker"
        try:
            speakers = self.repo.speakers(video_id) if video_id else []
        except Exception:  # noqa: BLE001 - a name is a nicety
            speakers = []
        return next((s.name for s in speakers if s.label == label and s.name), f"Speaker {label}")

    # ── the records the clone paths write ──

    def record_voice(self, owner: str, voice_id: str, *, kind: str, scope: str, origin: str,
                     source_video_id: str | None = None, speaker_label: str | None = None, speaker_name: str | None = None,
                     verified_consent_id: str | None = None) -> None:
        """A voice just made at the vendor. Written whatever the flag, so a later
        switch-on finds every clone's scope; never fails the clone itself."""
        now = self._now()
        try:
            with self.database.tx() as c:
                c.execute(
                    "INSERT INTO voice_records (voice_id, owner, workspace_id, kind, scope, source_video_id, speaker_label, "
                    "speaker_name, verified_consent_id, status, origin, vendor_state, created_at, updated_at) "
                    f"VALUES (?, ?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, 'active', ?, 'live', ?, ?) "
                    "ON CONFLICT (voice_id) DO UPDATE SET owner = excluded.owner, kind = excluded.kind, scope = excluded.scope, "
                    "source_video_id = excluded.source_video_id, speaker_label = excluded.speaker_label, "
                    "speaker_name = excluded.speaker_name, verified_consent_id = excluded.verified_consent_id, "
                    "status = 'active', status_reason = '', origin = excluded.origin, vendor_state = 'live', "
                    "updated_at = excluded.updated_at",
                    (voice_id, owner, owner, kind, scope, source_video_id, speaker_label, speaker_name, verified_consent_id,
                     origin, now, now))
        except Exception as exc:  # noqa: BLE001 - the clone is made; the record is the app's to catch up (backfill)
            self._alarm("voice record", exc)

    def backfill(self) -> int:
        """Records for any voice the lists hold without one (made by a path that
        could not write it): the migration's own rules. Run at app start."""
        from app.store.migrations import m0048_voice_consent as m0048
        now = self._now()
        with self.database.tx() as c:
            have = {r[0] for r in c.execute("SELECT voice_id FROM voice_records").fetchall()}
            missing = [r for r in m0048.classify(c) if r["voice_id"] not in have]
            for r in missing:
                c.execute(
                    "INSERT INTO voice_records (voice_id, owner, workspace_id, kind, scope, source_video_id, speaker_label, "
                    "speaker_name, verified_consent_id, status, status_reason, origin, migration_row, vendor_state, created_at, "
                    f"updated_at) VALUES (?, ?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, '', 'backfill', ?, ?, ?, ?)",
                    (r["voice_id"], r["owner"], r["owner"], r["kind"], r["scope"], r["source_video_id"], r["speaker_label"],
                     r["speaker_name"], r["verified_consent_id"], r["status"], r["row"], r["vendor_state"], now, now))
        return len(missing)

    # ── can_clone ──

    def limits(self, owner: str) -> tuple[int, int]:
        with self.database.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (f"voice_clone_limits:{owner}",)).fetchone()
        saved = json.loads(row["value"]) if row else {}
        return int(saved.get("day") or DAY_LIMIT), int(saved.get("month") or MONTH_LIMIT)

    def set_limits(self, owner: str, day: int, month: int) -> tuple[int, int]:
        """An admin raises (or lowers) a person's clone limits."""
        with self.database.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                      (f"voice_clone_limits:{owner}", json.dumps({"day": int(day), "month": int(month)})))
        return self.limits(owner)

    def _made_since(self, owner: str, since: str) -> int:
        with self.database.tx() as c:
            return int(c.execute("SELECT COUNT(*) FROM voice_records WHERE owner = ? AND origin IN ('clone', 'upload') "
                                 "AND created_at >= ?", (owner, since)).fetchone()[0])

    def can_clone(self, owner: str, video_id: str | None, speaker_label: str | None = None,
                  speaker_name: str | None = None, reference: Path | None = None) -> None:
        """The account may clone (a verified email, not suspended, under its limits)
        and the speaker is not on the no-go list. Raises clone_not_allowed."""
        if not self.enabled(owner):
            return

        def refuse(reason: str, message: str | None = None, **data) -> VoiceGuardError:
            return VoiceGuardError(CLONE_NOT_ALLOWED, message or REASONS[reason], 403, reason=reason, video_id=video_id, **data)
        if not self.account_verified(owner):
            raise refuse("email_unverified")
        if self.suspended(owner):
            raise refuse("suspended")
        day, month = self.limits(owner)
        if self._made_since(owner, self._since(24)) >= day:
            raise refuse("daily_limit", REASONS["daily_limit"].format(n=day), limit=day)
        if self._made_since(owner, self._since(24 * 30)) >= month:
            raise refuse("monthly_limit", REASONS["monthly_limit"].format(n=month), limit=month)
        self.check_no_go(owner, video_id, speaker_label, speaker_name, reference)

    def check_no_go(self, owner: str, video_id: str | None, speaker_label: str | None = None,
                    speaker_name: str | None = None, reference: Path | None = None) -> None:
        """The no-go part of can_clone, for a path that has the audio only after
        the account's checks (an uploaded recording). Raises clone_not_allowed:
        reason no_go (blocked), or no_go_review (the clone waits for an admin).
        The name list says which figure matched; a voice match never names the entry."""
        if not self.enabled(owner) or self.no_go is None:
            return
        name = speaker_name or (self._speaker_name(video_id, speaker_label) if speaker_label else None)
        verdict = self.no_go.check(name=name, reference=reference, owner=owner, video_id=video_id,
                                   speaker_label=speaker_label, speaker_name=name)

        def refuse(reason: str, message: str | None = None, **data) -> VoiceGuardError:
            return VoiceGuardError(CLONE_NOT_ALLOWED, message or REASONS[reason], 403, reason=reason, video_id=video_id, **data)
        if verdict.verdict == "block":
            if verdict.how == NameListNoGo.name:
                from app.safety.figures import REFUSAL
                raise refuse("no_go", REFUSAL, match=verdict.match, score=verdict.score)
            raise refuse("no_go", REASONS["no_go_voice"])
        if verdict.verdict == "review":
            raise refuse("no_go_review", hold_id=verdict.hold_id)

    # ── attestation ──

    def require_attestation(self, owner: str, video_id: str, voice_id: str | None = None,
                            speaker_label: str | None = None) -> str | None:
        """A current attestation for this user, voice (or speaker, before the clone
        is made) and statement version. Only cloned voices need one; a voice proven
        to be the user's own (library, with a passed check) does not. Returns the
        attestation's id, or raises attestation_required."""
        if not self.enabled(owner):
            return None
        rec = self.record(voice_id) if voice_id else None
        if voice_id and (rec is None or rec["kind"] != "cloned"):
            return None
        if rec is not None and rec["scope"] == "library" and rec["verified_consent_id"]:
            return None
        source = rec["source_video_id"] if rec is not None else video_id
        label = rec["speaker_label"] if rec is not None else speaker_label
        with self.database.tx() as c:
            row = c.execute(
                "SELECT id FROM voice_attestations WHERE owner = ? AND statement_version = ? AND "
                "((voice_id IS NOT NULL AND voice_id = ?) OR (video_id = ? AND speaker_label = ?)) "
                "ORDER BY created_at DESC LIMIT 1", (owner, STATEMENT_VERSION, voice_id or "", source or "", label or "")).fetchone()
        if row is not None:
            return row["id"]
        name = (rec["speaker_name"] if rec is not None and rec["speaker_name"] else None) or self._speaker_name(source, label)
        raise VoiceGuardError(ATTESTATION_REQUIRED, ATTEST_FIRST, 409, video_id=video_id, source_video_id=source,
                              voice=voice_id or label or "_", voice_id=voice_id, speaker_label=label, speaker_name=name,
                              statement_version=STATEMENT_VERSION)

    def statement(self) -> dict:
        """The words the modal and the export reminder show, with the version in force now."""
        return {**STATEMENT, "version": STATEMENT_VERSION, "export": {**EXPORT_STATEMENT, "version": STATEMENT_VERSION}}

    def attest(self, owner: str, video_id: str, voice: str, choice: str, statement_version: str,
               ip: str | None = None, user_agent: str | None = None) -> dict:
        """The user confirmed the modal for `voice` (a voice id, or a speaker's label before their clone exists)."""
        if choice not in CHOICES:
            raise VoiceGuardError("invalid_choice", "Pick whose voice this is.", 422)
        if statement_version != STATEMENT_VERSION:
            raise VoiceGuardError(STATEMENT_CHANGED, "The wording has changed since you opened it. Read it again and confirm.",
                                  409, statement=self.statement())
        rec = self.record(voice)
        if rec is not None:
            if rec["owner"] != owner:
                raise VoiceGuardError(NOT_YOURS, "No such voice of yours.", 404)
            voice_id, label = voice, rec["speaker_label"]
        else:
            label = voice
            clones = self.repo.clones(video_id) or {}
            speakers = {s.label for s in self.repo.speakers(video_id)} | set(clones) | {"_"}
            if label not in speakers:
                raise VoiceGuardError(NOT_YOURS, "There is no such speaker in this video.", 404)
            voice_id = clones.get(label)
        row = {"id": _id("va"), "owner": owner, "video_id": video_id, "voice_id": voice_id, "speaker_label": label,
               "choice": choice, "statement_version": statement_version, "created_at": self._now(),
               "ip": (ip or "")[:64] or None, "user_agent": (user_agent or "")[:300] or None}
        with self.database.tx() as c:
            c.execute("INSERT INTO voice_attestations (id, workspace_id, owner, video_id, voice_id, speaker_label, choice, "
                      f"statement_version, created_at, ip, user_agent) VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (row["id"], owner, owner, video_id, voice_id, label, choice, statement_version, row["created_at"],
                       row["ip"], row["user_agent"]))
        return row

    # ── scope ──

    def check_scope(self, voice_id: str | None, video_id: str, owner: str | None = None) -> None:
        """A voice may speak in this video: it is not a clone, or it is the owner's,
        active, and library or the video is in its source video's family."""
        owner = owner or self._owner_of(video_id)
        if not self.enabled(owner):
            return
        rec = self.record(voice_id)
        if rec is None:
            return
        if rec["status"] == "withdrawn":
            raise VoiceGuardError(VOICE_UNAVAILABLE, WITHDRAWN, 403, reason="withdrawn", voice_id=voice_id)
        if rec["status"] == "suspended":
            reason = "account_suspended" if rec["status_reason"] == "account" else "suspended"
            raise VoiceGuardError(VOICE_UNAVAILABLE, SUSPENDED if reason == "account_suspended" else VOICE_PAUSED, 403,
                                  reason=reason, voice_id=voice_id)
        if rec["kind"] in CLONE_KINDS and self.suspended(rec["owner"]):
            raise VoiceGuardError(VOICE_UNAVAILABLE, SUSPENDED, 403, reason="account_suspended", voice_id=voice_id)
        if rec["owner"] != owner or (rec["scope"] == "video" and not self.in_family(rec["source_video_id"], video_id)):
            raise VoiceGuardError(VOICE_OUT_OF_SCOPE, OUT_OF_SCOPE, 403, voice_id=voice_id, video_id=video_id,
                                  source_video_id=rec["source_video_id"] if rec["owner"] == owner else None)

    def usable(self, owner: str, video_id: str, voice_id: str) -> bool:
        """Whether Voltage may pick this voice here (list_voices shows only these)."""
        try:
            self.check_scope(voice_id, video_id, owner)
        except VoiceGuardError:
            return False
        return True

    # ── line checks ──

    def check_line(self, owner: str, video_id: str | None, voice_id: str | None, text: str) -> str | None:
        """Every line, with any voice, before it is voiced (open decision 7): the
        verdict is written (the text only when blocked or held). A held line an
        admin approved is voiced without a check again. Returns the check's id."""
        if not self.enabled(owner):
            return None
        h = _hash(text)
        with self.database.tx() as c:
            earlier = c.execute(
                "SELECT id, review_state, categories FROM line_checks WHERE owner = ? AND text_hash = ? AND verdict = 'review' "
                "AND review_state IN ('approved', 'waiting') AND (video_id = ? OR video_id IS NULL) ORDER BY created_at DESC LIMIT 1",
                (owner, h, video_id or "")).fetchone()
        if earlier is not None and earlier["review_state"] == "approved":
            return self._write_check(owner, video_id, voice_id, text, LineVerdict("pass", model=f"approved:{earlier['id']}"))
        if earlier is not None:                       # the same words already wait: no second row in the queue
            raise VoiceGuardError(LINE_IN_REVIEW, HELD, 409, categories=json.loads(earlier["categories"] or "[]"),
                                  line_check_id=earlier["id"])
        verdict = self.lines.check(text, owner=owner, video_id=video_id, voice_id=voice_id)
        if verdict.model_failed:
            verdict = self._model_failed(owner, voice_id, verdict)
        check_id = self._write_check(owner, video_id, voice_id, text, verdict)
        if verdict.verdict == "block":
            category = next((c for c in BLOCK_ORDER if c in verdict.categories), verdict.categories[0] if verdict.categories else "")
            if "minors" in verdict.categories:
                self._tell("minor", {"owner": owner, "video_id": video_id, "line_check_id": check_id, "text": text})
            self.strike(owner, category)
            raise VoiceGuardError(LINE_BLOCKED, block_copy(verdict.categories), 422, category=category,
                                  categories=list(verdict.categories), line_check_id=check_id)
        if verdict.verdict == "review":
            self._tell("held", {"owner": owner, "video_id": video_id, "line_check_id": check_id, "text": text,
                                "categories": list(verdict.categories)})
            raise VoiceGuardError(LINE_IN_REVIEW, HELD, 409, categories=list(verdict.categories), line_check_id=check_id)
        return check_id

    def _model_failed(self, owner: str, voice_id: str | None, verdict: LineVerdict) -> LineVerdict:
        """The check model did not answer. A cloned voice's line is held for a person;
        any other voice's line goes on what the rules said, with a warning in the log."""
        if verdict.verdict != "pass":
            return verdict
        rec = self.record(voice_id)
        if rec is not None and rec["kind"] == "cloned":
            return LineVerdict("review", ("unclear",), verdict.model, verdict.rule_hits,
                               verdict.reason + " Held for a person because the voice is a clone.", model_failed=True)
        log.warning("line check passed on the rules alone for %s (voice %s): %s", owner, voice_id, verdict.reason)
        return verdict

    def _write_check(self, owner: str, video_id: str | None, voice_id: str | None, text: str, verdict: LineVerdict) -> str:
        check_id = _id("lc")
        keep_text = text if verdict.verdict != "pass" else None
        with self.database.tx() as c:
            c.execute("INSERT INTO line_checks (id, workspace_id, owner, video_id, voice_id, text, text_hash, verdict, categories, "
                      "model, rule_hits, created_at, reason, review_state, model_ms) "
                      f"VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (check_id, owner, owner, video_id, voice_id, keep_text, _hash(text), verdict.verdict,
                       json.dumps(list(verdict.categories)), verdict.model or getattr(self.lines, "name", ""),
                       json.dumps(list(verdict.rule_hits)), self._now(), (verdict.reason or "")[:300],
                       "waiting" if verdict.verdict == "review" else "", verdict.model_ms))
        return check_id

    def _tell(self, event: str, facts: dict) -> None:
        if self.tell is None:
            return
        try:
            self.tell(event, facts)
        except Exception as exc:  # noqa: BLE001 - telling people never fails the check
            self._alarm(f"{event} notice", exc)

    def prepare_lines(self, owner: str, video_id: str, texts) -> int:
        """All of a video's lines checked in one model call ahead of voicing them
        (a Go on a plan, a batch, a language version's master). Never fails the caller."""
        if not self.enabled(owner) or not hasattr(self.lines, "prepare"):
            return 0
        texts = [t for t in dict.fromkeys(texts or ()) if (t or "").strip()]
        if not texts:
            return 0
        try:
            return int(self.lines.prepare(owner, video_id, texts) or 0)
        except Exception as exc:  # noqa: BLE001 - each line is still checked on its own when voiced
            log.warning("line check batch for %s failed: %s", video_id, exc)
            return 0

    # ── the held lines' queue (admins) ──

    def _review_row(self, r) -> dict:
        d = dict(r)
        d["categories"] = json.loads(d.get("categories") or "[]")
        d["rule_hits"] = json.loads(d.get("rule_hits") or "[]")
        d["category_words"] = [CATEGORY_WORDS.get(c, c) for c in d["categories"]]
        d["due_at"] = iso(datetime.fromisoformat(d["created_at"].replace("Z", "+00:00")) + timedelta(hours=REVIEW_HOURS))
        return d

    def review_queue(self, state: str = "waiting", limit: int = 50) -> dict:
        """The held lines waiting (oldest first) or decided (newest first), after auto-rejecting the overdue."""
        self.expire_reviews()
        limit = max(1, min(int(limit), 200))
        with self.database.tx() as c:
            if state == "waiting":
                rows = c.execute("SELECT * FROM line_checks WHERE verdict = 'review' AND review_state = 'waiting' "
                                 "ORDER BY created_at LIMIT ?", (limit,)).fetchall()
            else:
                rows = c.execute("SELECT * FROM line_checks WHERE verdict = 'review' AND review_state IN "
                                 "('approved', 'rejected', 'expired') ORDER BY reviewed_at DESC LIMIT ?", (limit,)).fetchall()
            waiting = c.execute("SELECT COUNT(*) FROM line_checks WHERE verdict = 'review' AND review_state = 'waiting'").fetchone()[0]
        return {"items": [self._review_row(r) for r in rows], "waiting": int(waiting)}

    def decide_review(self, check_id: str, who: str, decision: str, reason: str) -> dict:
        """An admin clears (approve) or refuses (reject) a held line, with a reason.
        Nobody decides on their own line. The owner is told either way."""
        if decision not in ("approve", "reject"):
            raise VoiceGuardError("invalid_decision", "Approve or reject.", 422)
        with self.database.tx() as c:
            row = c.execute("SELECT * FROM line_checks WHERE id = ? AND verdict = 'review'", (check_id,)).fetchone()
        if row is None:
            raise VoiceGuardError("line_check_not_found", "No held line with that id.", 404)
        if row["owner"] == who:
            raise VoiceGuardError("own_line", "You can't decide on your own line. Another admin has to.", 403)
        if row["review_state"] != "waiting":
            raise VoiceGuardError("already_decided", "That line is not waiting for a check any more.", 409)
        state = "approved" if decision == "approve" else "rejected"
        with self.database.tx() as c:
            c.execute("UPDATE line_checks SET review_state = ?, reviewed_by = ?, reviewed_at = ?, review_reason = ? "
                      "WHERE id = ? AND review_state = 'waiting'", (state, who, self._now(), reason, check_id))
            row = c.execute("SELECT * FROM line_checks WHERE id = ?", (check_id,)).fetchone()
        self._tell("decided", {"owner": row["owner"], "video_id": row["video_id"], "line_check_id": check_id,
                               "state": state, "title": CLEARED if state == "approved" else NOT_CLEARED,
                               "text": row["text"] or ""})
        return self._review_row(row)

    def expire_reviews(self) -> int:
        """Open decision 4: a held line nobody checked in 48 hours is rejected, and its owner told."""
        cutoff = self._since(REVIEW_HOURS)
        with self.database.tx() as c:
            due = [dict(r) for r in c.execute("SELECT id, owner, video_id, text FROM line_checks WHERE verdict = 'review' "
                                              "AND review_state = 'waiting' AND created_at < ?", (cutoff,))]
            for r in due:
                c.execute("UPDATE line_checks SET review_state = 'expired', reviewed_by = 'auto', reviewed_at = ?, "
                          "review_reason = ? WHERE id = ? AND review_state = 'waiting'",
                          (self._now(), f"Not checked within {REVIEW_HOURS} hours.", r["id"]))
        for r in due:
            self._tell("decided", {"owner": r["owner"], "video_id": r["video_id"], "line_check_id": r["id"],
                                   "state": "expired", "title": EXPIRED, "text": r["text"] or ""})
        return len(due)

    # ── synthesis, all together ──

    def before_synthesis(self, owner: str, video_id: str, voice_id: str, text: str) -> Ticket:
        """The synthesis checks in the plan's order: scope, attestation (cloned
        voices only), the line. Flag off: a ticket that checked nothing."""
        if not self.enabled(owner):
            return Ticket(owner, video_id, voice_id, text, False)
        self.check_scope(voice_id, video_id, owner)
        attestation = self.require_attestation(owner, video_id, voice_id)
        check = self.check_line(owner, video_id, voice_id, text)
        return Ticket(owner, video_id, voice_id, text, True, attestation, check)

    def log_synthesis(self, ticket: Ticket, take_id: str | None = None, cost_usd: float | None = None) -> str | None:
        """After the vendor call. Never fails the user: a write that fails alerts the admins."""
        if not ticket.enabled:
            return None
        try:
            log_id = _id("sl")
            with self.database.tx() as c:
                c.execute("INSERT INTO synthesis_log (id, workspace_id, owner, video_id, voice_id, attestation_id, line_check_id, "
                          f"text_hash, take_id, cost_usd, created_at) VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (log_id, ticket.owner, ticket.owner, ticket.video_id, ticket.voice_id, ticket.attestation_id,
                           ticket.line_check_id, _hash(ticket.text), take_id, cost_usd, self._now()))
            return log_id
        except Exception as exc:  # noqa: BLE001 - the take is made; the log is ours to fix
            self._alarm("synthesis log", exc)
            return None

    def _alarm(self, what: str, exc: BaseException) -> None:
        log.error("voice guard could not write the %s: %s", what, exc)
        if self.alert is not None:
            try:
                self.alert(what, exc)
            except Exception:  # noqa: BLE001 - telling the admins never breaks what it reports
                log.exception("could not alert the admins")

    # ── exports ──

    def _export_needs(self, video_ids) -> tuple[list[str], list[dict]]:
        covers: list[str] = []
        voices: list[dict] = []
        for vid in dict.fromkeys(video_ids):
            key, used = self.export_content(vid)
            cloned = [r for r in (self.record(v) for v in sorted(used)) if r is not None and r["kind"] == "cloned"]
            if cloned:
                covers.append(f"{vid}:{key}")
                voices += [{"voice_id": r["voice_id"], "video_id": vid, "speaker_label": r["speaker_label"],
                            "speaker_name": r["speaker_name"] or self._speaker_name(r["source_video_id"], r["speaker_label"])}
                           for r in cloned]
        return covers, voices

    def _confirmed(self, owner: str) -> list[dict]:
        with self.database.tx() as c:
            return [dict(r) for r in c.execute("SELECT * FROM export_attestations WHERE owner = ? AND statement_version = ? "
                                               "ORDER BY created_at DESC", (owner, STATEMENT_VERSION))]

    def require_export_attestation(self, owner: str, video_ids) -> dict | None:
        """The export uses no cloned voice, or a confirmation covers it (one for a
        whole batch). Returns that confirmation, or raises export_confirm_required
        with the reference the confirmation is saved against."""
        if not self.enabled(owner):
            return None
        covers, voices = self._export_needs(video_ids)
        if not covers:
            return None
        confirmed = self._confirmed(owner)
        have = {c for row in confirmed for c in json.loads(row["covers"])}
        if all(c in have for c in covers):
            return next(row for row in confirmed if set(json.loads(row["covers"])) & set(covers))
        ref = "ex_" + hashlib.sha256(json.dumps([owner, sorted(covers)]).encode()).hexdigest()[:16]
        pending = {"owner": owner, "covers": covers, "voices": voices, "video_ids": list(dict.fromkeys(video_ids)),
                   "at": self._now()}
        with self.database.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                      (f"voice_export_pending:{ref}", json.dumps(pending)))
        raise VoiceGuardError(EXPORT_CONFIRM_REQUIRED, CONFIRM_EXPORT, 409, export_ref=ref, voices=voices,
                              videos=pending["video_ids"], statement_version=STATEMENT_VERSION, label_default=True,
                              statement=self.statement()["export"])

    def confirm_export(self, owner: str, export_ref: str, label_on: bool, ip: str | None = None) -> dict:
        key = f"voice_export_pending:{export_ref}"
        with self.database.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            pending = json.loads(row["value"]) if row else None
            if pending is None or pending.get("owner") != owner:
                raise VoiceGuardError("export_not_found", "That export reminder is out of date. Export again.", 404)
            made = {"id": _id("ea"), "export_id": export_ref, "owner": owner,
                    "voices_used": sorted({v["voice_id"] for v in pending["voices"]}), "covers": pending["covers"],
                    "statement_version": STATEMENT_VERSION, "label_on": bool(label_on), "created_at": self._now(),
                    "ip": (ip or "")[:64] or None}
            c.execute("INSERT INTO export_attestations (id, workspace_id, export_id, owner, voices_used, covers, statement_version, "
                      f"label_on, created_at, ip) VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, ?)",
                      (made["id"], owner, export_ref, owner, json.dumps(made["voices_used"]), json.dumps(made["covers"]),
                       STATEMENT_VERSION, int(made["label_on"]), made["created_at"], made["ip"]))
            c.execute("DELETE FROM meta WHERE key = ?", (key,))
        return made

    def export_label(self, owner: str, video_id: str) -> bool | None:
        """Step 7's seam: whether this video's export carries the "AI voice" label
        (the confirmation's choice), or None when it needs none."""
        covers, _ = self._export_needs([video_id])
        if not covers:
            return None
        for row in self._confirmed(owner):
            if covers[0] in json.loads(row["covers"]):
                return bool(row["label_on"])
        return True

    def export_facts(self, owner: str, video_id: str) -> dict | None:
        """Step 7: what one exported file of this video carries. Flag off: None (the
        export is as before). Else {ai_voice, label_on, export_attestation_id, voices}:
        the label is on when the file has a cloned voice and the confirmation kept it on."""
        if not self.enabled(owner):
            return None
        covers, voices = self._export_needs([video_id])
        if not covers:
            return {"ai_voice": False, "label_on": False, "export_attestation_id": None, "voices": []}
        row = next((r for r in self._confirmed(owner) if covers[0] in json.loads(r["covers"])), None)
        return {"ai_voice": True, "label_on": bool(row["label_on"]) if row else True,
                "export_attestation_id": row["id"] if row else None, "voices": sorted({v["voice_id"] for v in voices})}

    # ── step 7: Trace ──

    def _rows(self, sql: str, args=()) -> list[dict]:
        with self.database.tx() as c:
            return [dict(r) for r in c.execute(sql, tuple(args))]

    @staticmethod
    def _in(values) -> str:
        return ", ".join("?" for _ in values) or "NULL"

    def trace(self, ref: str) -> dict | None:
        """Everything behind an export, for an admin: found by its mark, its export id,
        its confirmation (the export reminder's reference or id), or an abuse report's
        number (the marks and export ids its words name). None when nothing matches."""
        ref = (ref or "").strip()
        report = None
        found_by = None
        refs = [ref]
        if re.fullmatch(r"#?\d{1,12}", ref):
            got = self._rows("SELECT * FROM abuse_reports WHERE id = ?", (int(ref.lstrip("#")),))
            if not got:
                return None
            report = got[0]
            words = f"{report['location']} {report['details']}"
            refs = re.findall(r"\b(?:ve|ex)_[0-9a-z]+\b|\b[0-9a-f]{16}\b", words.lower())
            found_by = "abuse_report"
        marks: list[dict] = []
        confirmations: list[dict] = []
        for r in dict.fromkeys(refs):
            if not r:
                continue
            by_mark = self._rows("SELECT * FROM provenance_marks WHERE mark = ? OR export_id = ? ORDER BY created_at", (r, r))
            conf = self._rows("SELECT * FROM export_attestations WHERE export_id = ? OR id = ? ORDER BY created_at", (r, r))
            how = "mark" if any(m["mark"] == r for m in by_mark) else "export" if by_mark else "confirmation"
            if conf and not by_mark:
                ids = [c["id"] for c in conf]
                by_mark = self._rows(f"SELECT * FROM provenance_marks WHERE export_attestation_id IN ({self._in(ids)}) "
                                     "ORDER BY created_at", ids)
            if found_by is None and (by_mark or conf):
                found_by = how
            marks += [m for m in by_mark if m["mark"] not in {x["mark"] for x in marks}]
            confirmations += [c for c in conf if c["id"] not in {x["id"] for x in confirmations}]
        if not marks and not confirmations and report is None:
            return None
        # The confirmations the files name, and the voices they and the files list.
        named = [m["export_attestation_id"] for m in marks if m.get("export_attestation_id")]
        have = {c["id"] for c in confirmations}
        missing = [i for i in dict.fromkeys(named) if i not in have]
        if missing:
            confirmations += self._rows(f"SELECT * FROM export_attestations WHERE id IN ({self._in(missing)})", missing)
        voice_ids = sorted({v for m in marks for v in json.loads(m.get("voices") or "[]")}
                           | {v for c in confirmations for v in json.loads(c["voices_used"] or "[]")})
        owners = sorted({m["owner"] for m in marks} | {c["owner"] for c in confirmations})
        # The takes the files play, through the synthesis log to their line checks.
        synthesis: list[dict] = []
        for m in marks:
            takes = json.loads(m.get("takes") or "[]")
            if takes:
                synthesis += self._rows(f"SELECT * FROM synthesis_log WHERE video_id = ? AND take_id IN ({self._in(takes)}) "
                                        "ORDER BY created_at", [m["video_id"], *takes])
        synthesis = list({s["id"]: s for s in synthesis}.values())
        check_ids = sorted({s["line_check_id"] for s in synthesis if s.get("line_check_id")})
        line_checks = self._rows(f"SELECT * FROM line_checks WHERE id IN ({self._in(check_ids)}) ORDER BY created_at",
                                 check_ids) if check_ids else []
        for row in line_checks:
            for key in ("categories", "rule_hits"):
                row[key] = json.loads(row.get(key) or "[]")
        records = {r["voice_id"]: r for r in self._rows(
            f"SELECT * FROM voice_records WHERE voice_id IN ({self._in(voice_ids)})", voice_ids)} if voice_ids else {}
        attest_ids = {s["attestation_id"] for s in synthesis if s.get("attestation_id")}
        voices = []
        for vid in voice_ids:
            rec = records.get(vid) or {"voice_id": vid}
            label, source = rec.get("speaker_label"), rec.get("source_video_id")
            given = self._rows("SELECT * FROM voice_attestations WHERE voice_id = ? OR (owner = ? AND video_id = ? AND "
                               "speaker_label = ? AND (voice_id IS NULL OR voice_id = '')) ORDER BY created_at",
                               (vid, rec.get("owner") or "", source or "", label or ""))
            given += [a for a in self._rows(f"SELECT * FROM voice_attestations WHERE id IN ({self._in(attest_ids)})",
                                            sorted(attest_ids)) if a["voice_id"] == vid and a["id"] not in {g["id"] for g in given}] \
                if attest_ids else []
            voices.append({**rec, "attestations": given})
        for c in confirmations:
            c["voices_used"] = json.loads(c["voices_used"] or "[]")
            c["covers"] = json.loads(c["covers"] or "[]")
            c["label_on"] = bool(c["label_on"])
        exports = [{k: m.get(k) for k in ("mark", "export_id", "owner", "video_id", "file", "sha256", "created_at",
                                          "export_attestation_id")}
                   | {"ai_voice": bool(m.get("ai_voice")), "label_on": bool(m.get("label_on")),
                      "voices": json.loads(m.get("voices") or "[]"), "takes": json.loads(m.get("takes") or "[]")}
                   for m in marks]
        users = [{"owner": o, "suspended": self.suspended(o), "limits": dict(zip(("day", "month"), self.limits(o)))}
                 for o in owners]
        return {"ref": ref, "found_by": found_by or "abuse_report", "abuse_report": report, "exports": exports,
                "export_attestations": confirmations, "voices": voices, "synthesis": synthesis,
                "line_checks": line_checks, "users": users}

    def cloning_state(self, owner: str) -> dict:
        """Step 7, the admin's view of one person's cloning: suspended or not, the
        limits and what they used, and their cloned voices by status."""
        day, month = self.limits(owner)
        counts = {r["status"]: int(r["n"]) for r in self._rows(
            "SELECT status, COUNT(*) AS n FROM voice_records WHERE owner = ? AND kind IN ('cloned', 'recorded') GROUP BY status", (owner,))}
        return {"owner": owner, "suspended": self.suspended(owner), "limits": {"day": day, "month": month},
                "used": {"day": self._made_since(owner, self._since(24)), "month": self._made_since(owner, self._since(24 * 30))},
                "voices": {s: counts.get(s, 0) for s in ("active", "suspended", "withdrawn")},
                "enabled": self.enabled(owner)}

    # ── strikes, suspension ──

    def suspended(self, owner: str) -> dict | None:
        with self.database.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (f"voice_suspension:{owner}",)).fetchone()
        return json.loads(row["value"]) if row else None

    def strike(self, owner: str, category: str = "") -> int:
        """A blocked line counted: STRIKES in STRIKE_HOURS suspend cloning and
        synthesis with cloned voices until an admin restores it. Returns the count."""
        with self.database.tx() as c:
            n = int(c.execute("SELECT COUNT(*) FROM line_checks WHERE owner = ? AND verdict = 'block' AND created_at >= ?",
                              (owner, self._since(STRIKE_HOURS))).fetchone()[0])
        if n >= STRIKES and not self.suspended(owner):
            self.suspend(owner, f"{n} blocked lines in {STRIKE_HOURS} hours" + (f" ({category})" if category else ""),
                         "strike rule")
        return n

    def suspend(self, owner: str, reason: str, by: str) -> int:
        """Cloning blocked and every cloned voice of the owner's disabled. Returns how many voices."""
        now = self._now()
        with self.database.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
                      (f"voice_suspension:{owner}", json.dumps({"reason": reason, "by": by, "at": now})))
            return c.execute("UPDATE voice_records SET status = 'suspended', status_reason = 'account', status_by = ?, "
                             "updated_at = ? WHERE owner = ? AND kind IN ('cloned', 'recorded') AND status = 'active'",
                             (by, now, owner)).rowcount

    def restore(self, owner: str, by: str) -> int:
        """The suspension lifted: the voices it disabled are active again (a withdrawn one stays withdrawn)."""
        now = self._now()
        with self.database.tx() as c:
            c.execute("DELETE FROM meta WHERE key = ?", (f"voice_suspension:{owner}",))
            return c.execute("UPDATE voice_records SET status = 'active', status_reason = '', status_by = ?, updated_at = ? "
                             "WHERE owner = ? AND status = 'suspended' AND status_reason = 'account'", (by, now, owner)).rowcount

    # ── promote, withdraw ──

    def _mine(self, owner: str, voice_id: str) -> dict:
        rec = self.record(voice_id)
        if rec is None or rec["owner"] != owner:
            raise VoiceGuardError(NOT_YOURS, "No such voice of yours.", 404)
        return rec

    def own_voice_check(self, owner: str, video_id: str | None, label: str | None, name: str | None = None) -> str | None:
        """A passed own-voice check of the real gate for this video's speaker (a
        check that named no speaker counts for any), or None."""
        if not video_id:
            return None
        with self.database.tx() as c:
            row = c.execute("SELECT id FROM liveness_attempts WHERE owner = ? AND video_id = ? AND status = 'passed' "
                            "AND method = 'verified' AND (speaker IS NULL OR speaker = '' OR speaker = ? OR speaker = ?) "
                            "ORDER BY created_at DESC LIMIT 1", (owner, video_id, label or "", name or "")).fetchone()
        return row["id"] if row else None

    def promote(self, owner: str, voice_id: str) -> dict:
        """Save to My voices: a video-scoped clone becomes library after a passed
        own-voice check. Raises own_voice_check_required without one."""
        rec = self._mine(owner, voice_id)
        if rec["scope"] == "library":
            return rec
        if rec["status"] != "active":
            raise VoiceGuardError(VOICE_UNAVAILABLE, WITHDRAWN if rec["status"] == "withdrawn" else VOICE_PAUSED, 403,
                                  reason=rec["status"], voice_id=voice_id)
        check = self.own_voice_check(owner, rec["source_video_id"], rec["speaker_label"], rec["speaker_name"])
        if check is None:
            raise VoiceGuardError(OWN_VOICE_CHECK_REQUIRED, PROVE_IT, 403, voice_id=voice_id,
                                  video_id=rec["source_video_id"], speaker_label=rec["speaker_label"])
        with self.database.tx() as c:
            c.execute("UPDATE voice_records SET scope = 'library', verified_consent_id = ?, updated_at = ? WHERE voice_id = ?",
                      (check, self._now(), voice_id))
        return self.record(voice_id)

    def withdraw(self, owner: str, voice_id: str) -> dict:
        """The user withdraws a voice: unusable at once, deleted at the vendor
        (queued, and tried again at app start, when the vendor fails)."""
        rec = self._mine(owner, voice_id)
        if rec["status"] != "withdrawn":
            with self.database.tx() as c:
                c.execute("UPDATE voice_records SET status = 'withdrawn', status_reason = 'user', status_by = ?, "
                          "vendor_state = 'delete_queued', updated_at = ? WHERE voice_id = ?", (owner, self._now(), voice_id))
        self._delete_at_vendor(voice_id)
        return self.record(voice_id)

    def mark_withdrawn(self, voice_id: str, by: str, *, deleted: bool) -> None:
        """Consent withdrawn for a video (its clones deleted at the vendor by that route): the records follow."""
        with self.database.tx() as c:
            c.execute("UPDATE voice_records SET status = 'withdrawn', status_reason = 'consent withdrawn', status_by = ?, "
                      "vendor_state = ?, updated_at = ? WHERE voice_id = ?",
                      (by, "deleted" if deleted else "delete_queued", self._now(), voice_id))

    def _delete_at_vendor(self, voice_id: str) -> bool:
        if self.vendor_delete is None:
            return False
        try:
            self.vendor_delete(voice_id)
        except Exception as exc:  # noqa: BLE001 - stays queued; the next start tries again
            self._alarm("vendor delete", exc)
            return False
        with self.database.tx() as c:
            c.execute("UPDATE voice_records SET vendor_state = 'deleted', updated_at = ? WHERE voice_id = ?", (self._now(), voice_id))
        return True

    def drain_vendor_deletes(self) -> int:
        """Delete every queued voice at the vendor (the migration queues them; it
        never calls the vendor), for owners with the flag on. Returns how many went."""
        with self.database.tx() as c:
            queued = [(r["voice_id"], r["owner"]) for r in c.execute(
                "SELECT voice_id, owner FROM voice_records WHERE vendor_state = 'delete_queued' ORDER BY created_at")]
        return sum(1 for voice_id, owner in queued if self.enabled(owner) and self._delete_at_vendor(voice_id))

    def at_start(self) -> None:
        """App start: records for any voice without one, then the queued vendor deletes."""
        try:
            self.backfill()
            self.drain_vendor_deletes()
            self.expire_reviews()
        except Exception as exc:  # noqa: BLE001 - never stops the server starting
            self._alarm("start-up pass", exc)


class GuardedVoice:
    """The voice adapter with the vendor behind the guard: synthesis (`synthesize`,
    `speak_like`, `revoice`) and cloning (`create_clone`) reach the vendor only
    inside a pass the guard opened, for an owner with the flag on. Everything
    else, reads and writes alike, goes straight to the adapter it wraps, and a
    method the adapter lacks is missing here too (the pipeline asks `hasattr`)."""

    SYNTHESIS = {"synthesize": "synthesis", "speak_like": "speech to speech", "revoice": "voice change"}

    def __init__(self, inner, guard: VoiceGuard) -> None:
        self.__dict__["_inner"] = inner
        self.__dict__["_guard"] = guard

    @property
    def inner(self):
        return self.__dict__["_inner"]

    def __getattr__(self, name: str):
        value = getattr(self.__dict__["_inner"], name)          # AttributeError when the adapter has none
        if name in self.SYNTHESIS and callable(value):
            what = self.SYNTHESIS[name]

            def guarded(source, *args, **kwargs):
                self._synth(source, what)
                return value(source, *args, **kwargs)
            return guarded
        if name == "create_clone" and callable(value):
            def guarded_clone(clone_name, reference, *args, **kwargs):
                self._clone(clone_name)
                return value(clone_name, reference, *args, **kwargs)
            return guarded_clone
        return value

    def __setattr__(self, name: str, value) -> None:
        setattr(self.__dict__["_inner"], name, value)

    def __delattr__(self, name: str) -> None:
        delattr(self.__dict__["_inner"], name)

    def _need(self, key: str, owner: str | None, what: str) -> None:
        guard: VoiceGuard = self.__dict__["_guard"]
        if has_pass(key) or not guard.enabled(owner):
            return
        log.error("a %s reached the voice vendor without the voice guard (%s)", what, key)
        from app.failures import OUR_END_REPORTED
        raise VoiceGuardError(GUARD_BYPASSED, OUR_END_REPORTED, 500, what=what)

    def _synth(self, source, what: str) -> None:
        video_id = getattr(source, "project_id", "") or ""
        self._need(synth_key(video_id), self.__dict__["_guard"]._owner_of(video_id) if video_id else None, what)

    def _clone(self, name: str) -> None:
        if any(k.startswith("clone:") for k in _PASSES.get()):
            return
        owner = self._owner_from_name(name)
        self._need(clone_key(owner or ""), owner, "clone")

    def _owner_from_name(self, name: str) -> str | None:
        """A speaker's clone is named voltage-<video id>-<speaker>: its video's owner."""
        rest = (name or "").removeprefix("voltage-")
        if rest == name or rest.startswith("mine-"):
            return None
        return self.__dict__["_guard"]._owner_of(rest.rsplit("-", 1)[0])
