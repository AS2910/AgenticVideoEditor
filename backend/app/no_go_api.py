"""Voice consent V1, step 5: the no-go list and its borderline queue (admins
only, 404 for anyone else; every write audited). The check itself is
app.safety.no_go, run by the voice guard on every clone.

    GET    /admin/no-go-voices               the list (never the vectors), the bands, the speaker model
    POST   /admin/no-go-voices               multipart: name, reason, and the voice: `file` (a clip), or a
                                             reported export (`mark`, or `abuse_report_id` naming one), with
                                             an optional `start`/`end` in seconds. The clip is read once into a
                                             speaker vector and let go; only the vector is kept (audited no_go_add)
    DELETE /admin/no-go-voices/{id}          {reason}: off the list; clones waiting on it are closed (no_go_remove)
    GET    /admin/no-go-holds?status=        waiting (oldest first) | decided: clones from 0.84 to 0.92 of an entry
    GET    /admin/no-go-holds/{id}/audio     the held clip, while it waits
    POST   /admin/no-go-holds/{id}           {decision: approve | reject, reason}: the owner is told
                                             (audited no_go_approve, no_go_reject)
    GET    /admin/no-go-checks               the latest comparisons, every clone's
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from app import admin
from app.filenames import safe_filename
from app.safety.no_go import MIN_SECONDS, NoGoError

router = APIRouter(tags=["voice consent"])

NO_MODEL = "The speaker model is not available here, so a voice cannot be added to the list."
TOO_SHORT = f"That is too little of the voice. At least {MIN_SECONDS:.0f} seconds of it is needed."
NO_AUDIO = "That has no audio I can read. A WAV, MP3, M4A or a video with sound works."


def _api():
    from app.api import main
    return main


def admin_only(request: Request) -> str:
    """The signed-in admin, or 404 (writes also need the CSRF header)."""
    from app.admin_api import _admin
    return _admin(request)


def _reason(text: str | None) -> str:
    said = admin.clean_reason(text)
    if len(said) < 3:
        raise HTTPException(status_code=422, detail="Say why, in a few words. It goes in the audit trail.")
    return said


def _raise(exc: NoGoError):
    raise HTTPException(status_code=exc.status, detail=exc.message) from None


@router.get("/admin/no-go-voices")
def list_no_go(who: str = Depends(admin_only)) -> dict:
    from app.continuity import similarity
    no_go = _api().no_go
    return {"voices": no_go.entries(), "block_at": no_go.block_at, "review_from": no_go.review_from,
            "model": no_go.model, "model_available": similarity.available()}


def _export_file(mark: str | None, report_id: int | None) -> tuple[Path, str]:
    """The reported export's file: by its mark, or the mark an abuse report names."""
    api = _api()
    with api.database.tx() as c:
        if not mark and report_id is not None:
            report = c.execute("SELECT location, details FROM abuse_reports WHERE id = ?", (report_id,)).fetchone()
            if report is None:
                raise HTTPException(status_code=404, detail="No abuse report with that number.")
            for token in re.findall(r"[0-9a-f]{16}", f"{report['location']} {report['details']}".lower()):
                if c.execute("SELECT 1 FROM provenance_marks WHERE mark = ?", (token,)).fetchone():
                    mark = token
                    break
            if not mark:
                raise HTTPException(status_code=422, detail="That report names no export of ours. Upload a clip of the voice instead.")
        row = c.execute("SELECT file FROM provenance_marks WHERE mark = ?", (mark,)).fetchone() if mark else None
    if row is None:
        raise HTTPException(status_code=404, detail="No export carries that mark.")
    path = Path(row["file"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="That export's file is no longer kept. Upload a clip of the voice instead.")
    ref = f"export {mark}" + (f", report #{report_id}" if report_id is not None else "")
    return path, ref


def _vector_of(source: Path, start: float | None, end: float | None, tmp: Path) -> tuple[list[float], float]:
    """The clip (or its span) as 16 kHz mono, then the speaker vector. The audio stays in `tmp`, deleted after."""
    from app.media import ffmpeg
    try:
        if start is not None or end is not None:
            lo = max(0.0, float(start or 0.0))
            hi = float(end) if end is not None else ffmpeg.duration_of(source)
            if hi <= lo:
                raise HTTPException(status_code=422, detail="The end comes before the start.")
            wav, seconds = ffmpeg.extract_segment(source, tmp / "voice.wav", lo, hi)
        else:
            wav, seconds = ffmpeg.extract_audio(source, tmp / "voice.wav")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 - a file ffmpeg cannot read is the admin's to replace
        raise HTTPException(status_code=422, detail=NO_AUDIO) from None
    if seconds < MIN_SECONDS:
        raise HTTPException(status_code=422, detail=TOO_SHORT)
    vector = _api().no_go.embed(Path(wav))
    if vector is None:
        raise HTTPException(status_code=503, detail=NO_MODEL)
    return vector, float(seconds)


@router.post("/admin/no-go-voices", status_code=201)
async def add_no_go(name: str = Form(..., max_length=120), reason: str = Form("", max_length=500),
                    file: UploadFile | None = File(None), mark: str | None = Form(None),
                    abuse_report_id: int | None = Form(None), start: float | None = Form(None),
                    end: float | None = Form(None), who: str = Depends(admin_only)) -> dict:
    api = _api()
    label = " ".join(name.split())
    if not label:
        raise HTTPException(status_code=422, detail="Name the voice, so the list says whose it is.")
    said = _reason(reason)
    if file is None and not mark and abuse_report_id is None:
        raise HTTPException(status_code=422, detail="Upload a clip of the voice, or give the reported export.")
    with tempfile.TemporaryDirectory() as tmp:
        if file is not None:
            filename = safe_filename(file.filename, "voice.wav")
            staged = Path(tmp) / filename
            await api._spool(file, staged, "audio")
            source, source_kind, ref = staged, "upload", filename
        else:
            path, ref = await run_in_threadpool(_export_file, (mark or "").strip().lower() or None, abuse_report_id)
            source, source_kind = path, "export"
        vector, seconds = await run_in_threadpool(_vector_of, source, start, end, Path(tmp))
    entry = api.no_go.add(name=label, reason=said, embedding=vector, added_by=who, source=source_kind, source_ref=ref,
                          seconds=round(seconds, 1))
    admin.audit(api.database, who, "no_go_add", entry["id"], said,
                {"name": label, "source": source_kind, "source_ref": ref, "seconds": entry["seconds"], "model": entry["model"],
                 "abuse_report_id": abuse_report_id})
    return entry


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


@router.delete("/admin/no-go-voices/{entry_id}")
def remove_no_go(entry_id: str, req: ReasonRequest | None = None, who: str = Depends(admin_only)) -> dict:
    api = _api()
    said = _reason(req.reason if req else "")
    try:
        entry, closed = api.no_go.remove(entry_id, reason=said, who=who)
    except NoGoError as exc:
        _raise(exc)
    admin.audit(api.database, who, "no_go_remove", entry_id, said, {"name": entry["name"], "holds_closed": closed})
    return {"removed": entry_id, "name": entry["name"], "holds_closed": closed}


@router.get("/admin/no-go-holds")
def list_holds(status: str = "waiting", limit: int = 50, who: str = Depends(admin_only)) -> dict:
    items, waiting = _api().no_go.holds("waiting" if status == "waiting" else "decided", max(1, min(int(limit), 200)))
    return {"items": items, "waiting": waiting}


@router.get("/admin/no-go-holds/{hold_id}/audio")
def hold_audio(hold_id: str, who: str = Depends(admin_only)) -> FileResponse:
    try:
        path = _api().no_go.hold_audio(hold_id)
    except NoGoError as exc:
        _raise(exc)
    if path is None:
        raise HTTPException(status_code=404, detail="That clip is not kept (it is deleted once decided).")
    from app.admin_api import _audio
    return _audio(path, f"held-{hold_id}")


class HoldDecision(BaseModel):
    decision: str
    reason: str = Field(default="", max_length=500)


APPROVED = "The check is done: you can clone {who}'s voice now. Voice the line again to use it."
REJECTED = ("{who}'s voice can't be cloned: it is on the list of voices Voltage does not clone. "
            "Pick a voice from the catalogue, or design one from words.")


@router.post("/admin/no-go-holds/{hold_id}")
def decide_hold(hold_id: str, req: HoldDecision, who: str = Depends(admin_only)) -> dict:
    api = _api()
    if req.decision not in ("approve", "reject"):
        raise HTTPException(status_code=422, detail="Approve or reject.")
    said = _reason(req.reason)
    approve = req.decision == "approve"
    try:
        row = api.no_go.decide(hold_id, approve=approve, reason=said, who=who, allow_own=api.settings.auth_mode == "off")
    except NoGoError as exc:
        _raise(exc)
    speaker = row["speaker_name"] or "the speaker"
    with api.database.tx() as c:
        admin.audit_in(c, who, "no_go_approve" if approve else "no_go_reject", row["owner"], said,
                       {"hold_id": hold_id, "video_id": row["video_id"], "speaker_label": row["speaker_label"],
                        "no_go_id": row["no_go_id"], "no_go_name": row["no_go_name"], "score": row["score"]})
        api.inbox.add_in(c, row["owner"], "consent_decided",
                         (APPROVED if approve else REJECTED).format(who=speaker)[:300],
                         link=f"#v/{row['video_id']}" if row["video_id"] else "#voices", video_id=row["video_id"])
    return row


@router.get("/admin/no-go-checks")
def list_checks(limit: int = 50, who: str = Depends(admin_only)) -> dict:
    return {"checks": _api().no_go.checks(max(1, min(int(limit), 200)))}
