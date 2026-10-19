"""Videos, their candidates, approved edits and chat (Phase 9a: SQLite), and
the projects (folders) they sit in.

Source is never mutated and edits only ever append (design spec §7). A
`ProjectRepository()` with no database is in-memory — the tests' default.

Names (Folders): a *video* is what used to be called a project — one clip
with everything made on it; its id stays `p<n>`, and the Python attribute
names that carry it (`project_id` on sources, plans, candidates and the
child tables' columns) stay too. A *project* is a folder of videos, `f<n>`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.domain.models import ApprovedEdit, Consent, EditCandidate, Source, Transcript
from app.domain.plan import Plan, plan_from_dict
from app.store import codec
from app.store.db import PROJECT_TABLES, Database

# Who owns a project until sign-in exists (Phase 9c): everyone is this owner.
LOCAL_OWNER = "local"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class ProjectRecord:
    """A snapshot of a video. Changes go through the repository."""
    source: Source                 # immutable original
    transcript: Transcript
    # None until the uploader confirms rights. Generation is refused without it.
    consent: Consent | None = None
    owner: str = LOCAL_OWNER
    created_at: str = ""
    # Folders: the project (folder) the video is in, or None when standalone.
    folder_id: str | None = None


@dataclass(frozen=True)
class Project:
    """A folder of videos (Folders): a name, a brief, defaults for new videos,
    an optional spending ceiling. Its voices, files and brief suggestions
    live in meta lists keyed by its id."""
    project_id: str
    owner: str
    name: str
    brief: str = ""
    settings: dict = field(default_factory=dict)
    ceiling_usd: float | None = None
    created_at: str = ""


@dataclass(frozen=True)
class Speaker:
    """How the editor treats one diarized speaker: what to call them, and the
    voice their new lines are spoken in (None = the chat's voice)."""
    label: str                  # the diarization label, "A", "B", …
    name: str
    voice_id: str | None = None
    # 15a: the speaker's own cloned voice at the vendor, once made.
    clone_voice_id: str | None = None


@dataclass(frozen=True)
class Message:
    role: str   # "user" | "assistant"
    text: str
    at: str
    kind: str = "say"          # "say" (a message) | "step" (one thing Voltage did, Phase 20) | "previews" (voices to hear, 20b)
    cost: float | None = None  # what a step cost, in dollars
    seq: int = 0
    data: dict | None = None   # a card's facts, e.g. the previews' ids and audio


def _record(row) -> ProjectRecord:
    return ProjectRecord(
        source=codec.source(json.loads(row["source"])),
        transcript=codec.transcript(json.loads(row["transcript"])),
        consent=Consent(row["consent_at"]) if row["consent_at"] else None,
        owner=row["owner"],
        created_at=row["created_at"],
        folder_id=row["project_id"] if "project_id" in row.keys() else None,
    )


def _project(row) -> Project:
    return Project(project_id=row["id"], owner=row["owner"], name=row["name"], brief=row["brief"] or "",
                   settings=json.loads(row["settings"] or "{}"), ceiling_usd=row["ceiling_usd"], created_at=row["created_at"])


# `list(owner)` lists every video; `list(owner, folder=None)` the standalone ones.
ANY_FOLDER = "*"


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
        owner: str = LOCAL_OWNER, folder_id: str | None = None,
    ) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO videos (id, owner, created_at, source, transcript, consent_at, project_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (source.project_id, owner, _now(), json.dumps(codec.dump(source)),
                 json.dumps(codec.dump(transcript)), consent.granted_at if consent else None, folder_id),
            )

    def grant_consent(self, project_id: str, consent: Consent) -> Consent | None:
        """Record consent for a project that was uploaded without it."""
        with self.db.tx() as c:
            # First grant wins, so re-confirming cannot quietly restamp the record.
            c.execute(
                "UPDATE videos SET consent_at = ? WHERE id = ? AND consent_at IS NULL",
                (consent.granted_at, project_id),
            )
            row = c.execute("SELECT consent_at FROM videos WHERE id = ?", (project_id,)).fetchone()
        if row is None:
            return None
        return Consent(row["consent_at"])

    def get(self, project_id: str) -> ProjectRecord | None:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM videos WHERE id = ?", (project_id,)).fetchone()
        return _record(row) if row else None

    def list(self, owner: str, folder: str | None = ANY_FOLDER) -> list[ProjectRecord]:
        """The owner's videos, newest first; `folder` narrows to one project
        (an id) or to the standalone ones (None)."""
        where, args = "owner = ?", [owner]
        if folder is None:
            where += " AND project_id IS NULL"
        elif folder != ANY_FOLDER:
            where += " AND project_id = ?"
            args.append(folder)
        with self.db.tx() as c:
            rows = c.execute(
                f"SELECT * FROM videos WHERE {where} ORDER BY created_at DESC, id DESC", args,
            ).fetchall()
        return [_record(r) for r in rows]

    def set_folder(self, project_id: str, folder_id: str | None) -> bool:
        """Move a video into a project (or out, with None). Everything made on
        the video stays with it."""
        with self.db.tx() as c:
            changed = c.execute("UPDATE videos SET project_id = ? WHERE id = ?", (folder_id, project_id)).rowcount
        return changed > 0

    def delete(self, project_id: str) -> bool:
        with self.db.tx() as c:
            gone = c.execute("DELETE FROM videos WHERE id = ?", (project_id,)).rowcount
            for table in PROJECT_TABLES:
                c.execute(f"DELETE FROM {table} WHERE project_id = ?", (project_id,))
        return gone > 0

    def update_transcript(self, project_id: str, transcript: Transcript) -> None:
        """Replace the transcript — only ever to add labels (speakers) to the
        same words; the source itself is never touched."""
        with self.db.tx() as c:
            c.execute(
                "UPDATE videos SET transcript = ? WHERE id = ?",
                (json.dumps(codec.dump(transcript)), project_id),
            )

    # ── speakers ──

    def speakers(self, project_id: str) -> list[Speaker]:
        """Every speaker in the transcript, with any name and voice set for them."""
        record = self.get(project_id)
        if record is None:
            return []
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM videos WHERE id = ?", (project_id,)).fetchone()
        saved = json.loads(row["speakers"] or "{}")
        labels = sorted({w.speaker for w in record.transcript.words if w.speaker is not None})
        return [
            Speaker(label, saved.get(label, {}).get("name") or f"Speaker {label}",
                    saved.get(label, {}).get("voice_id"), saved.get(label, {}).get("clone_voice_id"))
            for label in labels
        ]

    # A clip with no diarization has one voice; its clone is kept under this key.
    WHOLE_CLIP = "_"

    def clones(self, project_id: str) -> dict[str, str]:
        """Every clone made for this project, by speaker label (or WHOLE_CLIP)."""
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM videos WHERE id = ?", (project_id,)).fetchone()
        saved = json.loads((row["speakers"] if row else None) or "{}")
        return {k: v["clone_voice_id"] for k, v in saved.items() if v.get("clone_voice_id")}

    def set_clone(self, project_id: str, key: str, voice_id: str | None) -> None:
        """Remember (or, with None, forget) the clone made for one speaker."""
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM videos WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            saved = json.loads(row["speakers"] or "{}")
            entry = saved.setdefault(key, {})
            if voice_id is None:
                entry.pop("clone_voice_id", None)
            else:
                entry["clone_voice_id"] = voice_id
            c.execute("UPDATE videos SET speakers = ? WHERE id = ?", (json.dumps(saved), project_id))

    def set_speaker(
        self, project_id: str, label: str, *, name: str | None = None,
        voice_id: str | None = None, clear_voice: bool = False,
    ) -> None:
        with self.db.tx() as c:
            row = c.execute("SELECT speakers FROM videos WHERE id = ?", (project_id,)).fetchone()
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
            c.execute("UPDATE videos SET speakers = ? WHERE id = ?", (json.dumps(saved), project_id))

    # ── candidates ──

    def next_candidate_id(self, project_id: str) -> str:
        with self.db.tx() as c:
            c.execute(
                "UPDATE videos SET candidate_counter = candidate_counter + 1 WHERE id = ?",
                (project_id,),
            )
            row = c.execute(
                "SELECT candidate_counter FROM videos WHERE id = ?", (project_id,),
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

    def candidates(self, project_id: str) -> list[EditCandidate]:
        """Every take ever made for the project, in the order they were made
        (the receipt counts them)."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT body FROM candidates WHERE project_id = ? ORDER BY rowid", (project_id,),
            ).fetchall()
        return [codec.candidate(json.loads(r["body"])) for r in rows]

    # ── approved edits ──

    def append_edit(self, project_id: str, edit: ApprovedEdit) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO edits (project_id, seq, body) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM edits WHERE project_id = ?), ?)",
                (project_id, project_id, json.dumps(codec.dump(edit))),
            )

    def list_edits(self, project_id: str) -> list[ApprovedEdit]:
        """Every approved edit in approval order, reverted ones included —
        callers that render or count skip `reverted` themselves."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT body FROM edits WHERE project_id = ? ORDER BY seq", (project_id,),
            ).fetchall()
        return [codec.edit(json.loads(r["body"])) for r in rows]

    def relink_edit(self, project_id: str, edit_id: str, partner: str | None) -> bool:
        """Point an edit at its new other half (a shifted line moved again)."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT seq, body FROM edits WHERE project_id = ? ORDER BY seq", (project_id,),
            ).fetchall()
            for row in rows:
                body = json.loads(row["body"])
                if body["edit_id"] == edit_id:
                    body["partner"] = partner
                    c.execute("UPDATE edits SET body = ? WHERE project_id = ? AND seq = ?",
                              (json.dumps(body), project_id, row["seq"]))
                    return True
        return False

    def revert_edit(self, project_id: str, edit_id: str) -> bool:
        """Mark an approved edit undone (Phase 12). The record stays — edits
        only ever append — but the render skips it. False if there is no such
        edit; reverting twice is harmless."""
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT seq, body FROM edits WHERE project_id = ? ORDER BY seq", (project_id,),
            ).fetchall()
            for row in rows:
                body = json.loads(row["body"])
                if body["edit_id"] == edit_id:
                    body["reverted"] = True
                    c.execute(
                        "UPDATE edits SET body = ? WHERE project_id = ? AND seq = ?",
                        (json.dumps(body), project_id, row["seq"]),
                    )
                    return True
        return False

    # ── meta: owner-level facts that belong to no project (the user's own voices, 20i) ──

    def get_meta(self, key: str) -> str | None:
        with self.db.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def set_meta(self, key: str, value: str) -> None:
        with self.db.tx() as c:
            c.execute("INSERT INTO meta (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value", (key, value))

    def delete_meta(self, key: str) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM meta WHERE key = ?", (key,))

    def meta_with_prefix(self, prefix: str) -> dict[str, str]:
        """Every meta row under one prefix — e.g. everyone's own voices, so a
        voice kept by anyone is never deleted with a project."""
        with self.db.tx() as c:
            rows = c.execute("SELECT key, value FROM meta WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}

    # ── projects as folders ──

    def next_project_id(self) -> str:
        with self.db.tx() as c:
            row = c.execute("SELECT value FROM meta WHERE key = 'folder_counter'").fetchone()
            n = int(row["value"]) + 1 if row else 1
            c.execute(
                "INSERT INTO meta (key, value) VALUES ('folder_counter', ?) "
                "ON CONFLICT (key) DO UPDATE SET value = excluded.value", (str(n),),
            )
        return f"f{n}"

    def create_project(self, owner: str, name: str, brief: str = "", settings: dict | None = None,
                       ceiling_usd: float | None = None) -> Project:
        project_id = self.next_project_id()
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO projects (id, owner, name, brief, settings, ceiling_usd, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, owner, name, brief, json.dumps(settings or {}), ceiling_usd, _now()),
            )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> Project | None:
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        return _project(row) if row else None

    def list_projects(self, owner: str) -> list[Project]:
        """The owner's projects, oldest first (the sidebar keeps their order)."""
        with self.db.tx() as c:
            rows = c.execute("SELECT * FROM projects WHERE owner = ? ORDER BY created_at, id", (owner,)).fetchall()
        return [_project(r) for r in rows]

    def update_project(self, project_id: str, *, name: str | None = None, brief: str | None = None,
                       settings: dict | None = None, ceiling_usd: float | None = None,
                       clear_ceiling: bool = False) -> Project | None:
        """Change a project's fields; `settings` merges into the defaults."""
        with self.db.tx() as c:
            row = c.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                return None
            merged = json.loads(row["settings"] or "{}")
            if settings is not None:
                merged.update({k: v for k, v in settings.items() if v is not None})
            c.execute(
                "UPDATE projects SET name = ?, brief = ?, settings = ?, ceiling_usd = ? WHERE id = ?",
                (name if name is not None else row["name"], brief if brief is not None else row["brief"],
                 json.dumps(merged), None if clear_ceiling else (ceiling_usd if ceiling_usd is not None else row["ceiling_usd"]),
                 project_id),
            )
        return self.get_project(project_id)

    def delete_project(self, project_id: str, keep_videos: bool) -> bool:
        """Delete a folder: its videos become standalone (`keep_videos`), or
        are left for the caller to delete first. Its meta lists go with it."""
        with self.db.tx() as c:
            gone = c.execute("DELETE FROM projects WHERE id = ?", (project_id,)).rowcount
            if keep_videos:
                c.execute("UPDATE videos SET project_id = NULL WHERE project_id = ?", (project_id,))
            for prefix in ("project_voices", "project_files", "brief_suggestions"):
                c.execute("DELETE FROM meta WHERE key = ?", (f"{prefix}:{project_id}",))
        return gone > 0

    def meta_list(self, key: str) -> list:
        return json.loads(self.get_meta(key) or "[]")

    def set_meta_list(self, key: str, items: list) -> None:
        self.set_meta(key, json.dumps(items))

    # ── settings ──

    def settings(self, project_id: str) -> dict:
        """Per-video preferences: the autonomy, what a turn may spend, the effort."""
        with self.db.tx() as c:
            row = c.execute("SELECT settings FROM videos WHERE id = ?", (project_id,)).fetchone()
        return json.loads(row["settings"] or "{}") if row else {}

    def set_settings(self, project_id: str, **changes) -> dict:
        with self.db.tx() as c:
            row = c.execute("SELECT settings FROM videos WHERE id = ?", (project_id,)).fetchone()
            if row is None:
                raise KeyError(project_id)
            saved = json.loads(row["settings"] or "{}")
            saved.update({k: v for k, v in changes.items() if v is not None})
            c.execute("UPDATE videos SET settings = ? WHERE id = ?", (json.dumps(saved), project_id))
        return saved

    # ── chat ──

    def add_message(self, project_id: str, role: str, text: str, kind: str = "say", cost: float | None = None,
                    data: dict | None = None) -> int:
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO messages (project_id, seq, role, text, at, kind, cost, data) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM messages WHERE project_id = ?), ?, ?, ?, ?, ?, ?)",
                (project_id, project_id, role, text, _now(), kind, cost, json.dumps(data) if data is not None else None),
            )
            return int(c.execute("SELECT MAX(seq) FROM messages WHERE project_id = ?", (project_id,)).fetchone()[0])

    def count_steps(self, project_id: str, text: str, since: str | None = None) -> int:
        """How many step messages say exactly `text` — one "Thinking" per
        turn, so this is how turns are counted — from `since` on when given."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COUNT(*) AS n FROM messages WHERE project_id = ? AND kind = 'step' AND text = ?"
                + (" AND at >= ?" if since else ""),
                (project_id, text) + ((since,) if since else ()),
            ).fetchone()
        return int(row["n"])

    def messages(self, project_id: str, after: int = 0) -> list[Message]:
        with self.db.tx() as c:
            rows = c.execute(
                "SELECT role, text, at, kind, cost, seq, data FROM messages WHERE project_id = ? AND seq > ? ORDER BY seq",
                (project_id, after),
            ).fetchall()
        return [Message(r["role"], r["text"], r["at"], r["kind"] or "say", r["cost"], r["seq"],
                        json.loads(r["data"]) if r["data"] else None) for r in rows]

    # ── the model's own thread (Phase 20) ──

    def append_turn(self, project_id: str, role: str, content) -> None:
        """One message as the model saw it: a string or content blocks. Append-only."""
        with self.db.tx() as c:
            c.execute(
                "INSERT INTO turns (project_id, seq, role, content, at) VALUES (?, "
                "(SELECT COALESCE(MAX(seq), 0) + 1 FROM turns WHERE project_id = ?), ?, ?, ?)",
                (project_id, project_id, role, json.dumps(content), _now()),
            )

    def turns(self, project_id: str) -> list[dict]:
        with self.db.tx() as c:
            rows = c.execute("SELECT role, content FROM turns WHERE project_id = ? ORDER BY seq", (project_id,)).fetchall()
        return [{"role": r["role"], "content": json.loads(r["content"])} for r in rows]

    # ── plans (Phase 13) ──

    def next_plan_id(self, project_id: str) -> str:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT COALESCE(MAX(seq), 0) AS n FROM plans WHERE project_id = ?", (project_id,),
            ).fetchone()
        return f"plan{int(row['n']) + 1}"

    def save_plan(self, plan: Plan) -> None:
        """Insert or replace the whole plan — items change as the run goes."""
        body = json.dumps(codec.dump(plan))
        with self.db.tx() as c:
            row = c.execute(
                "SELECT seq FROM plans WHERE project_id = ? AND plan_id = ?",
                (plan.project_id, plan.plan_id),
            ).fetchone()
            if row:
                c.execute("UPDATE plans SET body = ? WHERE project_id = ? AND plan_id = ?",
                          (body, plan.project_id, plan.plan_id))
            else:
                c.execute(
                    "INSERT INTO plans (project_id, plan_id, seq, body) VALUES (?, ?, "
                    "(SELECT COALESCE(MAX(seq), 0) + 1 FROM plans WHERE project_id = ?), ?)",
                    (plan.project_id, plan.plan_id, plan.project_id, body),
                )

    def get_plan(self, project_id: str, plan_id: str) -> Plan | None:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM plans WHERE project_id = ? AND plan_id = ?", (project_id, plan_id),
            ).fetchone()
        return plan_from_dict(json.loads(row["body"])) if row else None

    def plans(self, project_id: str) -> list[Plan]:
        """Every plan of the project, oldest first."""
        with self.db.tx() as c:
            rows = c.execute("SELECT body FROM plans WHERE project_id = ? ORDER BY seq", (project_id,)).fetchall()
        return [plan_from_dict(json.loads(r["body"])) for r in rows]

    def latest_plan(self, project_id: str) -> Plan | None:
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM plans WHERE project_id = ? ORDER BY seq DESC LIMIT 1", (project_id,),
            ).fetchone()
        return plan_from_dict(json.loads(row["body"])) if row else None

    def update_item(self, project_id: str, plan_id: str, item_id: str, **changes) -> Plan | None:
        """Change one item inside a transaction, so a running job and a
        request editing another item never overwrite each other."""
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM plans WHERE project_id = ? AND plan_id = ?", (project_id, plan_id),
            ).fetchone()
            if row is None:
                return None
            plan = plan_from_dict(json.loads(row["body"])).with_item(item_id, **changes)
            c.execute("UPDATE plans SET body = ? WHERE project_id = ? AND plan_id = ?",
                      (json.dumps(codec.dump(plan)), project_id, plan_id))
        return plan

    def update_plan(self, project_id: str, plan_id: str, **changes) -> Plan | None:
        """Change the plan's own fields (status, log) under the same lock."""
        from dataclasses import replace as _replace
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM plans WHERE project_id = ? AND plan_id = ?", (project_id, plan_id),
            ).fetchone()
            if row is None:
                return None
            plan = _replace(plan_from_dict(json.loads(row["body"])), **changes)
            c.execute("UPDATE plans SET body = ? WHERE project_id = ? AND plan_id = ?",
                      (json.dumps(codec.dump(plan)), project_id, plan_id))
        return plan

    def append_log(self, project_id: str, plan_id: str, text: str, detail: str = "") -> None:
        """Add a line to what Voltage did, under the same lock as item updates."""
        from dataclasses import replace as _replace
        entry = {"at": _now(), "text": text, "detail": detail}
        with self.db.tx() as c:
            row = c.execute(
                "SELECT body FROM plans WHERE project_id = ? AND plan_id = ?", (project_id, plan_id),
            ).fetchone()
            if row is None:
                return
            plan = plan_from_dict(json.loads(row["body"]))
            plan = _replace(plan, log=plan.log + (entry,))
            c.execute("UPDATE plans SET body = ? WHERE project_id = ? AND plan_id = ?",
                      (json.dumps(codec.dump(plan)), project_id, plan_id))
