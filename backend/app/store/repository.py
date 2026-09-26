"""Projects, their candidates, approved edits and chat (Phase 9a: SQLite).

Source is never mutated and edits only ever append (design spec §7). A
`ProjectRepository()` with no database is in-memory — the tests' default.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.models import ApprovedEdit, Consent, EditCandidate, Source, Transcript
from app.store import codec
from app.store.db import PROJECT_TABLES, Database

# Who owns a project until sign-in exists (Phase 9c): everyone is this owner.
LOCAL_OWNER = "local"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProjectRecord:
    """A snapshot of a project. Changes go through the repository."""
    source: Source                 # immutable original
    transcript: Transcript
    # None until the uploader confirms rights. Generation is refused without it.
    consent: Consent | None = None
    owner: str = LOCAL_OWNER
    created_at: str = ""


@dataclass(frozen=True)
class Speaker:
    """How the editor treats one diarized speaker: what to call them, and the
    voice their new lines are spoken in (None = the chat's voice)."""
    label: str                  # the diarization label, "A", "B", …
    name: str
    voice_id: str | None = None


@dataclass(frozen=True)
class Message:
    role: str   # "user" | "assistant"
    text: str
    at: str


def _record(row) -> ProjectRecord:
    return ProjectRecord(
        source=codec.source(json.loads(row["source"])),
        transcript=codec.transcript(json.loads(row["transcript"])),
        consent=Consent(row["consent_at"]) if row["consent_at"] else None,
        owner=row["owner"],
        created_at=row["created_at"],
    )


class ProjectRepository:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db or Database()

    def reset(self) -> None:
        """Clear all projects and the id counter. Intended for test isolation."""
        self.db.reset()

    def next_id(self) -> str:
        # A persisted counter, so an id is never reused — not even after a
        # delete, when stale links must not land on someone else's project.
        with self.db.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = 'project_counter'").fetchone()
            n = int(row["value"]) + 1 if row else 1
            c.execute(
                "INSERT INTO meta (key, value) VALUES ('project_counter', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(n),),
            )
        return f"p{n}"

    def create(
        self, source: Source, transcript: Transcript, consent: Consent | None = None,
        owner: str = LOCAL_OWNER,
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO projects (id, owner, created_at, source, transcript, consent_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (source.project_id, owner, _now(), json.dumps(codec.dump(source)),
                 json.dumps(codec.dump(transcript)), consent.granted_at if consent else None),
            )

    def grant_consent(self, project_id: str, consent: Consent) -> Consent | None:
        """Record consent for a project that was uploaded without it."""
        with self.db.tx() as c:
            # First grant wins, so re-confirming cannot quietly restamp the record.
            c.execute(
                "UPDATE projects SET consent_at = ? WHERE id = ? AND consent_at IS NULL",
                (consent.granted_at, project_id),
            )
            row = c.execute("SELECT consent_at FROM projects WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return Consent(row["consent_at"])

    def get(self, project_id: str) -> ProjectRecord | None:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _record(row) if row else None

    def list(self, owner: str) -> list[ProjectRecord]:
        """The owner's projects, newest first."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT * FROM projects WHERE owner = ? ORDER BY created_at DESC, id DESC", (owner,),
            ).fetchall()
        return [_record(r) for r in rows]

    def delete(self, project_id: str) -> bool:
        with self.db.tx() as c:
            gone = c.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount
            for table in PROJECT_TABLES:
                c.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        return gone > 0

    def update_transcript(self, project_id: str, transcript: Transcript) -> None:
        """Replace the transcript — only ever to add labels (speakers) to the
        same words; the source itself is never touched."""
        with self.db.tx() as c:
            c.execute(
                "UPDATE projects SET transcript = ? WHERE id = ?",
                (json.dumps(codec.dump(transcript)), project_id),
            )

    # ── speakers ──

    def speakers(self, project_id: str) -> list[Speaker]:
        """Every speaker in the transcript, with any name and voice set for them."""
        record = self.get(project_id)
        if record is None:
            return []
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM projects WHERE id = ?", (project_id,)).fetchone()
        saved = json.loads(row["speakers"] or "{}")
        labels = sorted({w.speaker for w in record.transcript.words if w.speaker is not None})
        return [
            Speaker(label, saved.get(label, {}).get("name") or f"Speaker {label}",
                    saved.get(label, {}).get("voice_id"))
            for label in labels
        ]

    def set_speaker(
        self, project_id: str, label: str, *, name: str | None = None,
        voice_id: str | None = None, clear_voice: bool = False,
    ) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            saved = json.loads(row["speakers"] or "{}")
            entry = saved.setdefault(label, {})
            if name is not None:
                entry["name"] = name
            if voice_id is not None:
                entry["voice_id"] = voice_id
            if clear_voice:
                entry.pop("voice_id", None)
            c.execute("UPDATE projects SET speakers = ? WHERE id = ?", (json.dumps(saved), project_id))

    # ── candidates ──

    def next_candidate_id(self, project_id: str) -> str:
        with self.db.tx() as c:
            c.execute(
                "UPDATE projects SET candidate_counter = candidate_counter + 1 WHERE id = ?",
                (project_id,),
            )
            row = c.execute(
                "SELECT candidate_counter FROM projects WHERE id = ?", (project_id,),
            ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return f"c{row['candidate_counter']}"

    def save_candidate(self, project_id: str, candidate: EditCandidate) -> None:
        # Every candidate ever previewed is retained (spec §7: nothing is lost)
        # and is what approval commits.
        with self.db.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO candidates (project_id, candidate_id, body) VALUES (?, ?, ?)",
                (project_id, candidate.candidate_id, json.dumps(codec.dump(candidate))),
            )

    def get_candidate(self, project_id: str, candidate_id: str) -> EditCandidate | None:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM candidates WHERE project_id = ? AND candidate_id = ?",
                (project_id, candidate_id),
            ).fetchone()
        return codec.candidate(json.loads(row["body"])) if row else None

    # ── approved edits ──

    def append_edit(self, project_id: str, edit: ApprovedEdit) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO edits (project_id, seq, body) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM edits WHERE project_id = ?), ?)",
                (project_id, project_id, json.dumps(codec.dump(edit))),
            )

    def list_edits(self, project_id: str) -> list[ApprovedEdit]:
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT body FROM edits WHERE project_id = ? ORDER BY seq", (project_id,),
            ).fetchall()
        return [codec.edit(json.loads(r["body"])) for r in rows]

    # ── chat ──

    def add_message(self, project_id: str, role: str, text: str) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO messages (project_id, seq, role, text, at) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE project_id = ?), ?, ?, ?)",
                (project_id, project_id, role, text, _now()),
            )

    def messages(self, project_id: str) -> list[Message]:
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT role, text, at FROM messages WHERE project_id = ? ORDER BY seq",
                (project_id,),
            ).fetchall()
        return [Message(r["role"], r["text"], r["at"]) for r in rows]
