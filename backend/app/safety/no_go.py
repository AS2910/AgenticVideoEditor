"""Voice consent V1, step 5: the public-figure block, the voice guard's
`NoGoCheck` (`voice_guard.no_go`).

On every clone the speaker's reference audio is turned into a speaker vector
with the same WavLM model as the consent check (SIM-o,
app.continuity.similarity) and compared with every `no_go_voices` entry:

    0.92 or more     block: clone_not_allowed, reason no_go
    0.84 to 0.92     hold: the clone waits for an admin (reason no_go_review);
                     Approve lets the next try through, Reject blocks it
    below 0.84       continue

The bands are the consent check's (`consent.PASS_AT`, `consent.REVIEW_FROM`).
The built-in public-figure name list (app.safety.figures) still runs first.
Every check that compared anything is one `no_go_checks` row.

What is kept: an entry keeps its vector only, never the clip it came from
(the admin's upload or the reported export is read once and let go). A held
clone's clip is copied aside while it waits, so the admin can listen, and
deleted the moment it is decided (or its entry removed).

When the voice cannot be measured (no speaker model here, too little audio,
an entry made by another model) and the list is not empty, the clone is held
for a person, as the consent check does with an unmeasured voice. An empty
list compares nothing and needs no model.

V2: `vendor`, a `VendorVoiceCheck` (a voice vendor's own public-figure check),
runs after the list when set; its block or review counts like the list's.

    VoiceListNoGo(database, embed, model=...).check(name=, reference=, owner=, video_id=, speaker_label=)
    .add(...), .remove(id), .entries(), .holds(status), .hold(id), .decide(id, approve, reason, who), .checks()
"""
from __future__ import annotations

import hashlib
import json
import logging
import secrets
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.continuity.similarity import cosine
from app.safety import consent
from app.safety.voice_guard import NoGoVerdict
from app.timefmt import iso

log = logging.getLogger("voltage.no_go")

BLOCK_AT = consent.PASS_AT          # 0.92
REVIEW_FROM = consent.REVIEW_FROM   # 0.84
MIN_SECONDS = 3.0                   # an entry needs this much of the voice (as the consent check's reference)
_WORKSPACE = "(SELECT id FROM workspaces WHERE owner = ? ORDER BY created_at, id LIMIT 1)"


class NoGoError(Exception):
    """An admin action that cannot be done; `status` for HTTP, `message` for the admin."""

    def __init__(self, message: str, status: int = 409) -> None:
        super().__init__(message)
        self.message, self.status = message, status


class VendorVoiceCheck(Protocol):
    """V2: a voice vendor's check of the reference against the public figures it knows.
    None (or a pass) when it has nothing to say."""
    name: str

    def check(self, reference: Path) -> NoGoVerdict | None: ...


def _id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class VoiceListNoGo:
    """The no-go list's check, entries and borderline queue over the app's database.
    `embed(path) -> unit vector | None` is the speaker model (injected; tests fake it)."""

    database: Any
    embed: Callable[[Path], list[float] | None]
    model: str = ""
    names: Any = None                                   # voice_guard.NameListNoGo, or None
    vendor: VendorVoiceCheck | None = None              # V2
    hold_dir: Path | None = None                        # where a held clip waits; None: not kept
    on_hold: Callable[[dict], None] | None = None       # a new hold (the app tells the admins)
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    block_at: float = BLOCK_AT
    review_from: float = REVIEW_FROM
    name: str = field(default="voice list")

    def _now(self) -> str:
        return iso(self.clock())

    # ── the check, on every clone ──

    def check(self, *, name: str | None, reference: Path | None, owner: str | None = None, video_id: str | None = None,
              speaker_label: str | None = None, speaker_name: str | None = None, **_) -> NoGoVerdict:
        who = {"owner": owner or "", "video_id": video_id, "speaker_label": speaker_label, "speaker_name": speaker_name or name}
        if self.names is not None:
            by_name = self.names.check(name=name, reference=None)
            if by_name.verdict == "block":
                self._log(who, "block", "name", top=(None, by_name.match, None))
                return by_name
        if reference is None:
            return NoGoVerdict("pass", how=self.name)          # no audio yet: the caller asks again with it
        entries = self._vectors()
        if not entries and self.vendor is None:
            return NoGoVerdict("pass", how=self.name)          # nothing to compare with
        subject = self._subject(video_id, speaker_label, reference)
        verdict = self._against(entries, reference, who, subject) if entries else None
        if verdict is not None and verdict.verdict != "pass":
            return verdict
        if self.vendor is not None:
            said = self._vendor(reference, who, subject)
            if said is not None:
                return said
        return verdict or NoGoVerdict("pass", how=self.name)

    def _against(self, entries: list[dict], reference: Path, who: dict, subject: str) -> NoGoVerdict:
        vector = self.embed(reference)
        scores = []
        for e in entries:
            comparable = vector is not None and e["vector"] is not None and (e["model"] or self.model) == self.model
            scores.append({"id": e["id"], "name": e["name"], "score": cosine(vector, e["vector"]) if comparable else None})
        scores.sort(key=lambda s: -1.0 if s["score"] is None else s["score"], reverse=True)
        measured = [s for s in scores if s["score"] is not None]
        top = measured[0] if measured else None
        top_of = (top["id"], top["name"], top["score"]) if top else (None, None, None)
        if top is not None and top["score"] >= self.block_at:
            self._log(who, "block", "voice", top=top_of, scores=scores)
            return NoGoVerdict("block", top["name"], top["score"], "voice")
        # Every borderline entry needs its own approval; one rejected is a block.
        approved = False
        waits = [s for s in measured if s["score"] >= self.review_from]
        if len(measured) < len(scores):
            waits.append({"id": None, "name": None, "score": None})      # unmeasured: a person listens
        for s in waits:
            found = self._decision(who["owner"], subject, s["id"])
            how = "voice" if s["id"] is not None else "unmeasured"
            if found is not None and found["status"] == "approved":
                approved = True
                continue
            if found is not None and found["status"] == "rejected":
                self._log(who, "block", "rejected", top=(s["id"], s["name"], s["score"]), scores=scores, hold_id=found["id"])
                return NoGoVerdict("block", s["name"], s["score"], "rejected", hold_id=found["id"])
            hold_id = found["id"] if found is not None else self._hold(who, subject, s, reference)
            self._log(who, "review", how, top=(s["id"], s["name"], s["score"]), scores=scores, hold_id=hold_id)
            return NoGoVerdict("review", s["name"], s["score"], how, hold_id=hold_id)
        self._log(who, "pass", "approved" if approved else "voice", top=top_of, scores=scores)
        return NoGoVerdict("pass", top_of[1], top_of[2], "approved" if approved else self.name)

    def _vendor(self, reference: Path, who: dict, subject: str) -> NoGoVerdict | None:
        try:
            said = self.vendor.check(reference)
        except Exception as exc:  # noqa: BLE001 - a vendor that cannot answer holds the clone for a person
            log.warning("vendor no-go check failed: %s", exc)
            said = NoGoVerdict("review", how="vendor")
        if said is None or said.verdict == "pass":
            return None
        ref = f"vendor:{said.match or self.vendor.name}"
        if said.verdict == "block":
            self._log(who, "block", "vendor", top=(ref, said.match, said.score))
            return NoGoVerdict("block", said.match, said.score, "vendor")
        found = self._decision(who["owner"], subject, ref)
        if found is not None and found["status"] == "approved":
            return None
        if found is not None and found["status"] == "rejected":
            self._log(who, "block", "rejected", top=(ref, said.match, said.score), hold_id=found["id"])
            return NoGoVerdict("block", said.match, said.score, "rejected", hold_id=found["id"])
        hold_id = found["id"] if found is not None else self._hold(who, subject, {"id": ref, "name": said.match,
                                                                               "score": said.score}, reference)
        self._log(who, "review", "vendor", top=(ref, said.match, said.score), hold_id=hold_id)
        return NoGoVerdict("review", said.match, said.score, "vendor", hold_id=hold_id)

    @staticmethod
    def _subject(video_id: str | None, speaker_label: str | None, reference: Path) -> str:
        """What an admin's decision covers: this video's speaker, or (an uploaded recording) this exact audio."""
        if video_id:
            return f"video:{video_id}:{speaker_label or '_'}"
        try:
            return f"audio:{_sha(reference)}"
        except OSError:
            return f"audio:{reference.name}"

    def _decision(self, owner: str, subject: str, no_go_id: str | None) -> dict | None:
        with self.database.tx() as c:
            row = c.execute("SELECT id, status FROM no_go_holds WHERE owner = ? AND subject = ? AND COALESCE(no_go_id, '') = ? "
                            "AND status IN ('waiting', 'approved', 'rejected') ORDER BY created_at DESC, id DESC LIMIT 1",
                            (owner, subject, no_go_id or "")).fetchone()
        return dict(row) if row else None

    def _hold(self, who: dict, subject: str, s: dict, reference: Path) -> str:
        hold_id = _id("ngh")
        kept = None
        if self.hold_dir is not None:
            try:
                self.hold_dir.mkdir(parents=True, exist_ok=True)
                kept = self.hold_dir / f"{hold_id}{reference.suffix or '.wav'}"
                shutil.copyfile(reference, kept)
            except OSError as exc:
                log.warning("held clip not kept: %s", exc)
                kept = None
        row = {"id": hold_id, "owner": who["owner"], "video_id": who["video_id"], "speaker_label": who["speaker_label"],
               "speaker_name": who["speaker_name"], "subject": subject, "no_go_id": s["id"], "no_go_name": s["name"],
               "score": s["score"], "model": self.model, "audio_path": str(kept) if kept else None, "status": "waiting",
               "created_at": self._now()}
        with self.database.tx() as c:
            c.execute("INSERT INTO no_go_holds (id, workspace_id, owner, video_id, speaker_label, speaker_name, subject, no_go_id, "
                      f"no_go_name, score, model, audio_path, status, created_at) VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, ?, ?, ?, ?, "
                      "?, ?, 'waiting', ?)",
                      (hold_id, row["owner"], row["owner"], row["video_id"], row["speaker_label"], row["speaker_name"], subject,
                       row["no_go_id"], row["no_go_name"], row["score"], self.model, row["audio_path"], row["created_at"]))
        if self.on_hold is not None:
            try:
                self.on_hold(row)
            except Exception as exc:  # noqa: BLE001 - telling the admins is a nicety; the hold stands
                log.warning("no-go hold not announced: %s", exc)
        return hold_id

    def _log(self, who: dict, verdict: str, how: str, *, top: tuple, scores: list | None = None,
             hold_id: str | None = None) -> None:
        """One row per check that compared anything. Never fails the clone (the verdict stands)."""
        try:
            with self.database.tx() as c:
                c.execute("INSERT INTO no_go_checks (id, workspace_id, owner, video_id, speaker_label, speaker_name, verdict, how, "
                          f"no_go_id, no_go_name, score, scores, model, hold_id, created_at) VALUES (?, {_WORKSPACE}, ?, ?, ?, ?, "
                          "?, ?, ?, ?, ?, ?, ?, ?, ?)",
                          (_id("ngc"), who["owner"], who["owner"], who["video_id"], who["speaker_label"], who["speaker_name"],
                           verdict, how, top[0], top[1], top[2], json.dumps(scores or []),
                           self.model if how != "name" else "", hold_id, self._now()))
        except Exception as exc:  # noqa: BLE001
            log.warning("no-go check not logged: %s", exc)

    # ── the list (admins) ──

    def _vectors(self) -> list[dict]:
        with self.database.tx() as c:
            rows = c.execute("SELECT id, name, model, reference_embedding FROM no_go_voices ORDER BY created_at, id").fetchall()
        out = []
        for r in rows:
            try:
                vector = json.loads(r["reference_embedding"]) if r["reference_embedding"] else None
            except ValueError:
                vector = None
            out.append({"id": r["id"], "name": r["name"], "model": r["model"] or "", "vector": vector})
        return out

    @staticmethod
    def _entry(r) -> dict:
        d = dict(r)
        try:
            dims = len(json.loads(d.pop("reference_embedding") or "[]"))
        except ValueError:
            dims = 0
        return {**d, "dims": dims}

    def entries(self) -> list[dict]:
        """The list as an admin sees it: never the vectors themselves."""
        with self.database.tx() as c:
            return [self._entry(r) for r in c.execute("SELECT * FROM no_go_voices ORDER BY created_at DESC, id DESC")]

    def add(self, *, name: str, reason: str, embedding: list[float], added_by: str, source: str, source_ref: str = "",
            seconds: float | None = None) -> dict:
        entry_id = _id("ngv")
        with self.database.tx() as c:
            c.execute("INSERT INTO no_go_voices (id, name, reason, reference_embedding, added_by, created_at, workspace_id, model, "
                      "source, source_ref, seconds) VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)",
                      (entry_id, name, reason, json.dumps([round(float(x), 7) for x in embedding]), added_by, self._now(),
                       self.model, source, source_ref, seconds))
            row = c.execute("SELECT * FROM no_go_voices WHERE id = ?", (entry_id,)).fetchone()
        return self._entry(row)

    def remove(self, entry_id: str, *, reason: str, who: str) -> tuple[dict, int]:
        """The entry goes; any clone still waiting on it is closed (nothing left to hold it for), its clip deleted."""
        with self.database.tx() as c:
            row = c.execute("SELECT * FROM no_go_voices WHERE id = ?", (entry_id,)).fetchone()
            if row is None:
                raise NoGoError("No such voice on the list.", 404)
            waiting = c.execute("SELECT id, audio_path FROM no_go_holds WHERE no_go_id = ? AND status = 'waiting'",
                                (entry_id,)).fetchall()
            c.execute("UPDATE no_go_holds SET status = 'closed', reason = ?, decided_by = ?, decided_at = ?, audio_path = NULL "
                      "WHERE no_go_id = ? AND status = 'waiting'", (f"entry removed: {reason}", who, self._now(), entry_id))
            c.execute("DELETE FROM no_go_voices WHERE id = ?", (entry_id,))
        for w in waiting:
            self._forget(w["audio_path"])
        return self._entry(row), len(waiting)

    # ── the borderline queue (admins) ──

    def holds(self, status: str = "waiting", limit: int = 50) -> tuple[list[dict], int]:
        """Waiting (oldest first, so the longest wait is on top), or the decided ones, newest first."""
        with self.database.tx() as c:
            if status == "waiting":
                rows = c.execute("SELECT * FROM no_go_holds WHERE status = 'waiting' ORDER BY created_at, id LIMIT ?", (limit,))
            else:
                rows = c.execute("SELECT * FROM no_go_holds WHERE status != 'waiting' ORDER BY decided_at DESC, id DESC LIMIT ?",
                                 (limit,))
            rows = [self._hold_row(r) for r in rows.fetchall()]
            waiting = c.execute("SELECT COUNT(*) FROM no_go_holds WHERE status = 'waiting'").fetchone()[0]
        return rows, int(waiting)

    def _hold_row(self, r) -> dict:
        d = dict(r)
        path = d.pop("audio_path", None)
        return {**d, "has_audio": bool(path) and Path(path).exists(), "block_at": self.block_at, "review_from": self.review_from}

    def hold(self, hold_id: str) -> dict:
        with self.database.tx() as c:
            row = c.execute("SELECT * FROM no_go_holds WHERE id = ?", (hold_id,)).fetchone()
        if row is None:
            raise NoGoError("No such held clone.", 404)
        return dict(row)

    def hold_audio(self, hold_id: str) -> Path | None:
        path = self.hold(hold_id)["audio_path"]
        return Path(path) if path and Path(path).exists() else None

    def decide(self, hold_id: str, *, approve: bool, reason: str, who: str, allow_own: bool = False) -> dict:
        """Approve (the next try of this clone goes through) or reject (it is blocked). An admin never
        decides a clone of their own, unless sign-in is off (one person is everyone)."""
        row = self.hold(hold_id)
        if row["status"] != "waiting":
            raise NoGoError("That clone is not waiting for a decision any more.", 409)
        if row["owner"] == who and not allow_own:
            raise NoGoError("Another admin decides a clone of your own.", 403)
        with self.database.tx() as c:
            c.execute("UPDATE no_go_holds SET status = ?, reason = ?, decided_by = ?, decided_at = ?, audio_path = NULL "
                      "WHERE id = ? AND status = 'waiting'", ("approved" if approve else "rejected", reason, who, self._now(), hold_id))
        self._forget(row["audio_path"])
        return self._hold_row(self.hold(hold_id) | {"audio_path": None})

    @staticmethod
    def _forget(path: str | None) -> None:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError as exc:
                log.warning("held clip not deleted: %s", exc)

    def checks(self, limit: int = 50) -> list[dict]:
        with self.database.tx() as c:
            rows = c.execute("SELECT * FROM no_go_checks ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["scores"] = json.loads(d["scores"] or "[]")
            except ValueError:
                d["scores"] = []
            out.append(d)
        return out
