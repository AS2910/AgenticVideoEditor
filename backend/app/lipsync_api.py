"""Run 5, item 10: lip-sync foundations (routes and the upload hook).

On upload each spoken line is looked at once, in the background
(`lipsync/on_camera.py`), and the answer is kept in the video's settings
under `on_camera`; the project's statements carry it from there.

    GET  /videos/{id}/on-camera                     the per-line record (status, timing, verdicts)
    POST /videos/{id}/on-camera                     look again (an old video, or after a failure)
    GET  /admin/lipsync                             which providers exist and which is on
    GET  /admin/lipsync/videos/{id}                 a video's lines, their verdicts and its review trials
    POST /admin/lipsync/videos/{id}/trials          {line, provider}: run one line's span through a provider
                                                    and score both sides (the side-by-side review)
    GET  /admin/lipsync/videos/{id}/files/{sha}     a trial's clip, for the review page's players

Admins only for /admin/* (everyone else gets 404).
"""
from __future__ import annotations

import logging
import os
import secrets
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.domain.transcript import statements_of
from app.lipsync import on_camera, provider as lipsync_provider, quality

log = logging.getLogger(__name__)
router = APIRouter(tags=["lipsync"])

# Tests look inline; the server looks on the work pool so the upload answers at once.
IN_BACKGROUND = True
MAX_TRIALS = 12      # per video, newest kept


def _api():
    from app.api import main
    return main


def _spans(record) -> list[on_camera.LineSpan]:
    return [on_camera.LineSpan(st.start, st.end) for st in statements_of(record.transcript)]


def look(project_id: str) -> dict | None:
    """Detect and store the per-line record now. None when the video is gone."""
    api = _api()
    record = api.repo.get(project_id)
    if record is None:
        return None
    spans = _spans(record)
    found = on_camera.run(record.source.media.path, spans) if spans else \
        {"version": on_camera.VERSION, "status": "done", "seconds": 0.0, "lines": []}
    try:
        api.repo.set_settings(project_id, on_camera=found)
    except KeyError:   # deleted while we looked
        return None
    log.info("on-camera for %s: %d lines in %.2f s", project_id, len(found["lines"]), found["seconds"])
    return found


def enabled() -> bool:
    """AVE_ON_CAMERA=0 switches the look off (the test suite, unless a test opts in)."""
    return os.environ.get("AVE_ON_CAMERA", "1") != "0"


def start(project_id: str) -> None:
    """The upload's hook: mark the record running and look in the background."""
    if not enabled():
        return
    api = _api()
    api.repo.set_settings(project_id, on_camera={"version": on_camera.VERSION, "status": "running", "lines": []})

    def run() -> None:
        try:
            look(project_id)
        except Exception:  # noqa: BLE001 - never fails the upload; the lines stay unknown
            log.exception("on-camera detection crashed for %s", project_id)
    if IN_BACKGROUND:
        api.work_pool.submit(run)
    else:
        run()


def _owner(request: Request) -> str:
    return _api().current_owner(request)


@router.get("/videos/{project_id}/on-camera")
def get_on_camera(project_id: str, owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(project_id, owner)
    return api.repo.settings(project_id).get("on_camera") or {"version": on_camera.VERSION, "status": "none", "lines": []}


@router.post("/videos/{project_id}/on-camera")
def look_again(project_id: str, owner: str = Depends(_owner)) -> dict:
    api = _api()
    api._owned(project_id, owner)
    start(project_id)
    return api.repo.settings(project_id).get("on_camera")


# ── the review page (admin) ──────────────────────────────────────────────────

def _admin(request: Request) -> str:
    api = _api()
    who = api._admin_or_404(request)
    if request.method not in ("GET", "HEAD") and api.settings.auth_mode != "off" \
            and request.headers.get(api.auth.CSRF_HEADER) != api.auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    return who


def _video(project_id: str):
    record = _api().repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="No video with that id.")
    return record


@router.get("/admin/lipsync")
def admin_status(request: Request) -> dict:
    _admin(request)
    return {**lipsync_provider.status(), "handle_seconds": lipsync_provider.HANDLE,
            "measure": "syncnet" if quality._syncnet_on() else "motion"}


@router.get("/admin/lipsync/videos/{project_id}")
def admin_video(project_id: str, request: Request) -> dict:
    _admin(request)
    record = _video(project_id)
    saved = _api().repo.settings(project_id)
    seen = saved.get("on_camera") or {}
    by_span = {(round(v["start"], 3), round(v["end"], 3)): v for v in seen.get("lines") or []}
    lines = []
    for i, st in enumerate(statements_of(record.transcript)):
        v = by_span.get((round(st.start, 3), round(st.end, 3)))
        lines.append({"index": i + 1, "start": st.start, "end": st.end, "text": st.text,
                      "on_camera": on_camera.state_for(seen, st.start, st.end), "detail": v})
    return {"video_id": project_id, "filename": record.source.filename, "duration": record.source.duration,
            "status": seen.get("status") or "none", "seconds": seen.get("seconds"),
            "lines": lines, "trials": list(reversed(saved.get("lipsync_trials") or []))}


class TrialRequest(BaseModel):
    line: int
    provider: str = "fake"


def _take_for(project_id: str, start: float, end: float) -> tuple[Path | None, str]:
    """The newest take voiced over this line, or None (then the line's own sound is used)."""
    api = _api()
    for c in reversed(api.repo.candidates(project_id)):
        sel = c.plan.selection
        if min(end, sel.end) - max(start, sel.start) > 0.5 * (end - start):
            path = api.artifacts.find(project_id, c.audio.sha256)
            if path is not None:
                return path, f"the take “{c.plan.new_text[:60]}”"
    return None, "the line's own sound (no take yet)"


@router.post("/admin/lipsync/videos/{project_id}/trials")
def admin_trial(project_id: str, req: TrialRequest, who: str = Depends(_admin)) -> dict:
    """One line through one provider, scored on both sides. Real providers run
    only when switched on (AVE_LIPSYNC_PROVIDER and their key); the fake always can.
    The admin check is a dependency so a stranger gets 404 before the body is read."""
    api = _api()
    record = _video(project_id)
    spans = _spans(record)
    if not 1 <= req.line <= len(spans):
        raise HTTPException(status_code=422, detail=f"Pick a line from 1 to {len(spans)}.")
    every = lipsync_provider.providers()
    chosen = every.get(req.provider)
    if chosen is None or not chosen.available():
        raise HTTPException(status_code=422, detail=f"Lip-sync by {req.provider} is off. Only the fake runs without a key.")
    span = spans[req.line - 1]
    source = Path(record.source.media.path)
    take, heard = _take_for(project_id, span.start, span.end)
    began = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ave-lipsync-") as tmp:
        work = Path(tmp)
        if take is None:
            take = work / "own.wav"
            api.ffmpeg.extract_segment(source, take, span.start, span.end)
        try:
            w, result, _ = lipsync_provider.replace_span(chosen, source, take, span.start, span.end,
                                                         record.source.duration, work)
        except lipsync_provider.LipSyncUnavailable as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except Exception as exc:  # noqa: BLE001 - the vendor's text is logged, never shown
            log.warning("lip-sync trial failed for %s line %s: %s", project_id, req.line, exc)
            raise HTTPException(status_code=502, detail="Something went wrong on our end. Nothing was charged. Try again in a minute.") from None
        before = quality.confidence(work / "window.mp4")
        after = quality.confidence(result.clip)
        put = api.artifacts.put_file
        original = put(project_id, work / "window.mp4", kind="video", container="mp4", duration=w.seconds)
        synced = put(project_id, result.clip, kind="video", container="mp4", duration=w.seconds)
    if result.usd > 0:
        api.ledger.record(project_id, result.provider, "lipsync", w.seconds, "seconds", result.usd)
    trial = {
        "id": secrets.token_hex(6), "at": api._now(), "by": who, "line": req.line, "provider": result.provider,
        "heard": heard, "window": {"start": w.start, "end": w.end, "send_start": w.send_start, "send_end": w.send_end},
        "original": {"sha256": original.sha256, "confidence": before.to_dict()},
        "result": {"sha256": synced.sha256, "confidence": after.to_dict()},
        "compare": quality.compare(before, after), "usd": result.usd, "notes": list(result.notes),
        "seconds": round(time.monotonic() - began, 2),
    }
    trials = (api.repo.settings(project_id).get("lipsync_trials") or [])[-(MAX_TRIALS - 1):] + [trial]
    api.repo.set_settings(project_id, lipsync_trials=trials)
    return trial


@router.get("/admin/lipsync/videos/{project_id}/files/{sha256}")
def admin_file(project_id: str, sha256: str, request: Request) -> FileResponse:
    _admin(request)
    path = _api().artifacts.find(project_id, sha256)
    if path is None:
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(path, media_type="video/mp4")
