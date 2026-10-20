import asyncio
import json
import queue
import time
import threading
from concurrent.futures import ThreadPoolExecutor
import hashlib
import logging
import tempfile
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import shutil

from fastapi import Depends, FastAPI, HTTPException, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from typing import Literal, Sequence

from app.domain.models import (
    Source, Selection, ContinuityReport, EditCandidate, ApprovedEdit, MediaArtifact,
    Consent, EditPlan, ROLES, OFFSET_RANGE, role_of,
)
from app.render import mix as mixmod
from app.domain.plan import Plan, PlanItem
from app.domain.transcript import (
    assign_speakers, room_after, snap_to_word_boundaries, speaker_of, statements_of,
)
from app.media.fit import speaking_rate, syllable_budget, syllables
from app.config import load_settings
from app.timefmt import iso, now_iso
from app.agent.prose import plain
from app.agent import suggestions as chips
from app import understanding as understanding_mod
from app.media import understand as understand_mod
from app import arrange
from app.media import frames as frames_mod, motion, shots
from app.media import stems as stems_module
from app.media import ffmpeg, ingest
from app.adapters.base import VendorError
from app.adapters.mock import MockLipSyncAdapter
from app.adapters.openai_whisper import TranscriptionError
from app.adapters.selection import (
    select_continuity, select_planner, select_transcriber, select_voice,
)
from app.errors import NonRetryableError
from app import chaos as chaos_module
from app.budget import VoiceBudget, BudgetExceeded
from app.orchestrator.planner import Line, Frame, Sight
from app.media.ffmpeg import SpanMismatch
from app.media.reference import extract_reference_audio, speech_seconds
from app.orchestrator.clones import CloneService, VoiceChoice
from app.orchestrator.pipeline import run_edit
from app.store.db import Database
from app.flags import FlagStore
from app.usage import (
    Ledger, SpendCeilingReached, WHISPER_USD_PER_MINUTE, claude_usd, current_turn, money, month_name, month_start,
)
from app import auth
from app.store import briefs
from app.store.repository import Project, ProjectRecord, ProjectRepository, LOCAL_OWNER
from app.store.artifacts import ArtifactStore
from app.render.renderer import render
from app.render.compose import compose
from app.render import retime
from app.jobs.store import JobStore, Job
from app.jobs.runner import JobRunner
from app.jobs.activity import ActivityJobs, KINDS as JOB_KINDS
from app.jobs.events import EventBus
from app.agent import loop as agent_loop
from app.agent.guards import TurnBudget, is_go
from app.agent.tools import Turn as AgentTurn, Workbench

# The coordinator's modules (Help, the tutorial, onboarding). Each is optional
# at import so the app boots while one is still being written.
try:
    from app.help import search as search_help_articles
except ImportError:  # pragma: no cover - until app.help lands
    def search_help_articles(query: str, limit: int = 3) -> list[dict]:
        return []
try:
    from app.tutorial import is_tutorial, replay_turn
except ImportError:  # pragma: no cover - until app.tutorial lands
    is_tutorial = replay_turn = None  # type: ignore[assignment]

app = FastAPI(title="Agentic Video Editor")
log = logging.getLogger(__name__)

# Media lands under `backend/var/artifacts` unless AVE_DATA_DIR overrides it
# (tests point that at a temp dir; deployment points it at real storage).
settings = load_settings()

# Wiring (module-level singletons for this in-memory slice).
database = Database(settings.data_dir / "ave.db")
repo = ProjectRepository(database)
# Step 0 (FLAGS): every phase of the projects plan ships behind a flag, on per owner.
flags = FlagStore(database, settings.flag_owners)
# Every paid call is recorded here; it backs the voice budget and the
# per-project spend ceiling (Phase 9b).
ledger = Ledger(database, ceiling_usd=settings.project_budget_usd)
artifacts = ArtifactStore(settings.data_dir / "artifacts")
# Real vendors when a key is configured, the deterministic mocks otherwise, and
# the mocks always under AVE_DRY_RUN — so the app runs offline and free.
budget = VoiceBudget(
    ceiling=settings.voice_budget_chars, ledger=ledger, usd_per_1k=settings.elevenlabs_usd_per_1k,
)
# The chaos pass: faults injected at the vendor seams for a game day (AVE_CHAOS); None in normal use.
chaos = chaos_module.from_settings(settings.chaos, settings.auth_mode, settings.chaos_force)
transcriber, transcriber_label = select_transcriber(settings, chaos)
voice, voice_label = select_voice(settings, artifacts, budget, chaos)
lipsync = MockLipSyncAdapter(artifacts)
continuity, continuity_label = select_continuity(voice.identity, artifacts)
# Phase 15a: each speaker's own voice, made once and reused (never under dry-run).
clones = CloneService(repo, artifacts, voice, enabled=settings.clone and not settings.dry_run,
                      min_seconds=settings.clone_min_seconds)
planner, planner_label = select_planner(settings, chaos)
jobs = JobStore()
runner = JobRunner(jobs)
# 2026-10-20 (one processing model): every piece of work the user waits on is
# an Activity job, persisted; the editor hears each change on its live channel.
events = EventBus()
activity = ActivityJobs(database, on_change=lambda j: events.publish(j.video_id, "job.updated", j.to_dict()))
activity.interrupt_leftovers()
# Renders and retries started from the editor run here, off the request thread
# and apart from the turns' pool, so a long turn never holds a preview back.
work_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ave-work")
# Phase 9c: who signs people in. None while AVE_AUTH=off.
oidc: auth.Provider | None = (
    auth.GoogleProvider(settings.google_client_id or "", settings.google_client_secret or "")
    if settings.auth_mode == "google" else None
)


@app.get("/health")
def health() -> dict:
    """Which capabilities are real in this process — handy when a key is missing."""
    return {
        "transcription": transcriber_label,
        "voice": voice_label,
        # Phase 15a: whether a speaker's own voice will be cloned (the key's
        # permissions are checked by `python -m app.tools.check_elevenlabs`).
        "cloning": "on" if clones.available else "off",
        # Phase 15c: music and room kept under an edited line (needs the `room` extra).
        "room": "on" if settings.stems and stems_module.available() else "off",
        "lipsync": "mock",
        "continuity": continuity_label,
        "planner": planner_label,
        # Phase 20: Voltage as an agent with tools (AVE_AGENT=1 and an Anthropic key).
        "agent": _agent_on(),
        "auth": settings.auth_mode,
        # The chaos pass: is the worker pool alive and busy, and are faults being injected.
        "jobs": runner.snapshot(),
        "chaos": chaos.describe() if chaos else None,
    }


_MEDIA_TYPES = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
                "wav": "audio/wav", "m4a": "audio/mp4", "mp3": "audio/mpeg"}


class ApproveRequest(BaseModel):
    candidate_id: str
    # Approve even though continuity failed. Explicit, per approval, and
    # recorded on the edit — never a default.
    override: bool = False


def _continuity_dict(report: ContinuityReport) -> dict:
    return {
        "voice_match": report.voice_match,
        "naturalness": report.naturalness,
        "prosody": report.prosody,
        "audio_integration": report.audio_integration,
        "lip_sync": report.lip_sync,
        "passed": report.passed,
        "warnings": list(report.warnings),
        "measured": list(report.measured),
    }


def _consent_dict(consent: Consent | None) -> dict | None:
    return {"granted_at": consent.granted_at} if consent else None


def _artifact_dict(artifact: MediaArtifact) -> dict:
    # Deliberately excludes the filesystem path — the client gets a content
    # address. Phase 1 adds an endpoint that serves bytes by that address.
    return {
        "kind": artifact.kind,
        "sha256": artifact.sha256,
        "duration": artifact.duration,
        "container": artifact.container,
    }


def _candidate_dict(candidate: EditCandidate) -> dict:
    return {
        "type": "candidate",
        "candidate_id": candidate.candidate_id,
        "plan": {
            "selection": {
                "start": candidate.plan.selection.start,
                "end": candidate.plan.selection.end,
            },
            "new_text": candidate.plan.new_text,
            "voice_profile_id": candidate.plan.voice_profile_id,
            "fit": candidate.plan.fit,
            "mix": candidate.plan.mix,
            "delivery": candidate.plan.delivery,
            "flex": candidate.plan.flex,
            "voice_settings": candidate.plan.voice_settings,
            "model": candidate.plan.model,
            "flex_max": candidate.plan.flex_max,
            "role": role_of(candidate.plan), "offset_db": candidate.plan.offset_db,
        },
        "audio": _artifact_dict(candidate.audio),
        "frames": _artifact_dict(candidate.frames),
        "continuity": _continuity_dict(candidate.continuity),
        "fit_notes": list(candidate.fit_notes),
        # P-3: the take's own words at their times, relative to the take.
        "words": [{"text": w.text, "start": w.start, "end": w.end} for w in candidate.words],
    }


async def _spool(upload: UploadFile, dest: Path) -> None:
    """Stream an upload to disk, refusing anything absurdly large."""
    written = 0
    with dest.open("wb") as out:
        while chunk := await upload.read(1 << 20):
            written += len(chunk)
            if written > ingest.MAX_SOURCE_BYTES:
                raise HTTPException(status_code=413, detail="That file is too large.")
            out.write(chunk)


def _now() -> str:
    # Bug 2: one format for every moment — ISO 8601 UTC with ms and Z (app/timefmt.py).
    return now_iso()


def _clock(seconds: float) -> str:
    """A time in the clip as m:ss, for the log and a take's notes."""
    whole = int(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


CONSENT_REQUIRED = (
    "Confirm you have the right to edit and clone this speaker before generating."
)


def current_owner(request: Request) -> str:
    """Who is calling — the auth seam (Phase 9c).

    With AVE_AUTH=off everyone is the local owner. With sign-in on, the
    session cookie names the owner, every route is scoped by it, and a
    state-changing request must carry the header a cross-site form cannot.
    """
    if settings.auth_mode == "off":
        return LOCAL_OWNER
    who = auth.identity_from(auth.verify(
        request.cookies.get(auth.SESSION_COOKIE), settings.session_secret or "", max_age=auth.SESSION_SECONDS,
    ))
    if who is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(auth.CSRF_HEADER) != auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    return who.owner


def _ensure_spend(project_id: str) -> None:
    """The video's ceiling, its project's when one is set (Folders), and the
    owner's for the month; the refusal names the scope that was reached."""
    record = repo.get(project_id)
    folder = None
    if record is not None and record.folder_id:
        project = repo.get_project(record.folder_id)
        if project is not None and project.ceiling_usd is not None:
            folder = (project.project_id, float(project.ceiling_usd), project.name)
    ledger.ensure_can_spend(
        project_id,
        owner=record.owner if record else None,
        owner_ceiling_usd=settings.user_budget_usd,
        folder=folder,
        filename=record.source.filename if record else "",
    )


# ── Spend scopes: turn → video → project → month ─────────────────────────────

SCOPE_ORDER = ("turn", "video", "project", "month")


def _scope(spent: float, ceiling: float | None, label: str) -> dict:
    return {"spent_usd": round(spent, 4), "ceiling_usd": None if ceiling is None else round(float(ceiling), 4),
            "label": label}


def _binding(scopes: dict) -> str | None:
    """The scope that stops paid work first: the least headroom (ceiling less
    spent) among the scopes with a ceiling; a tie goes to the narrower scope.
    The turn's cap is left out: it starts again with every turn, so it never
    stops the next one."""
    best = None
    for key in SCOPE_ORDER[1:]:
        scope = scopes.get(key)
        if not scope or scope["ceiling_usd"] is None:
            continue
        room = scope["ceiling_usd"] - scope["spent_usd"]
        if best is None or room < best[0] - 1e-9:
            best = (room, key)
    return best[1] if best else None


def _month_scope(owner: str) -> dict:
    return _scope(ledger.spent_usd_by_owner(owner, iso(month_start())), settings.user_budget_usd, month_name())


def _project_scope(project: Project) -> dict:
    return _scope(ledger.spent_usd_by_folder(project.project_id), project.ceiling_usd, f"Project {project.name}")


def _spend_summary(owner: str, video_id: str | None = None, project_id: str | None = None) -> dict:
    """Every scope for the context, each {spent_usd, ceiling_usd, label}, and
    the binding one. A video: its last turn (when it has had one), itself,
    its project (when it is in one) and the month; a project: itself and the
    month; nothing: the month."""
    out: dict = {}
    project = None
    if video_id is not None:
        record = repo.get(video_id)
        last = repo.settings(video_id).get("last_turn") or {}
        if last.get("id"):
            # A turn carried on after "allow $x more" keeps its id and its raised cap.
            out["turn"] = _scope(ledger.spent_usd_by_turn(video_id, last["id"], last.get("at")),
                                 last.get("cap_usd") or _settings(video_id, owner)["turn_usd"], "This turn")
        out["video"] = _scope(ledger.spent_usd(video_id), ledger.ceiling_usd, "This video")
        project = _folder_of(record) if record else None
    elif project_id is not None:
        project = repo.get_project(project_id)
    if project is not None:
        out["project"] = _project_scope(project)
    out["month"] = _month_scope(owner)
    out["binding"] = _binding(out)
    return out


@app.get("/spend")
def get_spend(video: str | None = None, project: str | None = None, owner: str = Depends(current_owner)) -> dict:
    """One summary of spend for the current context, every scope labelled,
    plus `binding`: the scope with the least headroom."""
    if video is not None:
        _owned(video, owner)
        return _spend_summary(owner, video_id=video)
    if project is not None:
        _owned_project(project, owner)
        return _spend_summary(owner, project_id=project)
    return _spend_summary(owner)


# ── Phase 9c: sign-in ────────────────────────────────────────────────────────

def _secure() -> bool:
    return settings.public_url.startswith("https://")


def _redirect_uri() -> str:
    return f"{settings.public_url}/api/auth/callback"


def _me(request: Request) -> dict:
    if settings.auth_mode == "off":
        return {"mode": "off", "user": None}
    who = auth.identity_from(auth.verify(
        request.cookies.get(auth.SESSION_COOKIE), settings.session_secret or "", max_age=auth.SESSION_SECONDS,
    ))
    return {
        "mode": settings.auth_mode,
        "user": {"sub": who.sub, "email": who.email, "name": who.name, "picture": who.picture} if who else None,
    }


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Whether sign-in is on, and who is signed in."""
    return _me(request)


@app.get("/auth/login")
def auth_login(request: Request) -> Response:
    """Off to Google. The state and the PKCE verifier ride in a short-lived
    signed cookie, so the callback can check them."""
    if oidc is None:
        raise HTTPException(status_code=404, detail="Sign-in is off.")
    state = auth._b64(auth.secrets.token_bytes(16))
    verifier, challenge = auth.pkce_pair()
    response = RedirectResponse(oidc.authorize_url(_redirect_uri(), state, challenge), status_code=302)
    response.set_cookie(
        auth.LOGIN_COOKIE, auth.sign({"state": state, "verifier": verifier}, settings.session_secret or ""),
        max_age=auth.LOGIN_SECONDS, httponly=True, samesite="lax", secure=_secure(), path="/",
    )
    return response


@app.get("/auth/callback")
def auth_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None) -> Response:
    """Back from Google: check the state, exchange the code, set the session."""
    if oidc is None:
        raise HTTPException(status_code=404, detail="Sign-in is off.")
    login = auth.verify(request.cookies.get(auth.LOGIN_COOKIE), settings.session_secret or "", max_age=auth.LOGIN_SECONDS)
    if error:
        raise HTTPException(status_code=400, detail=f"Google refused the sign-in ({error}).")
    if not login or not state or not code or login.get("state") != state:
        raise HTTPException(status_code=400, detail="That sign-in has expired. Start again.")
    try:
        who = oidc.identity(code, _redirect_uri(), login["verifier"])
    except auth.AuthError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not auth.allowed(who, settings.allowed_emails):
        raise HTTPException(status_code=403, detail="This Voltage is private; that account is not on its list.")
    response = RedirectResponse(settings.public_url + "/", status_code=302)
    response.set_cookie(
        auth.SESSION_COOKIE,
        auth.sign({"sub": who.sub, "email": who.email, "name": who.name, "picture": who.picture}, settings.session_secret or ""),
        max_age=auth.SESSION_SECONDS, httponly=True, samesite="lax", secure=_secure(), path="/",
    )
    response.delete_cookie(auth.LOGIN_COOKIE, path="/")
    return response


@app.post("/auth/logout")
def auth_logout(response: Response) -> dict:
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"signed_out": True}


def _owned(project_id: str, owner: str) -> ProjectRecord:
    """The caller's video, or 404. Someone else's video is indistinguishable
    from a missing one, so ids leak nothing."""
    record = repo.get(project_id)
    if record is None or record.owner != owner:
        raise HTTPException(status_code=404, detail="video not found")
    return record


def _owned_project(project_id: str, owner: str) -> Project:
    """The caller's project (a folder, Folders), or 404."""
    project = repo.get_project(project_id)
    if project is None or project.owner != owner:
        raise HTTPException(status_code=404, detail="project not found")
    return project


def _folder_of(record: ProjectRecord) -> Project | None:
    return repo.get_project(record.folder_id) if record.folder_id else None


# ── UX-5: the picture, for a clip with no speech ─────────────────────────────

def _frames(record: ProjectRecord) -> list[frames_mod.Frame]:
    """The clip's frames, extracted once beside its media."""
    source = record.source
    return frames_mod.extract_frames(source.media.path, source.duration, artifacts.root / source.project_id / "frames")


def _frames_dict(record: ProjectRecord) -> list[dict]:
    try:
        return [{"index": i, "at": f.at} for i, f in enumerate(_frames(record))]
    except Exception:  # noqa: BLE001 - a missing ffmpeg must not break reading a project
        return []


def _sight(project_id: str, record: ProjectRecord) -> Sight:
    """What Voltage saw in the clip: looked at once, kept with the project."""
    saved = repo.settings(project_id).get("sight")
    if saved:
        known = {k: v for k, v in saved.items() if k in Sight.__dataclass_fields__}
        return Sight(**{**known, "beats": tuple(saved.get("beats", ())), "details": tuple(saved.get("details", ()))})
    if planner is None:
        raise HTTPException(status_code=503, detail=NEEDS_CLAUDE)
    frames = [Frame(at=f.at, path=str(f.path)) for f in _frames(record)]
    sight = planner.look(frames, record.source.duration, meter=_meter(project_id, "looking"), brief=_brief_text(project_id))
    repo.set_settings(project_id, sight=asdict(sight))
    return sight


class SightRequest(BaseModel):
    # The place, as the user confirms or corrects it; empty clears a confirmation.
    place: str = ""


@app.put("/videos/{project_id}/sight")
@app.put("/projects/{project_id}/sight", deprecated=True)
def confirm_sight(project_id: str, req: SightRequest, owner: str = Depends(current_owner)) -> dict:
    """UX-5: the user confirms the place Voltage guessed, or names the real
    one. The plan then uses that name and never guesses."""
    record = _owned(project_id, owner)
    sight = _sight(project_id, record)
    sight = replace(sight, place_confirmed=req.place.strip())
    repo.set_settings(project_id, sight=asdict(sight))
    reading = repo.settings(project_id).get("reading")
    if reading and "sight" in reading:
        reading = {**reading, "sight": asdict(sight)}
        repo.set_settings(project_id, reading=reading)
    return asdict(sight)


@app.get("/videos/{project_id}/frames")
@app.get("/projects/{project_id}/frames", deprecated=True)
def list_frames(project_id: str, owner: str = Depends(current_owner)) -> list[dict]:
    """The clip's frames, by index and time; each is served at /frames/{index}."""
    record = _owned(project_id, owner)
    return _frames_dict(record)


@app.get("/videos/{project_id}/frames/{index}")
@app.get("/projects/{project_id}/frames/{index}", deprecated=True)
def get_frame(project_id: str, index: int, owner: str = Depends(current_owner)) -> FileResponse:
    record = _owned(project_id, owner)
    frames = _frames(record)
    if not 0 <= index < len(frames):
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(frames[index].path, media_type="image/jpeg")


def _project_dict(record: ProjectRecord) -> dict:
    """A video record. `video_id` is its own id; `project_id` the folder it
    is in, or null (Folders)."""
    source = record.source
    folder = _folder_of(record)
    return {
        "video_id": source.project_id,
        "project_id": folder.project_id if folder else None,
        "project_name": folder.name if folder else None,
        "filename": source.filename,
        "duration": source.duration,
        "media": _artifact_dict(source.media),
        # Bug 2: when the uploader confirmed they may edit and clone this speaker, or null.
        "consent_granted_at": record.consent.granted_at if record.consent else None,
        "created_at": record.created_at,
        "transcript": [
            {"text": w.text, "start": w.start, "end": w.end} for w in record.transcript.words
        ],
        "statements": [
            {"text": st.text, "start": st.start, "end": st.end, "speaker": st.speaker}
            for st in statements_of(record.transcript)
        ],
        "speakers": _speakers(source.project_id),
        "settings": _settings(source.project_id),
        "plan": _plan_dict(repo.latest_plan(source.project_id)),
        # UX-2: Voltage's first look at the clip, once it has had one.
        "reading": repo.settings(source.project_id).get("reading"),
        # 2026-10-20: the chips above Voltage's box, from this video.
        "suggestions": _chips_now(source.project_id, record)["suggestions"],
        # UX-5: a clip with no speech shows its frames where the transcript would be.
        "frames": _frames_dict(record) if not record.transcript.words and not record.transcript.statements else [],
    }


NEEDS_CLAUDE = "Voltage needs Claude for this (set ANTHROPIC_API_KEY)."
EFFORTS = ("medium", "high", "xhigh")
DEFAULT_AUTONOMY = "ask"


# The steps that can still wait for a yes under Just do it (Volt's Settings).
ASK_BEFORE = ("ship", "clone", "design")


def _ask_before(saved: dict | None) -> dict:
    saved = saved or {}
    return {k: bool(saved.get(k, False)) for k in ASK_BEFORE}


def _clamp_turn_usd(usd: float) -> float:
    """A turn's cap, between a cent and the project's ceiling."""
    return round(min(ledger.ceiling_usd, max(0.01, usd)), 2)


def _prefs(owner: str) -> dict:
    """The owner's defaults (Volt): what a new project starts with, and which
    steps still ask under Just do it. Kept in meta, apart from any project."""
    saved = json.loads(repo.get_meta(f"prefs:{owner}") or "{}")
    return {
        "autonomy": saved.get("autonomy", DEFAULT_AUTONOMY),
        "turn_usd": float(saved.get("turn_usd") or settings.agent_turn_usd),
        "effort": saved.get("effort") or settings.agent_effort,
        "ask_before": _ask_before(saved.get("ask_before")),
    }


SETTING_KEYS = ("autonomy", "turn_usd", "effort", "ask_before")


def _defaults_for(owner: str, folder: Project | None) -> dict:
    """The defaults a video reads when it has not set a key itself: the
    project's (Folders) over the owner's."""
    prefs = _prefs(owner)
    saved = (folder.settings or {}) if folder else {}
    if saved.get("autonomy") in ("ask", "draft"):
        prefs["autonomy"] = saved["autonomy"]
    if saved.get("turn_usd"):
        prefs["turn_usd"] = _clamp_turn_usd(float(saved["turn_usd"]))
    if saved.get("effort") in EFFORTS:
        prefs["effort"] = saved["effort"]
    if isinstance(saved.get("ask_before"), dict):
        prefs["ask_before"] = _ask_before({**prefs["ask_before"], **saved["ask_before"]})
    return prefs


def _starting_settings(owner: str, folder: Project | None = None) -> dict:
    """What a new video starts with: the project's defaults over the owner's,
    copied in, so a later change to the defaults leaves the video as it was set."""
    defaults = _defaults_for(owner, folder)
    return {k: defaults[k] for k in SETTING_KEYS}


class PrefsUpdate(BaseModel):
    autonomy: Literal["ask", "draft"] | None = None
    turn_usd: float | None = None
    effort: Literal["medium", "high", "xhigh"] | None = None
    # Any subset of ship / clone / design; the rest stay as they were.
    ask_before: dict[str, bool] | None = None


@app.get("/me/settings")
def get_my_settings(owner: str = Depends(current_owner)) -> dict:
    """The caller's defaults: what a new project starts with, and which steps
    still wait for a yes under Just do it."""
    return _prefs(owner)


@app.get("/me/flags")
def get_my_flags(owner: str = Depends(current_owner)) -> dict:
    """The feature flags that are on for the caller (Step 0, FLAGS)."""
    return {"flags": flags.enabled_for(owner)}


@app.put("/me/settings")
def update_my_settings(req: PrefsUpdate, owner: str = Depends(current_owner)) -> dict:
    """Change any of the defaults; the whole set comes back. Projects already
    made keep the settings they were made with."""
    prefs = _prefs(owner)
    if req.autonomy is not None:
        prefs["autonomy"] = req.autonomy
    if req.turn_usd is not None:
        prefs["turn_usd"] = _clamp_turn_usd(req.turn_usd)
    if req.effort is not None:
        prefs["effort"] = req.effort
    if req.ask_before is not None:
        prefs["ask_before"] = _ask_before({**prefs["ask_before"], **req.ask_before})
    repo.set_meta(f"prefs:{owner}", json.dumps(prefs))
    return prefs


def _settings(project_id: str, owner: str | None = None) -> dict:
    """What Voltage may do on this video (20d): the autonomy, what one
    turn may spend, how hard it thinks, and which steps still ask under Just
    do it; the video's ceiling and the model are read-only. A key the video
    never set reads its project's default, then its owner's (Folders)."""
    saved = repo.settings(project_id)
    record = repo.get(project_id)
    if owner is None:
        owner = record.owner if record else LOCAL_OWNER
    defaults = _defaults_for(owner, _folder_of(record) if record else None)
    out = {
        "autonomy": saved.get("autonomy") or defaults["autonomy"],
        "turn_usd": float(saved.get("turn_usd") or defaults["turn_usd"]),
        "effort": saved.get("effort") or defaults["effort"],
        "ceiling_usd": ledger.ceiling_usd,
        "ask_before": _ask_before(saved["ask_before"]) if saved.get("ask_before") is not None else defaults["ask_before"],
        "model": settings.agent_model,
        # 2026-10-20: how lines are mixed and how loud the render lands.
        "mix": {**MIX_DEFAULTS, **(saved.get("mix") or {})},
    }
    if saved.get("tutorial"):
        out["tutorial"] = True   # the guided run's sample video (its turns replay a recording)
    return out


def _speakers(project_id: str) -> list[dict]:
    return [
        {"label": s.label, "name": s.name, "voice_id": s.voice_id}
        for s in repo.speakers(project_id)
    ]


def _record_diarization(project_id: str, duration: float) -> None:
    if transcriber_label.startswith("openai"):
        minutes = duration / 60
        ledger.record(project_id, "openai", "diarization", minutes, "minutes",
                      minutes * WHISPER_USD_PER_MINUTE)


@app.post("/videos")
async def create_project(
    file: UploadFile = File(...),
    consent: bool = Form(False),
    project_id: str | None = Form(None),
    owner: str = Depends(current_owner),
) -> dict:
    """Upload a video (Folders: into a project when `project_id` names one
    of the caller's; it then starts with the project's defaults)."""
    folder = _owned_project(project_id, owner) if project_id else None
    filename = Path(file.filename or "upload.mp4").name
    container = (Path(filename).suffix.lstrip(".") or "mp4").lower()

    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / filename
        await _spool(file, staged)
        try:
            probed = ingest.probe_source(staged)
        except ingest.IngestError as exc:
            # Reject before allocating a project id, so a refused upload leaves
            # no trace in the store.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        project_id = repo.next_id()
        media = artifacts.put_file(
            project_id, staged, kind="video", container=container, duration=probed.duration,
        )

    source = Source(
        project_id=project_id, filename=filename, duration=probed.duration, media=media,
    )
    try:
        transcript = transcriber.transcribe(source)
    except TranscriptionError as exc:
        # The upload is already stored under `project_id`, so a vendor failure
        # leaves that media orphaned. Acceptable while storage is disposable;
        # the retry/cleanup story lands with the job model.
        log.warning("transcription failed for %s: %s", project_id, exc)
        raise HTTPException(
            status_code=502, detail="Could not transcribe that video. Please try again.",
        ) from exc

    granted = Consent(granted_at=_now()) if consent else None
    repo.create(source, transcript, granted, owner=owner, folder_id=folder.project_id if folder else None)
    repo.set_settings(project_id, **_starting_settings(owner, folder))
    if transcriber_label.startswith("openai"):
        minutes = source.duration / 60
        ledger.record(project_id, "openai", "transcription", minutes, "minutes",
                      minutes * WHISPER_USD_PER_MINUTE)
    if any(w.speaker for w in transcript.words):
        _record_diarization(project_id, source.duration)
    return _project_dict(repo.get(project_id))


# ── 20i: the user's own voices ───────────────────────────────────────────────
# Uploaded under a name, cloned once at the vendor, kept per owner (not per
# project), and offered wherever a voice is picked: the editor's Voice select,
# the speakers bar, and the agent's list ("in my voice" means one of these).

MIN_MY_VOICE_SECONDS = 10.0


def _my_voices(owner: str) -> list[dict]:
    return json.loads(repo.get_meta(f"my_voices:{owner}") or "[]")


def _set_my_voices(owner: str, voices: list[dict]) -> None:
    repo.set_meta(f"my_voices:{owner}", json.dumps(voices))


def _user_store(owner: str) -> str:
    """Where an owner's own media lives (voice samples, designed previews): a
    pseudo project id in the artifact store, since none of it belongs to a clip."""
    return f"user-{owner}"


def _designs(owner: str) -> dict:
    """The owner's recent designed previews outside any project, by generated id."""
    return json.loads(repo.get_meta(f"designs:{owner}") or "{}")


def _set_designs(owner: str, designs: dict) -> None:
    repo.set_meta(f"designs:{owner}", json.dumps(designs))


def _kept_voice_ids() -> set[str]:
    """Every voice anyone kept as their own, or shared into a project
    (Folders). A video's deletion leaves these at the vendor: they outlive
    the clip they were made from."""
    out: set[str] = set()
    for prefix in ("my_voices:", "project_voices:"):
        for value in repo.meta_with_prefix(prefix).values():
            out.update(v["voice_id"] for v in json.loads(value))
    return out


def _voice_entry(v: dict, used_in: int = 0) -> dict:
    """One of the owner's voices as the voices page shows it. Voices kept
    before Volt have no kind: they were all recordings."""
    return {**v, "kind": v.get("kind") or "recorded", "sample_sha": v.get("sample_sha"),
            "description": v.get("description"), "used_in": used_in}


def _voices_in_use(owner: str) -> dict[str, int]:
    """How many of the owner's projects speak in each voice: a live edit, or
    a plan item with a take, in that voice."""
    counts: dict[str, int] = {}
    for r in repo.list(owner):
        pid = r.source.project_id
        used = {e.plan.voice_profile_id for e in repo.list_edits(pid) if not e.reverted}
        plan = repo.latest_plan(pid)
        for item in (plan.items if plan else ()):
            if item.candidate_id and item.status != "dismissed":
                candidate = repo.get_candidate(pid, item.candidate_id)
                if candidate is not None:
                    used.add(candidate.plan.voice_profile_id)
        for vid in used:
            counts[vid] = counts.get(vid, 0) + 1
    return counts


def _slots() -> list[int] | None:
    """[used, limit] voice slots at the vendor, or None when it cannot say."""
    found = getattr(voice, "slots", lambda: None)()
    return [int(found[0]), int(found[1])] if found else None


def _voice_name_or_422(name: str) -> str:
    label = " ".join(name.split())[:40]
    if not label:
        raise HTTPException(status_code=422, detail="Give the voice a name.")
    return label


def _no_voice_called(owner: str, label: str) -> None:
    if any(v["name"].lower() == label.lower() for v in _my_voices(owner)):
        raise HTTPException(status_code=409, detail=f"You already have a voice called {label}.")


def _voices_can_be_made(attr: str = "can_clone") -> None:
    """Making a voice of the user's own needs a vendor that keeps it; under
    dry-run a mock id would outlive the setup that made it."""
    if settings.dry_run or not getattr(voice, attr, False):
        raise HTTPException(status_code=503, detail="Voices cannot be made in this setup (no vendor that clones).")


@app.get("/voices")
def list_voices(owner: str = Depends(current_owner)) -> dict:
    """The voices a new line can be spoken in, which one is the default, the
    caller's own voices (20i) with where each is used, and the vendor's slots."""
    mine = _my_voices(owner)
    shared = [(p, v) for p in repo.list_projects(owner) for v in _project_voices(p.project_id)]
    for v in [*mine, *(v for _, v in shared)]:
        getattr(voice, "register_clone", lambda vid: None)(v["voice_id"])
    used = _voices_in_use(owner) if mine or shared else {}
    return {
        "default": voice.default_voice,
        "voices": [{**v, "preview_url": v.get("preview_url")} for v in voice.voices()],
        "mine": [_voice_entry(v, used.get(v["voice_id"], 0)) for v in mine],
        # Folders: the voices shared in the caller's projects.
        "project": [{**_voice_entry(v, used.get(v["voice_id"], 0)), "project_id": p.project_id, "project_name": p.name} for p, v in shared],
        "slots": _slots(),
    }


@app.post("/voices/mine", status_code=201)
async def add_my_voice(
    name: str = Form(...), consent: bool = Form(False), file: UploadFile = File(...),
    owner: str = Depends(current_owner),
) -> dict:
    """Upload a recording of your own voice and keep it under a name (20i).
    Ten seconds or more of speech; the vendor clones it once (a voice slot,
    no characters). Consent is the uploader's word that the voice is theirs
    or one they may use."""
    if not consent:
        raise HTTPException(status_code=403, detail="Say it is your voice, or one you have the right to use.")
    _voices_can_be_made()
    label = _voice_name_or_422(name)
    _no_voice_called(owner, label)
    filename = Path(file.filename or "voice.wav").name
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / filename
        await _spool(file, staged)
        try:
            wav, seconds = ffmpeg.extract_audio(staged, Path(tmp) / "voice.wav", sample_rate=44100)
        except Exception:  # noqa: BLE001 — a file ffmpeg cannot read is the user's to replace
            raise HTTPException(status_code=422, detail="That file has no audio I can read. A WAV, MP3, M4A or a video with sound works.") from None
        if seconds < MIN_MY_VOICE_SECONDS:
            raise HTTPException(status_code=422, detail=f"That is {seconds:.0f} s; at least {MIN_MY_VOICE_SECONDS:.0f} s of your voice is needed to clone it.")
        try:
            voice_id = voice.create_clone(f"voltage-mine-{label}", wav)
        except Exception as exc:  # noqa: BLE001 — the vendor's refusal, in its own words
            raise HTTPException(status_code=502, detail=str(exc) or "The voice could not be made.") from None
        # The recording stays with the owner, so the voices page can play it back.
        sample = artifacts.put_file(_user_store(owner), wav, kind="audio", container="wav", duration=seconds)
    ticked = _now()   # the request carries the ticked box: this is the moment of consent
    entry = {"voice_id": voice_id, "name": label, "seconds": round(seconds, 1), "at": ticked,
             "kind": "recorded", "sample_sha": sample.sha256, "description": None, "consent_granted_at": ticked}
    _set_my_voices(owner, [*_my_voices(owner), entry])
    return _voice_entry(entry)


@app.get("/voices/sample/{sha256}")
def get_voice_sample(sha256: str, owner: str = Depends(current_owner)) -> FileResponse:
    """The recording behind one of the caller's voices, or one of their
    designed previews, with range requests. Only their own are served."""
    allowed = {v.get("sample_sha") for v in _my_voices(owner)} | {d.get("sha256") for d in _designs(owner).values()}
    path = artifacts.find(_user_store(owner), sha256) if sha256 in allowed else None
    if path is None:
        raise HTTPException(status_code=404, detail="sample not found")
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"))


def _made_voices_of(owner: str) -> list[dict]:
    """Every voice Voltage made inside the owner's projects: designed or added
    from the library (the project's `made_voices`), and each speaker's own
    clone. `kept` says it is already one of the owner's own."""
    kept = {v["voice_id"] for v in _my_voices(owner)}
    out: list[dict] = []
    for r in repo.list(owner):
        pid, filename = r.source.project_id, r.source.filename
        for m in repo.settings(pid).get("made_voices") or []:
            out.append({"voice_id": m["voice_id"], "name": m.get("name") or m["voice_id"], "kind": m.get("kind") or "designed",
                        "video_id": pid, "filename": filename, "description": m.get("description"), "seconds": None,
                        "kept": m["voice_id"] in kept})
        names = {s.label: s.name for s in repo.speakers(pid)}
        for key, voice_id in repo.clones(pid).items():
            whole = key == ProjectRepository.WHOLE_CLIP
            out.append({"voice_id": voice_id, "name": "The speaker" if whole else names.get(key, f"Speaker {key}"), "kind": "cloned",
                        "video_id": pid, "filename": filename, "description": None,
                        "seconds": round(speech_seconds(r.transcript, None if whole else key), 1), "kept": voice_id in kept})
    return out


@app.get("/voices/made")
def list_made_voices(owner: str = Depends(current_owner)) -> dict:
    """The voices Voltage made across the caller's projects, and whether each
    is kept as their own yet. One that is not goes when its project does."""
    return {"voices": _made_voices_of(owner)}


class KeepRequest(BaseModel):
    voice_id: str
    # Defaults to the name it was made under.
    name: str | None = None


@app.post("/voices/mine/keep", status_code=201)
def keep_made_voice(req: KeepRequest, owner: str = Depends(current_owner)) -> dict:
    """Keep a voice Voltage made for a clip as one of your own: it leaves the
    project's list, so deleting the project no longer deletes it."""
    mine = _my_voices(owner)
    if any(v["voice_id"] == req.voice_id for v in mine):
        raise HTTPException(status_code=409, detail="That voice is already yours.")
    found = next((m for m in _made_voices_of(owner) if m["voice_id"] == req.voice_id), None)
    if found is None:
        raise HTTPException(status_code=404, detail="No such voice was made in your projects.")
    label = _voice_name_or_422(req.name or found["name"])
    _no_voice_called(owner, label)
    pid = found["video_id"]
    made = repo.settings(pid).get("made_voices") or []
    if any(m["voice_id"] == req.voice_id for m in made):
        repo.set_settings(pid, made_voices=[m for m in made if m["voice_id"] != req.voice_id])
    entry = {"voice_id": req.voice_id, "name": label, "seconds": float(found.get("seconds") or 0.0), "at": _now(),
             "kind": found["kind"], "sample_sha": None, "description": found.get("description"),
             "source": {"video_id": pid, "filename": found["filename"]}, **_made_voice_consent({**found, "video_id": pid})}
    _set_my_voices(owner, [*mine, entry])
    getattr(voice, "register_clone", lambda vid: None)(req.voice_id)
    return _voice_entry(entry)


@app.get("/voices/speakers")
def list_speakers_with_a_voice(owner: str = Depends(current_owner)) -> dict:
    """Every speaker across the caller's projects with enough speech to clone."""
    out = []
    for r in repo.list(owner):
        pid = r.source.project_id
        for spk in repo.speakers(pid):
            seconds = speech_seconds(r.transcript, spk.label)
            if seconds >= MIN_MY_VOICE_SECONDS:
                out.append({"video_id": pid, "filename": r.source.filename, "label": spk.label, "name": spk.name,
                            "seconds": round(seconds, 1)})
    return {"speakers": out}


class FromSpeakerRequest(BaseModel):
    video_id: str
    label: str
    name: str
    consent: bool = False


@app.post("/voices/mine/from-speaker", status_code=201)
def add_my_voice_from_speaker(req: FromSpeakerRequest, owner: str = Depends(current_owner)) -> dict:
    """One of your own voices from a speaker in one of your clips: their
    speech, joined, cloned once under your name. Consent is your word that
    the voice is yours or one you may use."""
    if not req.consent:
        raise HTTPException(status_code=403, detail="Say it is your voice, or one you have the right to use.")
    _voices_can_be_made()
    label = _voice_name_or_422(req.name)
    _no_voice_called(owner, label)
    record = _owned(req.video_id, owner)
    spk = next((s for s in repo.speakers(req.video_id) if s.label == req.label), None)
    if spk is None:
        raise HTTPException(status_code=404, detail="speaker not found")
    seconds = speech_seconds(record.transcript, spk.label)
    if seconds < MIN_MY_VOICE_SECONDS:
        raise HTTPException(status_code=422, detail=f"{spk.name} speaks for {seconds:.0f} s; at least {MIN_MY_VOICE_SECONDS:.0f} s is needed to clone a voice.")
    reference = extract_reference_audio(record.source, record.transcript, artifacts, speaker=spk.label, min_seconds=MIN_MY_VOICE_SECONDS)
    if reference is None:
        raise HTTPException(status_code=422, detail=f"Could not cut a clean sample of {spk.name}'s voice.")
    try:
        voice_id = voice.create_clone(f"voltage-mine-{label}", Path(reference.path))
    except Exception as exc:  # noqa: BLE001 — the vendor's refusal, in its own words
        raise HTTPException(status_code=502, detail=str(exc) or "The voice could not be made.") from None
    # The sample is kept with the owner, so it outlives the project it came from.
    sample = artifacts.put_file(_user_store(owner), reference.path, kind="audio", container="wav", duration=reference.duration)
    entry = {"voice_id": voice_id, "name": label, "seconds": round(seconds, 1), "at": _now(), "kind": "cloned", "consent_granted_at": _now(),
             "sample_sha": sample.sha256, "description": None,
             "source": {"video_id": req.video_id, "filename": record.source.filename, "label": spk.label}}
    _set_my_voices(owner, [*_my_voices(owner), entry])
    return _voice_entry(entry)


class DesignRequest(BaseModel):
    description: str


# How many designed previews an owner keeps outside projects; older ones are forgotten.
RECENT_DESIGNS = 30


@app.post("/voices/design")
def design_my_voice(req: DesignRequest, owner: str = Depends(current_owner)) -> dict:
    """Three previews of a voice described in words, outside any project. The
    spend is kept under the owner's own id and the ceiling applies."""
    description = " ".join(req.description.split())
    if not description:
        raise HTTPException(status_code=422, detail="Describe the voice in words first.")
    if settings.dry_run or not hasattr(voice, "design_voice"):
        raise HTTPException(status_code=503, detail="Voices cannot be designed in this setup (no vendor that designs).")
    key = _user_store(owner)
    try:
        ledger.ensure_can_spend(key, owner=owner, owner_ceiling_usd=settings.user_budget_usd, filename="Your voices")
        previews = list(voice.design_voice(key, description))
    except (SpendCeilingReached, BudgetExceeded) as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    designs = _designs(owner)
    out = []
    for pv in previews:
        container = "wav" if "wav" in (pv.get("media_type") or "") else "mp3"
        duration = float(pv.get("duration") or 0.0)
        art = artifacts.put_bytes(key, pv["audio"], kind="audio", container=container, duration=duration)
        designs[pv["generated_voice_id"]] = {"description": description, "sha256": art.sha256, "duration": duration, "at": _now()}
        out.append({"generated_voice_id": pv["generated_voice_id"], "sha256": art.sha256, "duration": round(duration, 1),
                    "text": pv.get("text") or ""})
    _set_designs(owner, dict(sorted(designs.items(), key=lambda kv: kv[1].get("at", ""))[-RECENT_DESIGNS:]))
    return {"previews": out}


class FromPreviewRequest(BaseModel):
    generated_voice_id: str
    name: str
    sha256: str | None = None
    description: str = ""
    consent: bool = False


@app.post("/voices/mine/from-preview", status_code=201)
def add_my_voice_from_preview(req: FromPreviewRequest, owner: str = Depends(current_owner)) -> dict:
    """Keep one designed preview as one of your own voices (a slot, no credits)."""
    if not req.consent:
        raise HTTPException(status_code=403, detail="Say you have the right to use this voice.")
    if settings.dry_run or not hasattr(voice, "save_voice"):
        raise HTTPException(status_code=503, detail="Voices cannot be designed in this setup (no vendor that designs).")
    label = _voice_name_or_422(req.name)
    _no_voice_called(owner, label)
    designed = _designs(owner).get(req.generated_voice_id) or {}
    description = " ".join(req.description.split()) or designed.get("description") or ""
    try:
        voice_id = voice.save_voice(req.generated_voice_id, f"voltage-mine-{label}", description)
    except Exception as exc:  # noqa: BLE001 — the vendor's refusal, in its own words
        raise HTTPException(status_code=502, detail=str(exc) or "The voice could not be kept.") from None
    entry = {"voice_id": voice_id, "name": label, "seconds": 0.0, "at": _now(), "kind": "designed", "consent_granted_at": _now(),
             "sample_sha": req.sha256 or designed.get("sha256"), "description": description or None}
    _set_my_voices(owner, [*_my_voices(owner), entry])
    return _voice_entry(entry)


@app.delete("/voices/mine/{voice_id}", status_code=204)
def delete_my_voice(voice_id: str, owner: str = Depends(current_owner)) -> Response:
    """Remove one of your own voices: forgotten here, and deleted at the vendor."""
    mine = _my_voices(owner)
    if not any(v["voice_id"] == voice_id for v in mine):
        raise HTTPException(status_code=404, detail="No such voice of yours.")
    _set_my_voices(owner, [v for v in mine if v["voice_id"] != voice_id])
    try:
        getattr(voice, "delete_voice", lambda v: None)(voice_id)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger("ave").warning("voice %s forgotten, but still at ElevenLabs: %s", voice_id, exc)
    return Response(status_code=204)


@app.get("/videos")
def list_projects(project: str | None = None, recent: int | None = None, owner: str = Depends(current_owner)) -> dict:
    """The caller's videos, newest first — enough to show and reopen them:
    a frame (the source media), where each stands, and its last change (UX-3).
    Folders: `project=none` lists the standalone ones, `project=<id>` one
    project's; `recent=N` caps the list."""
    from app.store.repository import ANY_FOLDER
    folder: str | None = ANY_FOLDER
    if project == "none":
        folder = None
    elif project:
        folder = _owned_project(project, owner).project_id
    found = repo.list(owner, folder=folder)
    if recent is not None:
        found = found[:max(0, recent)]
    return {"videos": [_summary(r) for r in found]}


def _summary(r: ProjectRecord) -> dict:
    pid = r.source.project_id
    folder = _folder_of(r)
    live = [e for e in repo.list_edits(pid) if not e.reverted]
    plan = repo.latest_plan(pid)
    settings_ = repo.settings(pid)
    if live:
        state = "shipped"
    elif plan is not None:
        state = "draft"
    else:
        state = "new"
    if plan is not None and plan.log:
        last = plan.log[-1]["text"]
    elif live:
        last = f"{len(live)} {'line' if len(live) == 1 else 'lines'} changed"
    else:
        last = "Nothing changed yet"
    return {
        "video_id": pid,
        "project_id": folder.project_id if folder else None,
        "project_name": folder.name if folder else None,
        "filename": r.source.filename,
        "duration": r.source.duration,
        "created_at": r.created_at,
        "edits": len(live),
        "media": _artifact_dict(r.source.media),
        "state": state,
        "last_change": last,
        "variant_of": settings_.get("variant_of"),
    }


@app.get("/videos/{project_id}")
def get_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Everything needed to reopen a video: source, transcript, approved
    edits and the chat."""
    record = _owned(project_id, owner)
    speakers = _speakers_by_take(project_id)
    return {
        **_project_dict(record),
        "edits": [_edit_dict(e, speakers) for e in repo.list_edits(project_id)],
        "messages": [_message_dict(m) for m in repo.messages(project_id)],
        # Phase 20: the composer talks to Voltage with tools when this is on.
        "agent": _agent_on(),
    }


def _speakers_by_take(project_id: str) -> dict[str, str | None]:
    """Who each take was given to, by candidate id and by edit id, from the
    plans' items — the edit itself does not know (Volt's rows name them). An
    edit may belong to an earlier plan than the latest, so every plan is read."""
    out: dict[str, str | None] = {}
    for plan in repo.plans(project_id):
        for item in plan.items:
            if item.candidate_id:
                out[item.candidate_id] = item.speaker
            if item.edit_id:
                out[item.edit_id] = item.speaker
    return out


def _voice_of(plan: EditPlan) -> str | None:
    # A removal is room tone, not a voice.
    return None if plan.voice_profile_id in ("none", "") else plan.voice_profile_id


def _edit_dict(e: ApprovedEdit, speakers: dict[str, str | None]) -> dict:
    return {
        "edit_id": e.edit_id,
        "candidate_id": e.candidate_id,
        "new_text": e.plan.new_text,
        "selection": {"start": e.plan.selection.start, "end": e.plan.selection.end},
        "mix": e.plan.mix,
        "delivery": e.plan.delivery,
        "flex": e.plan.flex,
        "role": role_of(e.plan), "offset_db": e.plan.offset_db,
        "overridden": e.overridden,
        "reverted": e.reverted,
        "partner": e.partner,
        # Volt: the row says who the line is for and whose voice says it.
        "speaker": speakers.get(e.edit_id, speakers.get(e.candidate_id)),
        "voice_profile_id": _voice_of(e.plan),
    }


@app.get("/videos/{project_id}/usage")
@app.get("/projects/{project_id}/usage", deprecated=True)
def get_usage(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """What the project has spent, per vendor, against its limits. USD is an
    estimate from list prices."""
    record = _owned(project_id, owner)
    folder = _folder_of(record)
    return {
        "spent_usd": round(ledger.spent_usd(project_id), 4),
        "ceiling_usd": ledger.ceiling_usd,
        # Folders: the project's ceiling (when set) and what the project has spent.
        "project_ceiling_usd": folder.ceiling_usd if folder else None,
        "project_spent_usd": round(ledger.spent_usd_by_folder(folder.project_id), 4) if folder else None,
        "user_spent_usd": round(ledger.spent_usd_by_owner(owner), 4) if settings.auth_mode != "off" else None,
        "user_ceiling_usd": settings.user_budget_usd if settings.auth_mode != "off" else None,
        "voice_characters": budget.spent(project_id),
        "voice_characters_ceiling": budget.ceiling,
        "lines": [
            {"vendor": u.vendor, "what": u.what, "unit": u.unit, "units": round(u.units, 4),
             "usd": round(u.usd, 4), "calls": u.calls}
            for u in ledger.lines(project_id)
        ],
    }


# How the Usage page names each vendor's share.
VENDOR_LABELS = {"anthropic": "Voltage thinking", "elevenlabs": "Voices and takes", "openai": "Transcription"}
# The ElevenLabs rows that are a take: the budget charges takes as "speech";
# the agent tests' fake ledger says "take".
TAKE_WHATS = ("speech", "take")


def _period_start(period: str) -> str | None:
    """When the period began, in the ledger's own time (UTC ISO); None for all time."""
    now = datetime.now(timezone.utc)
    if period == "week":
        return iso(now - timedelta(days=7))
    if period == "month":
        return iso(now.replace(day=1, hour=0, minute=0, second=0, microsecond=0))
    return None


def _usage_groups(owner: str, since: str | None) -> tuple[list[dict], dict]:
    """The Usage table: every project with its videos nested (each video's
    spend while it was in that project), a Project-level row per project,
    and the standalone videos under "No project". A video moved between
    projects shows under each, with what it spent there. Also each
    (group, video) pair's spend by vendor, for the chosen scope's totals."""
    rows = ledger.breakdown(owner, since)
    videos = {r.source.project_id: r for r in repo.list(owner)}
    folders = repo.list_projects(owner)
    cells: dict[tuple[str | None, str], dict[str, float]] = {}
    for row in rows:
        if row["video_id"].startswith("user-"):
            continue
        key = (row["folder_id"], row["video_id"])
        cells.setdefault(key, {})[row["vendor"]] = cells.get(key, {}).get(row["vendor"], 0.0) + row["usd"]

    def video_rows(folder_id: str | None) -> list[dict]:
        ids = {vid for (fid, vid) in cells if fid == folder_id and vid}
        ids |= {vid for vid, r in videos.items() if r.folder_id == folder_id}
        out = []
        for vid in ids:
            r = videos.get(vid)
            if r is None:
                continue   # a deleted video's rows went with it
            out.append({"video_id": vid, "filename": r.source.filename, "here": r.folder_id == folder_id,
                        "spent_usd": round(sum(cells.get((folder_id, vid), {}).values()), 4)})
        return sorted(out, key=lambda v: (-v["spent_usd"], v["filename"]))

    groups = []
    for p in folders:
        project_level = round(sum(cells.get((p.project_id, ""), {}).values()), 4)
        nested = video_rows(p.project_id)
        groups.append({"project_id": p.project_id, "name": p.name, "ceiling_usd": p.ceiling_usd,
                       "project_level_usd": project_level, "videos": nested,
                       "spent_usd": round(project_level + sum(v["spent_usd"] for v in nested), 4)})
    alone = video_rows(None)
    groups.append({"project_id": None, "name": "No project", "ceiling_usd": None, "project_level_usd": None,
                   "videos": alone, "spent_usd": round(sum(v["spent_usd"] for v in alone), 4)})
    return groups, {"cells": cells, "rows": rows}


def _usage_totals(owner: str, period: str, scope: str, groups: list[dict], raw: dict) -> dict:
    """The chosen scope's totals: spent, its ceiling (when it has one) and by vendor."""
    cells: dict = raw["cells"]
    if scope.startswith("v:"):
        vid = scope[2:]
        record = _owned(vid, owner)
        picked = [c for (fid, v), c in cells.items() if v == vid]
        label, ceiling = record.source.filename, ledger.ceiling_usd
    elif scope == "none":
        picked = [c for (fid, v), c in cells.items() if fid is None]
        label, ceiling = "Standalone videos", None
    elif scope != "all":
        project = _owned_project(scope, owner)
        picked = [c for (fid, v), c in cells.items() if fid == project.project_id]
        label, ceiling = f"Project {project.name}", project.ceiling_usd
    else:
        picked = [{row["vendor"]: row["usd"]} for row in raw["rows"]]
        label = month_name() if period == "month" else ("Last 7 days" if period == "week" else "All time")
        ceiling = settings.user_budget_usd if period == "month" else None
    by_vendor = {v: 0.0 for v in VENDOR_LABELS}
    for c in picked:
        for vendor, usd in c.items():
            by_vendor[vendor] = by_vendor.get(vendor, 0.0) + usd
    return {"scope": scope, "label": label, "spent_usd": round(sum(by_vendor.values()), 4), "ceiling_usd": ceiling,
            "by_vendor": [{"vendor": v, "label": VENDOR_LABELS.get(v, v), "usd": round(usd, 4)} for v, usd in by_vendor.items()]}


@app.get("/usage")
def get_my_usage(period: Literal["week", "month", "all"] = "month", scope: str = "all",
                 owner: str = Depends(current_owner)) -> dict:
    """What the caller has spent across their projects in the period: the
    week is the last seven days, the month the calendar month so far (UTC).
    A turn is one "Thinking" step; a take is one ElevenLabs speech call; the
    voices made are the caller's own plus every project's. A voice designed
    outside any project (the voices page) counts in the totals, not by project."""
    since = _period_start(period)
    groups, raw = _usage_groups(owner, since)
    by_vendor = {v: 0.0 for v in VENDOR_LABELS}
    by_video: list[dict] = []
    turns = takes = 0
    voices_made = len(_my_voices(owner))
    projects = repo.list(owner)
    turns_by_folder: dict[str, int] = {}
    for r in projects:
        pid = r.source.project_id
        lines = ledger.lines(pid, since)
        project_turns = repo.count_steps(pid, "Thinking", since)
        for u in lines:
            by_vendor[u.vendor] = by_vendor.get(u.vendor, 0.0) + u.usd
            if u.vendor == VoiceBudget.VENDOR and u.what in TAKE_WHATS:
                takes += u.calls
        turns += project_turns
        voices_made += len(repo.settings(pid).get("made_voices") or [])
        if r.folder_id:
            turns_by_folder[r.folder_id] = turns_by_folder.get(r.folder_id, 0) + project_turns
        by_video.append({
            "video_id": pid, "project_id": r.folder_id, "filename": r.source.filename, "turns": project_turns,
            "voice_characters": int(sum(u.units for u in lines if u.vendor == VoiceBudget.VENDOR and u.unit == VoiceBudget.UNIT)),
            "spent_usd": round(sum(u.usd for u in lines), 4), "cap_usd": ledger.ceiling_usd,
        })
    # Folders: each project's share, from the rows charged while its videos were in it.
    by_project = [{
        "project_id": p.project_id, "name": p.name, "videos": sum(1 for r in projects if r.folder_id == p.project_id),
        "turns": turns_by_folder.get(p.project_id, 0), "spent_usd": round(ledger.spent_usd_by_folder(p.project_id, since), 4),
        "ceiling_usd": p.ceiling_usd,
    } for p in repo.list_projects(owner)]
    for u in ledger.lines(_user_store(owner), since):
        by_vendor[u.vendor] = by_vendor.get(u.vendor, 0.0) + u.usd
    thinking = by_vendor.get("anthropic", 0.0)
    return {
        "period": period,
        "spent_usd": round(sum(by_vendor.values()), 4),
        "ceiling_usd": settings.user_budget_usd,
        "project_cap_usd": ledger.ceiling_usd,
        "turns": turns,
        "takes": takes,
        "voices_made": voices_made,
        "avg_turn_usd": round(thinking / turns, 4) if turns else 0.0,
        "by_vendor": [{"vendor": v, "label": VENDOR_LABELS.get(v, v), "usd": round(usd, 4)} for v, usd in by_vendor.items()],
        "by_video": by_video,
        "by_project": by_project,
        # Spend scopes: the table (projects with their videos nested, "No
        # project" last) and the chosen scope's totals (`scope` = all | none
        # | f<n> | v:p<n>).
        "groups": groups,
        "totals": _usage_totals(owner, period, scope, groups, raw),
    }


class SettingsUpdate(BaseModel):
    autonomy: Literal["ask", "draft"] | None = None
    # 20d: what one turn may spend, and how hard Voltage thinks.
    turn_usd: float | None = None
    effort: Literal["medium", "high", "xhigh"] | None = None
    # Volt: the steps that still ask under Just do it, any subset.
    ask_before: dict[str, bool] | None = None
    # 2026-10-20: the mix. Any subset of voice_default_lufs, bed_under_db (12 to 18),
    # speech_clear_db and loudness ("social" -14 LUFS or "general" -16).
    mix: dict | None = None


@app.get("/videos/{project_id}/settings")
@app.get("/projects/{project_id}/settings", deprecated=True)
def get_settings(project_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return {"settings": _settings(project_id, owner)}


@app.put("/videos/{project_id}/settings")
@app.put("/projects/{project_id}/settings", deprecated=True)
def update_settings(
    project_id: str, req: SettingsUpdate, owner: str = Depends(current_owner),
) -> dict:
    """What Voltage may do on this project: the autonomy, a turn's spend
    cap (between a cent and the project's ceiling), the effort, and which
    steps still wait for a yes under Just do it."""
    _owned(project_id, owner)
    turn_usd = None if req.turn_usd is None else _clamp_turn_usd(req.turn_usd)
    ask_before = None if req.ask_before is None else _ask_before({**_settings(project_id, owner)["ask_before"], **req.ask_before})
    mix = None if req.mix is None else _clean_mix({**_settings(project_id, owner)["mix"], **req.mix})
    repo.set_settings(project_id, autonomy=req.autonomy, turn_usd=turn_usd, effort=req.effort, ask_before=ask_before, mix=mix)
    return {"settings": _settings(project_id, owner)}


MIX_DEFAULTS = {"voice_default_lufs": -18.0, "bed_under_db": 15.0, "speech_clear_db": 10.0, "loudness": "social"}
LOUDNESS_TARGETS = {"social": -14.0, "general": -16.0}


def _clean_mix(m: dict) -> dict:
    """The mix settings, each in its range."""
    return {
        "voice_default_lufs": round(min(-10.0, max(-30.0, float(m.get("voice_default_lufs", -18.0)))), 1),
        "bed_under_db": round(min(18.0, max(12.0, float(m.get("bed_under_db", 15.0)))), 1),
        "speech_clear_db": round(min(20.0, max(3.0, float(m.get("speech_clear_db", 10.0)))), 1),
        "loudness": m.get("loudness") if m.get("loudness") in LOUDNESS_TARGETS else "social",
    }


def _mix_settings(project_id: str) -> mixmod.MixSettings:
    m = _clean_mix({**MIX_DEFAULTS, **(repo.settings(project_id).get("mix") or {})})
    return mixmod.MixSettings(voice_default_lufs=m["voice_default_lufs"], bed_under_db=m["bed_under_db"],
                              clear_db=m["speech_clear_db"], export_lufs=LOUDNESS_TARGETS[m["loudness"]])


def _speech_spans(record: ProjectRecord, edits) -> list[tuple[float, float]]:
    """Where the original's words are heard: every word but those a removal took out."""
    removed = [e.plan.selection for e in edits if e.plan.mix == "remove"]
    return [(w.start, w.end) for w in record.transcript.words
            if not any(r.start <= w.start + 1e-3 and w.end <= r.end + 1e-3 for r in removed)]


def _mix_report(mixed: dict, previewed) -> dict | None:
    """The mix as the rows read it: per line by edit and by take (a proposal's
    row knows its take), with the item a previewed proposal came from."""
    if not mixed:
        return None
    items = {e.edit_id: item_id for item_id, e in previewed}
    lines = [{**ln, "item_id": items.get(ln["edit_id"])} for ln in mixed.get("lines", [])]
    return {**mixed, "lines": lines}


class SpeakerUpdate(BaseModel):
    name: str | None = None
    # A voice id to speak this speaker's new lines in; null returns them to
    # the chat's voice. Omitted = unchanged.
    voice_id: str | None = None
    clear_voice: bool = False


@app.get("/videos/{project_id}/speakers")
@app.get("/projects/{project_id}/speakers", deprecated=True)
def get_speakers(project_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return {"speakers": _speakers(project_id)}


@app.put("/videos/{project_id}/speakers/{label}")
@app.put("/projects/{project_id}/speakers/{label}", deprecated=True)
def update_speaker(
    project_id: str, label: str, req: SpeakerUpdate, owner: str = Depends(current_owner),
) -> dict:
    _owned(project_id, owner)
    if label not in {s.label for s in repo.speakers(project_id)}:
        raise HTTPException(status_code=404, detail="speaker not found")
    name = req.name.strip() if req.name is not None else None
    repo.set_speaker(project_id, label, name=name or None, voice_id=req.voice_id,
                     clear_voice=req.clear_voice)
    return {"speakers": _speakers(project_id)}


@app.post("/videos/{project_id}/speakers/detect")
@app.post("/projects/{project_id}/speakers/detect", deprecated=True)
def detect_speakers(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Find who speaks when, for a project transcribed before Phase 11."""
    record = _owned(project_id, owner)
    if transcriber_label.startswith("openai"):
        try:
            _ensure_spend(project_id)
        except SpendCeilingReached as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc
    try:
        turns = transcriber.diarize(record.source)
    except TranscriptionError as exc:
        log.warning("diarization failed for %s: %s", project_id, exc)
        raise HTTPException(status_code=502, detail="Could not detect speakers. Please try again.") from exc
    _record_diarization(project_id, record.source.duration)
    repo.update_transcript(project_id, assign_speakers(record.transcript, turns))
    return _project_dict(repo.get(project_id))


# ── The chips above Voltage's box (2026-10-20) ──────────────────────────────

def _brief_text(project_id: str) -> str:
    """The project's name and brief, for the first read; empty when standalone."""
    record = repo.get(project_id)
    project = repo.get_project(record.folder_id) if record is not None and record.folder_id else None
    if project is None:
        return ""
    return f"{project.name}: {project.brief}".strip(": ") if project.brief else project.name


def _chip_sources(project_id: str, record: ProjectRecord) -> str:
    """Everything a chip may name: what is said, what is on screen, the brief, the voices, the lines in the plan."""
    parts = [st.text for st in statements_of(record.transcript)]
    sight = repo.settings(project_id).get("sight") or {}
    parts += [str(sight.get(k) or "") for k in ("setting", "people", "text_on_screen", "place_confirmed", "opening")]
    parts += list(sight.get("details") or [])
    parts.append(_brief_text(project_id))
    parts += [s.name or "" for s in repo.speakers(project_id)]
    parts += [v.get("name") or "" for v in repo.settings(project_id).get("made_voices") or []]
    plan = repo.latest_plan(project_id)
    parts += [i.new_text for i in (plan.items if plan else ())]
    return " ".join(p for p in parts if p)


def _clean_chips(project_id: str, record: ProjectRecord, raw) -> list[dict]:
    return [{**c.as_dict(), "label": plain(c.label), "prompt": plain(c.prompt)} for c in chips.clean(raw, _chip_sources(project_id, record))]


def _chips_now(project_id: str, record: ProjectRecord) -> dict:
    """The chips to show: the last turn's, else the first read's, else a generic set by clip type."""
    saved = repo.settings(project_id)
    if saved.get("suggestions") is not None:
        return {"suggestions": saved["suggestions"], "source": "turn"}
    reading = saved.get("reading") or {}
    if reading.get("suggestions"):
        return {"suggestions": reading["suggestions"], "source": "reading"}
    has_speech = bool(record.transcript.words or record.transcript.statements)
    return {"suggestions": [c.as_dict() for c in chips.fallback(has_speech)], "source": "generic"}


def _after_turn_chips(project_id: str, record: ProjectRecord, said: str, raw: list) -> None:
    """After a turn the chips are Voltage's next ones; with none, the chip just used goes."""
    fresh = _clean_chips(project_id, record, raw)
    if fresh:
        repo.set_settings(project_id, suggestions=fresh)
        return
    current = _chips_now(project_id, record)["suggestions"]
    said_norm = " ".join((said or "").split()).lower()
    left = [c for c in current if " ".join(c["prompt"].split()).lower() != said_norm]
    if len(left) != len(current):
        repo.set_settings(project_id, suggestions=left)


@app.get("/videos/{project_id}/suggestions")
def get_suggestions(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """The chips above Voltage's box: up to four, each {label, prompt, kind, grounded_in}, and where they came from."""
    record = _owned(project_id, owner)
    return _chips_now(project_id, record)


class ChipEvent(BaseModel):
    # shown: on screen; clicked: put in the box; sent: sent, as is or edited first.
    event: Literal["shown", "clicked", "sent"]
    kind: Literal["fix", "change", "add", "voice", "finish"]
    label: str = ""
    edited: bool = False


CHIP_EVENTS_KEPT = 5000


@app.post("/videos/{project_id}/suggestions/events", status_code=204)
def chip_event(project_id: str, req: ChipEvent, owner: str = Depends(current_owner)) -> Response:
    """What people do with the chips, by kind, so the useful ones can be told apart."""
    _owned(project_id, owner)
    events = repo.meta_list("chip_events")[-(CHIP_EVENTS_KEPT - 1):]
    events.append({"video": project_id, "owner": owner, "event": req.event, "kind": req.kind,
                   "label": req.label[:60], "edited": bool(req.edited), "at": _now()})
    repo.set_meta_list("chip_events", events)
    return Response(status_code=204)


@app.get("/suggestions/stats")
def chip_stats(owner: str = Depends(current_owner)) -> dict:
    """Chips shown, clicked, edited before sending, and sent as they were, by kind (the caller's own)."""
    out = {k: {"shown": 0, "clicked": 0, "edited": 0, "sent_as_is": 0} for k in chips.KINDS}
    for e in repo.meta_list("chip_events"):
        if e.get("owner") != owner or e.get("kind") not in out:
            continue
        row = out[e["kind"]]
        if e["event"] == "sent":
            row["edited" if e.get("edited") else "sent_as_is"] += 1
        else:
            row[e["event"]] += 1
    return {"by_kind": out}


# ── The video as a piece (2026-10-20) ───────────────────────────────────────

def _signals(project_id: str, record: ProjectRecord) -> dict:
    """The clip's beats, energy and sound, read once per source and kept."""
    saved = repo.settings(project_id).get("signals")
    if saved and saved.get("sha256") == record.source.media.sha256:
        return saved["data"]
    words = [(w.start, w.end) for w in record.transcript.words]
    sig = understand_mod.read_signals(record.source.media.path, record.source.duration, words,
                                      cache_dir=artifacts.root / project_id / "understand")
    data = sig.as_dict()
    repo.set_settings(project_id, signals={"sha256": record.source.media.sha256, "data": data})
    return data


def _adaptive_frames(project_id: str, record: ProjectRecord, times: list[float]) -> list[Frame]:
    """Frames at the times the signals chose (every cut and peak, one a second, up to 24), kept."""
    out_dir = artifacts.root / project_id / "frames-adaptive"
    out_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for at in times:
        dest = out_dir / f"at-{at:07.2f}.jpg"
        if not dest.exists():
            try:
                ffmpeg.extract_frame(record.source.media.path, dest, at, width=frames_mod.FRAME_WIDTH)
            except Exception:  # noqa: BLE001 - one missing frame is not worth the read
                continue
        frames.append(Frame(at=at, path=str(dest)))
    return frames


def _understand(project_id: str, record: ProjectRecord, lines: list[Line]) -> dict | None:
    """The first read as one look at the whole piece: the understanding, the
    opening, the roles, the style line and the chips, in one call. None when
    this planner cannot (the plain reads follow)."""
    if planner is None or not hasattr(planner, "understand"):
        return None
    try:
        _ensure_spend(project_id)
        signals = _signals(project_id, record)
        frames = _adaptive_frames(project_id, record, signals.get("frame_times") or [])
        vision = planner.understand(frames, signals, lines, meter=_meter(project_id, "looking"), brief=_brief_text(project_id))
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if vision is None:
        return None
    sources = _chip_sources(project_id, record)
    record_ = understanding_mod.build(signals, vision, sources, repo.settings(project_id).get("understanding"))
    repo.set_settings(project_id, understanding=record_)
    by_name = {s.name: s.label for s in repo.speakers(project_id)}
    out = {"opening": plain(vision.get("opening") or ""), "at": _now(),
           "roles": [{"label": by_name[r["speaker"]], "role": r["role"].strip().rstrip("."), "why": r.get("why", "")}
                     for r in vision.get("roles") or [] if r.get("speaker") in by_name],
           "suggestions": _clean_chips(project_id, record, vision.get("suggestions"))}
    if not lines:
        read = record_["read"]
        sight = Sight(opening=out["opening"], setting=read.get("setting", ""), mood=vision.get("mood", ""),
                      people=vision.get("people", ""), text_on_screen="; ".join(read.get("on_screen_text") or []),
                      place_guess=vision.get("place_guess", ""), confidence=vision.get("confidence", ""),
                      beats=tuple({"at": b["at"], "note": b["label"]} for b in record_["beats"] if b.get("kind") == "visual"),
                      details=tuple((vision.get("details") or [])[:5]))
        repo.set_settings(project_id, sight=asdict(sight))
        out = {**out, "sight": asdict(sight)}
    repo.set_settings(project_id, reading=out)
    return out


def _understanding_view(project_id: str, record: ProjectRecord) -> dict:
    """The record with the user's corrections applied; signals only, without Claude."""
    saved = repo.settings(project_id).get("understanding")
    if saved is None:
        saved = understanding_mod.build(_signals(project_id, record), None, "", None)
    return understanding_mod.view(saved)


@app.get("/videos/{project_id}/understanding")
def get_understanding(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """What Voltage sees in the video: its kind, a summary, the beats with times and confidences, the energy, the style line."""
    record = _owned(project_id, owner)
    return _understanding_view(project_id, record)


class CorrectionRequest(BaseModel):
    # In the user's words: "This is Muay Thai", "That's not a knockdown, he slipped".
    text: str
    # A beat it is about, by time, with a new label or removed.
    beat_at: float | None = None
    label: str | None = None
    remove: bool = False


@app.post("/videos/{project_id}/understanding/corrections")
def correct_understanding(project_id: str, req: CorrectionRequest, owner: str = Depends(current_owner)) -> dict:
    """A correction to Voltage's read; kept, and it wins in every later turn."""
    record = _owned(project_id, owner)
    if not req.text.strip() and req.beat_at is None:
        raise HTTPException(status_code=422, detail="Say what to correct.")
    current = repo.settings(project_id).get("understanding") or understanding_mod.build(_signals(project_id, record), None, "", None)
    updated = understanding_mod.correct(current, req.text, req.beat_at, req.label, req.remove)
    repo.set_settings(project_id, understanding=updated)
    repo.add_message(project_id, "user", f"Correction: {req.text.strip()}" if req.text.strip() else "Corrected a beat")
    return understanding_mod.view(updated)


class StyleRequest(BaseModel):
    # The style line as accepted or rewritten by the user.
    line: str
    accepted: bool = True


@app.put("/videos/{project_id}/style")
def set_style(project_id: str, req: StyleRequest, owner: str = Depends(current_owner)) -> dict:
    """The style line for the piece, accepted as Voltage proposed it or changed."""
    record = _owned(project_id, owner)
    if not req.line.strip():
        raise HTTPException(status_code=422, detail="Say how the new words should sound.")
    current = repo.settings(project_id).get("understanding") or understanding_mod.build(_signals(project_id, record), None, "", None)
    before = (current.get("style") or {}).get("line", "")
    style = {"line": plain(req.line.strip()), "accepted": req.accepted, "by": "user" if req.line.strip() != before else "voltage", "shown": True}
    updated = {**current, "style": style}
    repo.set_settings(project_id, understanding=updated)
    return understanding_mod.view(updated)


class ReadRequest(BaseModel):
    # Read the clip again even though a reading is saved.
    again: bool = False


@app.post("/videos/{project_id}/reading")
@app.post("/projects/{project_id}/reading", deprecated=True)
def read_project(project_id: str, req: ReadRequest, owner: str = Depends(current_owner)) -> dict:
    """Voltage's first look at the clip (UX-2): one specific opening line for
    the goal stage, and a role for each speaker ("the Customer") to confirm
    or rename. Saved with the project; read once unless asked again."""
    record = _owned(project_id, owner)
    saved = repo.settings(project_id).get("reading")
    if saved and not req.again:
        return saved
    lines = _lines(record)
    understood = _understand(project_id, record, lines)
    if understood is not None:
        return understood
    if not lines:
        # UX-5: nothing to read, so Voltage looks at the picture instead.
        try:
            _ensure_spend(project_id)
            sight = _sight(project_id, record)
        except SpendCeilingReached as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc
        except NonRetryableError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except VendorError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        out = {"opening": plain(sight.opening), "roles": [], "sight": asdict(sight),
               "suggestions": _clean_chips(project_id, record, sight.suggestions)}
        repo.set_settings(project_id, reading=out)
        return out
    try:
        _ensure_spend(project_id)
        if planner is None:
            raise HTTPException(status_code=503, detail=NEEDS_CLAUDE)
        reading = planner.read(lines, meter=_meter(project_id, "reading"), brief=_brief_text(project_id))
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    by_name = {s.name: s.label for s in repo.speakers(project_id)}
    out = {
        "opening": plain(reading.opening),
        "roles": [
            {"label": by_name[r.speaker], "role": r.role, "why": r.why}
            for r in reading.roles if r.speaker in by_name
        ],
        "at": _now(),
        "suggestions": _clean_chips(project_id, record, reading.suggestions),
    }
    repo.set_settings(project_id, reading=out)
    return out


@app.delete("/videos/{project_id}", status_code=204)
def delete_project(project_id: str, owner: str = Depends(current_owner)) -> None:
    """Delete the project and all of its media. This is also how consent is
    withdrawn (design spec §2): nothing of the speaker is kept."""
    _owned(project_id, owner)
    _delete_project(project_id)


def _delete_project(project_id: str) -> None:
    # A clone of the speaker's voice goes with the project (Phase 15a). If the
    # vendor cannot be reached the project is still deleted here; the failure
    # is logged by name so the clone can be removed by hand. A voice someone
    # kept as their own stays (Volt): it is theirs now, not the project's.
    kept = _kept_voice_ids()
    left = clones.purge(project_id, keep=kept)
    if left:
        logging.getLogger("ave").warning(
            "project %s deleted, but these voice clone(s) are still at ElevenLabs: %s", project_id, ", ".join(left))
    # Voices Voltage made for the clip (designed, or added from the library;
    # 20b) go with it too, so slots come back.
    for made in repo.settings(project_id).get("made_voices") or []:
        if made["voice_id"] in kept:
            continue
        try:
            getattr(voice, "delete_voice", lambda v: None)(made["voice_id"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ave").warning("project %s deleted, but voice %s (%s) is still at ElevenLabs: %s",
                                             project_id, made.get("name"), made["voice_id"], exc)
    repo.delete(project_id)
    shutil.rmtree(artifacts.root / project_id, ignore_errors=True)


@app.delete("/account", status_code=204)
def delete_account(owner: str = Depends(current_owner)) -> Response:
    """Everything of the caller's goes: every project with its media and the
    voices made for it, every voice of their own (deleted at the vendor; a
    failure is logged by name), their samples and their defaults."""
    for r in repo.list(owner):
        _delete_project(r.source.project_id)
    for v in _my_voices(owner):
        try:
            getattr(voice, "delete_voice", lambda vid: None)(v["voice_id"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ave").warning("account %s deleted, but voice %s (%s) is still at ElevenLabs: %s",
                                             owner, v.get("name"), v["voice_id"], exc)
    for key in ("my_voices", "prefs", "designs"):
        repo.delete_meta(f"{key}:{owner}")
    repo.delete(_user_store(owner))   # the designs' spend, kept under the owner's own id
    shutil.rmtree(artifacts.root / _user_store(owner), ignore_errors=True)
    return Response(status_code=204)


# ── Folders: a project is a folder of videos ─────────────────────────────────
# A project has a name, a brief, defaults for new videos, shared voices,
# reference files and an optional spending ceiling. Its voices, files and
# brief suggestions are meta lists keyed by its id; the files' bytes live
# under the artifact store at projects/<id>/files/<sha256>.

def _project_voices(project_id: str) -> list[dict]:
    return repo.meta_list(f"project_voices:{project_id}")


def _set_project_voices(project_id: str, voices: list[dict]) -> None:
    repo.set_meta_list(f"project_voices:{project_id}", voices)


def _project_files(project_id: str) -> list[dict]:
    """The reference files, `text` included (what read_project_files searches)."""
    return repo.meta_list(f"project_files:{project_id}")


def _set_project_files(project_id: str, files: list[dict]) -> None:
    repo.set_meta_list(f"project_files:{project_id}", files)


def _suggestions(project_id: str) -> list[dict]:
    return repo.meta_list(f"brief_suggestions:{project_id}")


def _set_suggestions(project_id: str, items: list[dict]) -> None:
    repo.set_meta_list(f"brief_suggestions:{project_id}", items)


def _files_dir(project_id: str) -> Path:
    return artifacts.root / "projects" / project_id / "files"


def _file_dict(entry: dict) -> dict:
    return {k: entry.get(k) for k in ("name", "sha256", "size", "kind", "at")}


def _suggestion_dict(entry: dict) -> dict:
    record = repo.get(entry.get("video_id") or "")
    return {**entry, "filename": record.source.filename if record else None}


def _folder_dict(project: Project) -> dict:
    return {
        "project_id": project.project_id,
        "name": project.name,
        "brief": project.brief,
        "brief_version": project.brief_version,
        "settings": {k: v for k, v in _defaults_for(project.owner, project).items() if k in SETTING_KEYS},
        "ceiling_usd": project.ceiling_usd,
        "spent_usd": round(ledger.spent_usd_by_folder(project.project_id), 4),
        "created_at": project.created_at,
    }


def _last_at(videos: list[ProjectRecord], fallback: str) -> str:
    """When something last happened in the project: the newest message or upload."""
    at = fallback
    for r in videos:
        at = max(at, r.created_at)
        messages = repo.messages(r.source.project_id)
        if messages:
            at = max(at, messages[-1].at)
    return at


def _project_summary(project: Project) -> dict:
    videos = repo.list(project.owner, folder=project.project_id)
    return {
        **{k: v for k, v in _folder_dict(project).items() if k != "settings"},
        "video_count": len(videos),
        "voices": len(_project_voices(project.project_id)),
        "files": len(_project_files(project.project_id)),
        "last_at": _last_at(videos, project.created_at),
    }


def _voices_used_by(video_id: str) -> set[str]:
    """The voices a video's kept edits and ready proposals speak in."""
    used = {e.plan.voice_profile_id for e in repo.list_edits(video_id) if not e.reverted}
    plan = repo.latest_plan(video_id)
    for item in (plan.items if plan else ()):
        if item.status == "ready" and item.candidate_id:
            candidate = repo.get_candidate(video_id, item.candidate_id)
            if candidate is not None:
                used.add(candidate.plan.voice_profile_id)
    return {v for v in used if v}


def _project_page(project: Project) -> dict:
    videos = repo.list(project.owner, folder=project.project_id)
    in_use: dict[str, int] = {}
    for r in videos:
        for vid in _voices_used_by(r.source.project_id):
            in_use[vid] = in_use.get(vid, 0) + 1
    return {
        "project": _folder_dict(project),
        "videos": [_summary(r) for r in videos],
        "voices": [_voice_entry(v, in_use.get(v["voice_id"], 0)) for v in _project_voices(project.project_id)],
        "files": [_file_dict(f) for f in _project_files(project.project_id)],
        "suggestions": [_suggestion_dict(s) for s in _suggestions(project.project_id)],
    }


def _project_view(video_id: str) -> dict | None:
    """The project around a video, for the agent (Folders): name, brief,
    the shared voices, the sister videos with what each shipped, the
    reference files with their text. None for a standalone video."""
    record = repo.get(video_id)
    if record is None or not record.folder_id:
        return None
    project = repo.get_project(record.folder_id)
    if project is None:
        return None
    sisters = []
    for r in repo.list(project.owner, folder=project.project_id):
        pid = r.source.project_id
        if pid == video_id:
            continue
        shipped = [{"text": e.plan.new_text, "voice": _voice_words(pid, r.owner, e.plan.voice_profile_id)}
                   for e in repo.list_edits(pid) if not e.reverted and e.plan.mix != "remove"]
        sisters.append({**_summary(r), "shipped": shipped})
    return {"project_id": project.project_id, "name": project.name, "brief": project.brief,
            "brief_version": project.brief_version,
            "voices": _project_voices(project.project_id), "videos": sisters, "files": _project_files(project.project_id)}


def _suggest_brief(video_id: str, addition: str, why: str) -> str | None:
    """Record what Voltage thinks the brief should add; the brief changes
    only when the user accepts it on the project page."""
    record = repo.get(video_id)
    if record is None or not record.folder_id or repo.get_project(record.folder_id) is None:
        return None
    items = _suggestions(record.folder_id)
    n = 1 + max((int(i["id"][1:]) for i in items if str(i.get("id", "")).startswith("s") and str(i["id"])[1:].isdigit()), default=0)
    entry = {"id": f"s{n}", "text": addition.strip(), "why": why.strip(), "video_id": video_id, "at": _now()}
    _set_suggestions(record.folder_id, [*items, entry])
    return entry["id"]


class ProjectCreate(BaseModel):
    name: str
    brief: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    brief: str | None = None
    # Defaults for new videos: any subset of autonomy, turn_usd, effort, ask_before.
    settings: dict | None = None
    # A null sent on purpose clears the ceiling.
    ceiling_usd: float | None = None


def _project_name_or_422(name: str) -> str:
    label = " ".join(name.split())[:80]
    if not label:
        raise HTTPException(status_code=422, detail="Give the project a name.")
    return label


def _clean_defaults(saved: dict) -> dict:
    """The defaults a project may hold, validated like a video's settings."""
    out: dict = {}
    if saved.get("autonomy") is not None:
        if saved["autonomy"] not in ("ask", "draft"):
            raise HTTPException(status_code=422, detail="autonomy is ask or draft.")
        out["autonomy"] = saved["autonomy"]
    if saved.get("turn_usd") is not None:
        out["turn_usd"] = _clamp_turn_usd(float(saved["turn_usd"]))
    if saved.get("effort") is not None:
        if saved["effort"] not in EFFORTS:
            raise HTTPException(status_code=422, detail=f"effort is one of {', '.join(EFFORTS)}.")
        out["effort"] = saved["effort"]
    if saved.get("ask_before") is not None:
        if not isinstance(saved["ask_before"], dict):
            raise HTTPException(status_code=422, detail="ask_before is an object of ship, clone, design.")
        out["ask_before"] = {k: bool(v) for k, v in saved["ask_before"].items() if k in ASK_BEFORE}
    return out


@app.get("/projects")
def list_folders(owner: str = Depends(current_owner)) -> dict:
    """The caller's projects (folders), with how much each holds and has spent."""
    return {"projects": [_project_summary(p) for p in repo.list_projects(owner)]}


@app.post("/projects", status_code=201)
def create_folder(req: ProjectCreate, owner: str = Depends(current_owner)) -> dict:
    project = repo.create_project(owner, _project_name_or_422(req.name), req.brief.strip())
    return _folder_dict(project)


@app.get("/projects/{project_id}")
def get_folder(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """The project page: the project, its videos, shared voices (with how
    many videos use each), reference files and Voltage's brief suggestions."""
    return _project_page(_owned_project(project_id, owner))


@app.patch("/projects/{project_id}")
def update_folder(project_id: str, req: ProjectUpdate, owner: str = Depends(current_owner)) -> dict:
    _owned_project(project_id, owner)
    name = _project_name_or_422(req.name) if req.name is not None else None
    if req.ceiling_usd is not None and req.ceiling_usd <= 0:
        raise HTTPException(status_code=422, detail="The ceiling is a positive amount, or null for none.")
    project = repo.update_project(
        project_id, name=name, brief=req.brief.strip() if req.brief is not None else None, by=owner,
        settings=_clean_defaults(req.settings) if req.settings is not None else None,
        ceiling_usd=req.ceiling_usd, clear_ceiling="ceiling_usd" in req.model_fields_set and req.ceiling_usd is None,
    )
    return _folder_dict(project)


@app.get("/projects/{project_id}/briefs")
def list_brief_versions(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """F2: every version of the project's brief, newest first."""
    project = _owned_project(project_id, owner)
    return {"current": project.brief_version, "versions": [v.to_dict() for v in briefs.history(database, project_id)]}


@app.get("/projects/{project_id}/briefs/diff")
def diff_brief_versions(project_id: str, a: int, b: int, owner: str = Depends(current_owner)) -> dict:
    """F2: word-level changes from version `a` to version `b` (0 = no brief)."""
    _owned_project(project_id, owner)
    runs = briefs.diff(database, project_id, a, b)
    if runs is None:
        raise HTTPException(status_code=404, detail="brief version not found")
    return {"a": a, "b": b, "changes": runs}


@app.delete("/projects/{project_id}", status_code=204)
def delete_folder(project_id: str, videos: Literal["delete", "keep"], owner: str = Depends(current_owner)) -> Response:
    """Delete a project: its videos go with it (`delete`) or become
    standalone (`keep`). A voice shared only here goes at the vendor
    unless someone kept it as their own or a video still carries it."""
    project = _owned_project(project_id, owner)
    shared = _project_voices(project_id)
    if videos == "delete":
        for r in repo.list(owner, folder=project_id):
            _delete_project(r.source.project_id)
    repo.delete_project(project_id, keep_videos=videos == "keep")
    kept = _kept_voice_ids()
    for r in repo.list(owner):
        kept.update(m["voice_id"] for m in repo.settings(r.source.project_id).get("made_voices") or [])
        kept.update(repo.clones(r.source.project_id).values())
    for v in shared:
        if v["voice_id"] in kept:
            continue
        try:
            getattr(voice, "delete_voice", lambda vid: None)(v["voice_id"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ave").warning("project %s deleted, but voice %s (%s) is still at ElevenLabs: %s",
                                             project.project_id, v.get("name"), v["voice_id"], exc)
    shutil.rmtree(artifacts.root / "projects" / project_id, ignore_errors=True)
    return Response(status_code=204)


@app.get("/projects/{project_id}/videos")
def list_folder_videos(project_id: str, owner: str = Depends(current_owner)) -> dict:
    project = _owned_project(project_id, owner)
    return {"videos": [_summary(r) for r in repo.list(owner, folder=project.project_id)]}


# ── reference files ──

MAX_FILE_BYTES = 20 << 20
MAX_FILE_TEXT = 20_000
TEXT_KINDS = ("txt", "md", "json", "csv")


def _extract_text(name: str, data: bytes) -> str:
    """The file's words, where they can be read without a new dependency:
    text files as they are; a .docx from its XML (stdlib); a .pdf through
    pypdf when it is installed, else nothing."""
    kind = Path(name).suffix.lstrip(".").lower()
    text = ""
    try:
        if kind in TEXT_KINDS:
            text = data.decode("utf-8", errors="replace")
        elif kind == "docx":
            import io
            import re as _re
            import zipfile
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            xml = _re.sub(r"</w:p>", "\n", xml)
            text = _re.sub(r"<[^>]+>", "", xml)
        elif kind == "pdf":
            try:
                import io
                from pypdf import PdfReader  # type: ignore[import-not-found]
                reader = PdfReader(io.BytesIO(data))
                text = "\n".join((page.extract_text() or "") for page in reader.pages)
            except ImportError:
                text = ""
    except Exception as exc:  # noqa: BLE001 — a file whose text cannot be read is still kept
        logging.getLogger("ave").info("no text read from %s: %s", name, exc)
        text = ""
    return text[:MAX_FILE_TEXT]


@app.post("/projects/{project_id}/files", status_code=201)
async def add_folder_file(project_id: str, file: UploadFile = File(...), owner: str = Depends(current_owner)) -> dict:
    """Add a reference file (a brief, a script, notes). Its text is kept so
    Voltage can search it."""
    _owned_project(project_id, owner)
    name = Path(file.filename or "file").name
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="That file is too large (20 MB at most).")
    if not data:
        raise HTTPException(status_code=422, detail="That file is empty.")
    import hashlib
    sha256 = hashlib.sha256(data).hexdigest()
    folder = _files_dir(project_id)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / sha256
    if not dest.exists():
        tmp = dest.with_name(f"{sha256}.tmp")
        tmp.write_bytes(data)
        tmp.replace(dest)
    entry = {"name": name, "sha256": sha256, "size": len(data), "kind": Path(name).suffix.lstrip(".").lower() or "file",
             "at": _now(), "text": _extract_text(name, data)}
    _set_project_files(project_id, [*(f for f in _project_files(project_id) if f["sha256"] != sha256), entry])
    return _file_dict(entry)


@app.get("/projects/{project_id}/files/{sha256}")
def get_folder_file(project_id: str, sha256: str, owner: str = Depends(current_owner)) -> FileResponse:
    _owned_project(project_id, owner)
    entry = next((f for f in _project_files(project_id) if f["sha256"] == sha256), None)
    path = _files_dir(project_id) / sha256
    if entry is None or not path.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    import mimetypes
    media_type = mimetypes.guess_type(entry["name"])[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=entry["name"])


@app.delete("/projects/{project_id}/files/{sha256}", status_code=204)
def delete_folder_file(project_id: str, sha256: str, owner: str = Depends(current_owner)) -> Response:
    _owned_project(project_id, owner)
    files = _project_files(project_id)
    if not any(f["sha256"] == sha256 for f in files):
        raise HTTPException(status_code=404, detail="file not found")
    _set_project_files(project_id, [f for f in files if f["sha256"] != sha256])
    (_files_dir(project_id) / sha256).unlink(missing_ok=True)
    return Response(status_code=204)


# ── shared voices ──

def _made_voice_consent(made: dict) -> dict:
    """A voice Voltage made in a video: a speaker's clone carries that video's
    consent; a designed or library voice is nobody's, so it needs none."""
    if made.get("kind") != "cloned":
        return {"consent_granted_at": None, "consent_needed": False}
    record = repo.get(made.get("video_id") or made.get("project_id") or "")
    return {"consent_granted_at": record.consent.granted_at if record and record.consent else None, "consent_needed": True}


class ShareVoiceRequest(BaseModel):
    voice_id: str


@app.post("/projects/{project_id}/voices", status_code=201)
def share_voice(project_id: str, req: ShareVoiceRequest, owner: str = Depends(current_owner)) -> dict:
    """Share one of the caller's voices (their own, or one Voltage made in
    a video) into the project, so every video in it can speak in it."""
    _owned_project(project_id, owner)
    shared = _project_voices(project_id)
    if any(v["voice_id"] == req.voice_id for v in shared):
        raise HTTPException(status_code=409, detail="That voice is already shared in this project.")
    found = next((v for v in _my_voices(owner) if v["voice_id"] == req.voice_id), None)
    if found is not None:
        entry = {"voice_id": found["voice_id"], "name": found["name"], "kind": found.get("kind") or "recorded",
                 "description": found.get("description"), "sample_sha": found.get("sample_sha"), "at": _now(),
                 # The moment its owner's consent was given goes with it — never a boolean.
                 "consent_granted_at": found.get("consent_granted_at"), "consent_approximate": bool(found.get("consent_approximate"))}
    else:
        made = next((m for m in _made_voices_of(owner) if m["voice_id"] == req.voice_id), None)
        if made is None:
            raise HTTPException(status_code=404, detail="No such voice of yours.")
        entry = {"voice_id": made["voice_id"], "name": made["name"], "kind": made["kind"], "description": made.get("description"),
                 "sample_sha": None, "at": _now(), **_made_voice_consent(made)}
    _set_project_voices(project_id, [*shared, entry])
    getattr(voice, "register_clone", lambda vid: None)(entry["voice_id"])
    return _voice_entry(entry)


@app.delete("/projects/{project_id}/voices/{voice_id}", status_code=204)
def unshare_voice(project_id: str, voice_id: str, owner: str = Depends(current_owner)) -> Response:
    _owned_project(project_id, owner)
    shared = _project_voices(project_id)
    if not any(v["voice_id"] == voice_id for v in shared):
        raise HTTPException(status_code=404, detail="That voice is not shared in this project.")
    _set_project_voices(project_id, [v for v in shared if v["voice_id"] != voice_id])
    return Response(status_code=204)


# ── brief suggestions ──

def _suggestion_or_404(project_id: str, sid: str) -> list[dict]:
    items = _suggestions(project_id)
    if not any(i["id"] == sid for i in items):
        raise HTTPException(status_code=404, detail="suggestion not found")
    return items


@app.post("/projects/{project_id}/suggestions/{sid}/accept")
def accept_suggestion(project_id: str, sid: str, owner: str = Depends(current_owner)) -> dict:
    """Add the suggestion's words to the brief and drop the suggestion."""
    project = _owned_project(project_id, owner)
    items = _suggestion_or_404(project_id, sid)
    text = next(i["text"] for i in items if i["id"] == sid)
    brief = project.brief.rstrip()
    repo.update_project(project_id, brief=(brief + "\n" + text) if brief else text, by=owner)
    _set_suggestions(project_id, [i for i in items if i["id"] != sid])
    return _project_page(repo.get_project(project_id))


@app.post("/projects/{project_id}/suggestions/{sid}/dismiss")
def dismiss_suggestion(project_id: str, sid: str, owner: str = Depends(current_owner)) -> dict:
    _owned_project(project_id, owner)
    items = _suggestion_or_404(project_id, sid)
    _set_suggestions(project_id, [i for i in items if i["id"] != sid])
    return _project_page(repo.get_project(project_id))


# ── moving a video ──

class MoveVideoRequest(BaseModel):
    project_id: str | None = None
    # What to do with a project voice the video uses when it leaves: copy it
    # into the video's own voices, or keep it in the owner's.
    voice: Literal["copy", "keep"] | None = None


@app.patch("/videos/{project_id}")
def move_video(project_id: str, req: MoveVideoRequest, owner: str = Depends(current_owner)):
    """Move a video into a project, or out (`project_id` null). Its turns,
    takes and edits stay with it. Leaving a project whose voices its kept
    edits or ready proposals use needs `voice`: copy or keep; without it the
    answer is 409 naming the voices."""
    record = _owned(project_id, owner)
    target = _owned_project(req.project_id, owner) if req.project_id else None
    target_id = target.project_id if target else None
    leaving = record.folder_id if record.folder_id and record.folder_id != target_id else None
    if leaving:
        shared = {v["voice_id"]: v for v in _project_voices(leaving)}
        # A voice the destination shares too, or the video carries itself, needs no question.
        still = {v["voice_id"] for v in _project_voices(target_id)} if target_id else set()
        still |= {m["voice_id"] for m in repo.settings(project_id).get("made_voices") or []}
        going = [shared[v] for v in sorted(_voices_used_by(project_id)) if v in shared and v not in still]
        if going and req.voice is None:
            names = ", ".join(v["name"] for v in going)
            return JSONResponse(status_code=409, content={
                "detail": f"This video speaks in {names}, shared in the project it is leaving. Copy the voice into the video, or keep it in your voices.",
                "voices": [{"voice_id": v["voice_id"], "name": v["name"]} for v in going]})
        if going and req.voice == "copy":
            made = repo.settings(project_id).get("made_voices") or []
            have = {m["voice_id"] for m in made}
            made.extend({"voice_id": v["voice_id"], "name": v["name"], "kind": v.get("kind") or "designed", "at": _now(),
                         "description": v.get("description")} for v in going if v["voice_id"] not in have)
            repo.set_settings(project_id, made_voices=made)
        elif going and req.voice == "keep":
            mine = _my_voices(owner)
            have = {m["voice_id"] for m in mine}
            taken = {m["name"].lower() for m in mine}
            for v in going:
                if v["voice_id"] in have:
                    continue
                name = v["name"] if v["name"].lower() not in taken else f"{v['name']} ({repo.get_project(leaving).name})"
                mine.append({"voice_id": v["voice_id"], "name": name, "seconds": 0.0, "at": _now(), "kind": v.get("kind") or "designed",
                             "consent_granted_at": v.get("consent_granted_at"), "consent_approximate": bool(v.get("consent_approximate")),
                             "sample_sha": v.get("sample_sha"), "description": v.get("description"),
                             "source": {"project_id": leaving}})
                taken.add(name.lower())
            _set_my_voices(owner, mine)
    repo.set_folder(project_id, target_id)
    return _project_dict(repo.get(project_id))


@app.post("/videos/{project_id}/variants")
@app.post("/projects/{project_id}/variants", deprecated=True)
def create_variant(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """A variant (UX-3): the same clip as a new project, with the latest
    plan copied as a draft — every line planned again, nothing voiced — so
    another offer or another wording starts from the plan, not an upload."""
    record = _owned(project_id, owner)
    new_id = repo.next_id()
    path = artifacts.find(project_id, record.source.media.sha256)
    if path is None:
        raise HTTPException(status_code=409, detail="The original video is missing.")
    media = artifacts.put_file(new_id, path, kind="video", container=record.source.media.container,
                               duration=record.source.media.duration)
    source = replace(record.source, project_id=new_id, media=media)
    repo.create(source, record.transcript, record.consent, owner=owner, folder_id=record.folder_id)
    for s in repo.speakers(project_id):
        repo.set_speaker(new_id, s.label, name=s.name, voice_id=s.voice_id)
    # The original's settings carry over (its render does not: the variant has
    # not been rendered); the owner's defaults fill whatever it never set.
    saved = _starting_settings(owner, _folder_of(record)) | {k: v for k, v in repo.settings(project_id).items() if k not in ("reading", "render", "renders")} | {"variant_of": project_id}
    if "reading" in repo.settings(project_id):
        saved["reading"] = repo.settings(project_id)["reading"]
    repo.set_settings(new_id, **saved)
    plan = repo.latest_plan(project_id)
    if plan is not None:
        items = tuple(
            replace(i, status="planned" if i.kind == "planned" else "suggested", candidate_id=None, edit_id=None,
                    question=None, error=None, progress=None, fit=None, note=None)
            for i in plan.items if i.status != "dismissed"
        )
        draft = Plan(
            plan_id=repo.next_plan_id(new_id), project_id=new_id, goal=plan.goal, summary=plan.summary,
            items=items, mode=plan.mode, status="proposed", created_at=_now(), findings=plan.findings,
            estimate=_estimate(new_id, items),
        )
        repo.save_plan(draft)
        repo.append_log(new_id, draft.plan_id, f"Made as a variant of {record.source.filename}, with its plan as a draft")
    return _project_dict(repo.get(new_id))


@app.post("/videos/{project_id}/consent")
@app.post("/projects/{project_id}/consent", deprecated=True)
def grant_consent(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Confirm rights for a project uploaded without them.

    Lets a refused generation be recovered without re-uploading.
    """
    _owned(project_id, owner)
    recorded = repo.grant_consent(project_id, Consent(granted_at=_now()))
    return {"video_id": project_id, "consent_granted_at": recorded.granted_at if recorded else None}


@app.get("/videos/{project_id}/artifacts/{sha256}")
@app.get("/projects/{project_id}/artifacts/{sha256}", deprecated=True)
def get_artifact(project_id: str, sha256: str, owner: str = Depends(current_owner)) -> FileResponse:
    """Serve stored media by content address, with range requests.

    Scoped to the project so one project's id cannot be used to read another's
    media, and `sha256` is validated as a bare hex digest by the store.
    """
    _owned(project_id, owner)
    path = artifacts.find(project_id, sha256)
    if path is None:
        raise HTTPException(status_code=404, detail="artifact not found")
    return FileResponse(
        path,
        media_type=_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
    )


def _job_dict(job: Job) -> dict:
    return {
        "job_id": job.job_id,
        "kind": job.kind,
        "video_id": job.project_id,
        "status": job.status,
        "progress": round(job.progress, 3),
        "step": job.step,
        "attempts": job.attempts,
        "result": job.result,
        "error": job.error,
    }


def _meter(project_id: str, what: str):
    """Records a Claude call against the project, as `what` in the ledger."""
    def meter(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> None:
        ledger.record(project_id, "anthropic", what, input_tokens + output_tokens + cache_read + cache_write, "tokens",
                      claude_usd(model, input_tokens, output_tokens, cache_read, cache_write))
    return meter


def _voice_for(project_id: str, record: ProjectRecord, selection: Selection, requested: str,
               speaker: str | None = None) -> VoiceChoice:
    """The voice a line is spoken in (Phase 15a): the one picked for that
    speaker on purpose, else their own clone — made now if it is the first —
    else the voice asked for, with the reason it is not their own. `speaker`
    names who says it when that is not the selection's speaker (an added line)."""
    speaker = speaker or speaker_of(record.transcript, selection)
    return clones.resolve(project_id, record.source, record.transcript, speaker, requested)


# An added line can play over the picture only if the pause after its line
# can hold speech at all.
MIN_OVER_ROOM = 0.3


def _generate(
    project_id: str, record: ProjectRecord, candidate_id: str, selection: Selection,
    text: str, voice_id: str, fit: str | None, mix: str, report,
    delivery: str | None = None, voice_notes: tuple[str, ...] = (),
    voice_settings: dict | None = None, model: str | None = None, flex_max: float | None = None,
    max_regenerations: int | None = None, role: str | None = None, offset_db: float | None = None,
) -> EditCandidate:
    """One line through generation and continuity, saved as a candidate.
    A take that does not fit its slot raises SpanMismatch to the caller
    (Voltage, who decides on a shorter wording or another placement).

    "over" (UX-1): an added line plays *after* the selection, over the picture
    that follows — layered on the pause there, fitted to it. When the pause is
    too short to speak over, or the take cannot be fitted to it, the picture
    is held instead (concatenate), and the candidate says so."""
    if mix == "over":
        room = room_after(record.transcript, selection, record.source.duration)
        if room >= MIN_OVER_ROOM:
            window = Selection(selection.end, min(record.source.duration, selection.end + room))
            try:
                candidate = _generate(project_id, record, candidate_id, window, text, voice_id,
                                      None, "layer", report, delivery, voice_notes, voice_settings, model, flex_max,
                                      max_regenerations, role, offset_db)
            except SpanMismatch:
                candidate = None
            if candidate is not None:
                return candidate
            report(0.1, "No room to play over the picture; holding it instead")
        return _generate(project_id, record, candidate_id, selection, text, voice_id,
                         fit, "concatenate", report, delivery, voice_notes, voice_settings, model, flex_max,
                         max_regenerations, role, offset_db)
    plan = EditPlan(selection, text, voice_id, fit=fit, mix=mix, delivery=delivery,
                    voice_settings=voice_settings or None, model=model or None, flex_max=flex_max,
                    role=role if role in ROLES and role != "voice" else None, offset_db=offset_db or None)
    cost = voice.cost_of(plan)
    if not budget.can_afford(project_id, cost):
        raise BudgetExceeded(cost, budget.remaining(project_id))

    def generate(plan: EditPlan) -> EditCandidate:
        return run_edit(
            candidate_id, plan, record.source, voice, lipsync, continuity, report,
            transcript=record.transcript,
            max_regenerations=settings.max_regenerations if max_regenerations is None else max_regenerations,
            voice_notes=voice_notes, route=settings.voice_route,
        )

    # A take that does not fit its slot raises SpanMismatch to the caller:
    # Voltage hears why and decides (a shorter wording, another placement).
    candidate = generate(plan)
    # Retained so approval commits this exact candidate rather than re-running
    # generation, which real vendors would not reproduce byte-for-byte.
    repo.save_candidate(project_id, candidate)
    return candidate


def _held_take(
    project_id: str, record: ProjectRecord, candidate_id: str, selection: Selection,
    text: str, voice_id: str, fit: str | None, mix: str, report,
    delivery: str | None = None, voice_notes: tuple[str, ...] = (),
    voice_settings: dict | None = None, model: str | None = None, flex_max: float | None = None,
    max_regenerations: int | None = None, role: str | None = None, offset_db: float | None = None,
) -> EditCandidate | None:
    """p61: `_generate` from a take already paid for and held because it did
    not fit (the fit ladder's free rungs, and the eased take kept for the
    user). None when no such take is held, so nothing here is ever paid."""
    plan = EditPlan(selection, text, voice_id, fit=fit, mix=mix, delivery=delivery,
                    voice_settings=voice_settings or None, model=model or None, flex_max=flex_max)
    holds = getattr(voice, "holds", None)
    if holds is None or not holds(record.source, plan, record.transcript):
        return None
    return _generate(project_id, record, candidate_id, selection, text, voice_id, fit, mix, report, delivery, voice_notes,
                     voice_settings, model, flex_max, max_regenerations, role, offset_db)


# ── One processing model (2026-10-20): the user-facing jobs ─────────────────
#
# Every line voiced, voice made or cloned, mix change and render is an Activity
# job (app/jobs/activity.py). These are the seams the pipeline reports through;
# the editor reads GET /videos/{id}/jobs and the live channel.

# The pipeline's own step words, as a row and the status strip say them.
STEP_LABELS = (
    ("Synthesizing", "Voicing"), ("Take ", "Voicing again"), ("Checking continuity", "Checking fit"),
    ("Matching mouth", "Matching the picture"), ("No room to play over", "Holding the picture for it"),
)


def _job_label(step: str) -> str:
    for start, label in STEP_LABELS:
        if step.startswith(start):
            return label
    return step


class LineJobs:
    """The job hooks a tool reports through (Workbench.jobs)."""

    def claim(self, project_id: str, item_id: str, *, text: str, voice_name: str | None, params: dict) -> str:
        """The line's Job: the one the user's Go queued for this item, or a new one; running from here."""
        detail = {"text": text, "voice_name": voice_name, "chars": len(text)}
        queued = activity.active_for_line(project_id, item_id)
        if queued is not None and queued.status == "queued":
            activity.update(queued.job_id, detail=detail, params=params)
            job_id = queued.job_id
        else:
            job_id = activity.create(project_id, "voice_line", turn_id=current_turn.get(), line_ids=[item_id],
                                     detail=detail, params=params).job_id
        activity.start(job_id, "Voicing")
        return job_id

    def begin(self, project_id: str, kind: str, label: str, *, detail: dict | None = None,
              line_ids: Sequence[str] = ()) -> str:
        job = activity.create(project_id, kind, turn_id=current_turn.get(), line_ids=line_ids, step_label=label,
                              detail=detail)
        activity.start(job.job_id, label)
        return job.job_id

    def step(self, job_id: str | None, label: str, progress: float | None = None) -> None:
        if job_id:
            activity.update(job_id, step_label=_job_label(label), progress=progress)

    def settle(self, job_id: str | None, *, ok: bool, cost: float | None = None, code: str | None = None,
               text: str | None = None, label: str | None = None) -> None:
        if not job_id:
            return
        job = activity.get(job_id)
        if ok:
            activity.finish(job_id, step_label=label or ("Ready to hear" if job and job.kind == "voice_line" else "Done"),
                            cost_usd=cost)
        elif code == "cancelled":
            activity.cancel(job_id, text or "Cancelled")
        else:
            activity.fail(job_id, code or "unknown", text, cost_usd=cost)


line_jobs = LineJobs()


class CloneTrack:
    """A speaker's clone, made the first time a line needs it, as a Job."""

    def __init__(self, project_id: str, who: str) -> None:
        self.who = who
        self.job_id = line_jobs.begin(project_id, "clone", f"Cloning {who}'s voice", detail={"voice_name": who})

    def done(self) -> None:
        activity.finish(self.job_id, step_label=f"{self.who[0].upper() + self.who[1:]}'s voice is ready")

    def fail(self, text: str) -> None:
        activity.fail(self.job_id, "vendor_failed", text)


clones.tracker = CloneTrack


def _turn_running(project_id: str) -> bool:
    return any(j.kind == "turn" and j.project_id == project_id and not j.done for j in jobs.all())


def _turn_view(project_id: str) -> dict | None:
    """The last turn, as the editor shows it. A turn the server lost (a
    restart mid-turn) reads as failed, never running forever."""
    view = repo.settings(project_id).get("turn_view")
    if view and view.get("status") in ("running", "stopping") and not _turn_running(project_id):
        view = _set_turn(project_id, status="failed", step="Interrupted", finished_at=_now())
    return view


def _set_turn(project_id: str, **changes) -> dict:
    view = {**(repo.settings(project_id).get("turn_view") or {}), **changes}
    repo.set_settings(project_id, turn_view=view)
    events.publish(project_id, "turn.updated", view)
    return view


# The turns the user asked to stop (by turn id); the agent loop checks between steps.
_stops: set[str] = set()


def _cancel_leftovers(project_id: str, turn_id: str, why: str = "Not voiced this turn") -> int:
    n = 0
    for job in activity.of_turn(project_id, turn_id):
        if job.status == "queued":
            activity.cancel(job.job_id, why)
            n += 1
    return n


def _queue_lines(project_id: str, plan_id: str, turn_id: str) -> list[str]:
    """The user's Go: every planned line not voiced yet is queued at once, so
    each row says Queued before the first take starts."""
    plan = repo.get_plan(project_id, plan_id)
    out = []
    for item in (plan.items if plan else ()):
        if item.kind != "planned" or not item.enabled or item.status != "planned":
            continue
        if activity.active_for_line(project_id, item.item_id) is not None:
            continue
        activity.create(project_id, "voice_line", turn_id=turn_id, line_ids=[item.item_id],
                        detail={"text": item.new_text, "voice_name": None, "chars": len(item.new_text)})
        out.append(item.item_id)
    return out


def _retry_line(project_id: str, job_id: str) -> None:
    """A failed line voiced again with the same words and voice, outside a
    turn: the same pipeline, the same item, the same job flow."""
    job = activity.get(job_id)
    if job is None or job.done:
        return
    p = job.params or {}
    item_id = job.line_ids[0]
    plan_id = p.get("plan_id")
    record = repo.get(project_id)
    activity.start(job_id, "Voicing")
    attempt = repo.begin_attempt(project_id, plan_id, item_id, error=None)
    before = ledger.spent_usd(project_id)
    selection = Selection(*p["selection"])

    def report(progress: float, step: str) -> None:
        activity.update(job_id, step_label=_job_label(step), progress=progress)
        repo.update_item(project_id, plan_id, item_id, progress=step)

    def failed(code: str, reason: str) -> None:
        repo.finish_attempt(project_id, plan_id, item_id, attempt, error=reason)
        activity.fail(job_id, code, reason, cost_usd=max(0.0, ledger.spent_usd(project_id) - before))

    try:
        _ensure_spend(project_id)
        candidate = _generate(
            project_id, record, repo.next_candidate_id(project_id), selection, p["text"], p["voice_id"],
            p.get("fit"), p.get("mix") or "replace", report, delivery=p.get("delivery"),
            voice_notes=tuple(p.get("voice_notes") or ()), voice_settings=p.get("voice_settings"), model=p.get("model"),
            flex_max=p.get("flex_max"), max_regenerations=0, role=p.get("role"), offset_db=p.get("offset_db"),
        )
    except SpanMismatch as exc:
        needs = getattr(exc, "natural", None)
        has = selection.end - selection.start
        failed("too_long", f"Too long for its gap: needs {needs:.1f} s, has {has:.1f} s." if needs else str(exc))
        return
    except (BudgetExceeded, SpendCeilingReached) as exc:
        failed("budget", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - the row shows why; nothing stays Voicing
        log.warning("retry %s failed: %s", job_id, exc)
        failed("vendor_failed", str(exc) or "The take could not be made.")
        return
    repo.finish_attempt(project_id, plan_id, item_id, attempt, candidate_id=candidate.candidate_id,
                        fit=candidate.plan.fit, note=None, fit_failure=None)
    activity.finish(job_id, step_label="Ready to hear", cost_usd=max(0.0, ledger.spent_usd(project_id) - before))


def _in_background(project_id: str, job_id: str, work) -> None:
    """Run `work` on the work pool; a crash fails its job instead of leaving it running."""
    def run() -> None:
        try:
            work()
        except Exception as exc:  # noqa: BLE001
            log.exception("background job %s crashed", job_id)
            activity.fail(job_id, "unknown", str(exc) or "Something went wrong.")
    work_pool.submit(run)


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dict(job)


@app.post("/videos/{project_id}/edits")
@app.post("/projects/{project_id}/edits", deprecated=True)
def approve_edit(
    project_id: str, req: ApproveRequest, owner: str = Depends(current_owner),
) -> dict:
    _owned(project_id, owner)
    candidate = repo.get_candidate(project_id, req.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    overridden = not candidate.continuity.passed
    if overridden and not req.override:
        raise HTTPException(status_code=422, detail="continuity check failed")
    edit_id = _approve_candidate(project_id, candidate, overridden)
    return {
        "edit_id": edit_id,
        "candidate_id": candidate.candidate_id,
        "overridden": overridden,
        "continuity": _continuity_dict(candidate.continuity),
        "speaker": _speakers_by_take(project_id).get(candidate.candidate_id),
        "voice_profile_id": _voice_of(candidate.plan),
    }


def _approve_candidate(project_id: str, candidate: EditCandidate, overridden: bool, partner: str | None = None) -> str:
    """Commit a previewed candidate as an approved edit; a plan item that
    produced it is marked approved too."""
    edit_id = f"e{len(repo.list_edits(project_id)) + 1}"
    repo.append_edit(project_id, ApprovedEdit(
        edit_id=edit_id,
        candidate_id=candidate.candidate_id,
        plan=candidate.plan,
        audio=candidate.audio,
        frames=candidate.frames,
        overridden=overridden,
        partner=partner,
    ))
    plan = repo.latest_plan(project_id)
    if plan is not None:
        for item in plan.items:
            if item.candidate_id == candidate.candidate_id:
                repo.update_item(project_id, plan.plan_id, item.item_id, status="approved", edit_id=edit_id,
                                 note=None if item.note == TAKEN_OUT else item.note)
    return edit_id


@app.post("/videos/{project_id}/edits/{edit_id}/revert")
@app.post("/projects/{project_id}/edits/{edit_id}/revert", deprecated=True)
def revert_edit(project_id: str, edit_id: str, owner: str = Depends(current_owner)) -> dict:
    """Undo an approved edit (Phase 12). The edit is kept and marked, so
    nothing is lost; the render skips it and the transcript shows the line as
    shot. Reverting again is harmless."""
    _owned(project_id, owner)
    if not _revert(project_id, edit_id):
        raise HTTPException(status_code=404, detail="edit not found")
    return {"edit_id": edit_id, "reverted": True}


# 20h: what a row says once its line was taken out of the video (it stands as a proposal again).
TAKEN_OUT = "Taken out of the video. Add it puts it back; Discard drops it for good."


def _revert(project_id: str, edit_id: str, by: str = "You") -> bool:
    """Undo an approved edit; False when there is no such edit."""
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id), None)
    if edit is None or not repo.revert_edit(project_id, edit_id):
        return False
    # A shifted line is two edits; undoing one undoes the other.
    if edit.partner:
        repo.revert_edit(project_id, edit.partner)
    # One processing model: taking a line out is a change to the mix; the render that follows is its own job.
    activity.instant(project_id, "mix", "Took the line out", turn_id=current_turn.get(),
                     line_ids=[edit_id, *([edit.partner] if edit.partner else [])], detail={"edit_id": edit_id})
    # A shipped plan line goes back to a draft (ready, with its take), so the
    # review shows it held rather than shipped (UX-3).
    plan = repo.latest_plan(project_id)
    if plan is not None:
        for item in plan.items:
            if item.edit_id == edit_id and item.status == "approved":
                repo.update_item(project_id, plan.plan_id, item.item_id, status="ready", edit_id=None,
                                 note=TAKEN_OUT)
                repo.append_log(project_id, plan.plan_id, f"{by} undid the line at {_clock(item.selection.start)}")
    return True


class ExportRequest(BaseModel):
    # Bug 1 (2026-10-19): the client's own id for this request, echoed back, so it can keep only the latest.
    request_id: int | None = None
    # 20e: render the proposed takes too (the plan's ready items), so the user
    # can play the video with what is waiting for their Add it.
    with_proposals: bool = False
    # 2026-10-20: "export" from the Export page; the editor's preview otherwise.
    purpose: Literal["preview", "export"] = "preview"


@app.post("/videos/{project_id}/export")
@app.post("/projects/{project_id}/export", deprecated=True)
def export_project(project_id: str, req: ExportRequest | None = None, owner: str = Depends(current_owner)) -> dict:
    out = _export(_owned(project_id, owner), proposals=bool(req and req.with_proposals), request_id=req.request_id if req else None,
                  purpose=req.purpose if req else "preview")
    return {**out, "request_id": req.request_id if req else None}


@app.get("/videos/{project_id}/renders/latest")
def latest_render(project_id: str, mode: Literal["final", "proposals"] = "final", owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return _latest_render(project_id, mode)


class RenderRequest(BaseModel):
    mode: Literal["final", "proposals"] = "final"


@app.post("/videos/{project_id}/renders", status_code=202)
def start_render(project_id: str, req: RenderRequest, owner: str = Depends(current_owner)) -> dict:
    """A preview render in the background ("Render now"): the job comes back at once."""
    _owned(project_id, owner)
    job = activity.create(project_id, "render_preview", turn_id=None, detail={"mode": req.mode})
    _in_background(project_id, job.job_id,
                   lambda: _export(repo.get(project_id), proposals=req.mode == "proposals", job_id=job.job_id))
    return job.to_dict()


@app.get("/videos/{project_id}/renders")
def render_state(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Where each mode's render stands against the edits as they are now:
    the edit-set hash, and the finished render for it (or null)."""
    _owned(project_id, owner)
    return {mode: _render_status(project_id, mode) for mode in ("final", "proposals")}


def _proposal_edits(project_id: str) -> list[tuple[str, ApprovedEdit]]:
    """The plan's proposed takes as edits a render can carry, for a preview:
    nothing is approved, nothing is stored."""
    plan = repo.latest_plan(project_id)
    out: list[tuple[str, ApprovedEdit]] = []
    for item in (plan.items if plan else ()):
        if item.kind != "planned" or item.status != "ready" or not item.candidate_id:
            continue
        candidate = repo.get_candidate(project_id, item.candidate_id)
        if candidate is None:
            continue
        out.append((item.item_id, ApprovedEdit(
            edit_id=f"preview-{item.item_id}", candidate_id=candidate.candidate_id, plan=candidate.plan,
            audio=candidate.audio, frames=candidate.frames, overridden=not candidate.continuity.passed,
        )))
    return out


def _cuts(project_id: str, record: ProjectRecord) -> list[float]:
    """Where the picture cuts (Phase 16), found once and kept with the project."""
    saved = repo.settings(project_id).get("shots")
    if saved and saved.get("sha") == record.source.media.sha256:
        return [float(c) for c in saved.get("cuts", ())]
    found = shots.cuts(record.source.media.path)
    repo.set_settings(project_id, shots={"sha": record.source.media.sha256, "cuts": found})
    return found


def _pieces(record: ProjectRecord, manifest, edits: list[ApprovedEdit]) -> list[retime.Piece]:
    """The export as pieces (Phase 16): flexed lines, living holds for added
    lines, copies between. The picture's motion steers where time is added."""
    source = record.source
    motion_fn = lambda a, b: motion.motion(source.media.path, a, b)   # noqa: E731
    flexed = retime.flex_pieces(edits, motion_fn, settings.max_flex)
    living = retime.living_pieces(
        manifest.inserts, record.transcript, source.duration,
        _cuts(source.project_id, record) if manifest.inserts else (), motion_fn, settings.max_living,
        taken=[(p.start, p.end) for p in flexed],
    )
    return retime.tile(source.duration, [*flexed, *living], ffmpeg.frame_rate(source.media.path))


def _stems(record: ProjectRecord, manifest):
    """The original's voice apart from its music and room (Phase 15c), so an
    edited line can sit over the bed that was always there. Only when something
    is edited, only when the optional model is installed, and kept per source."""
    if not settings.stems or not stems_module.available():
        return None
    if not any(s.kind == "edited" for s in manifest.segments):
        return None
    with tempfile.TemporaryDirectory() as tmp:
        wav, _ = ffmpeg.extract_audio(record.source.media.path, Path(tmp) / "source.wav", sample_rate=44100)
        return stems_module.separate(wav, artifacts.root / record.source.project_id / "stems")


def _segments_with_layers(manifest) -> list[dict]:
    """The export bar's strip: every stretch, edited where a replacement or a
    layer plays (20h). The manifest keeps layers out of its segments so they
    can mix; here they only colour the strip."""
    out = [{"start": s.start, "end": s.end, "kind": s.kind, "ref": s.ref,
            "artifact": _artifact_dict(s.artifact) if s.artifact else None} for s in manifest.segments]
    for e in manifest.layers:
        start, end = e.plan.selection.start, e.plan.selection.end
        tiled = []
        for seg in out:
            if seg["end"] <= start or seg["start"] >= end or seg["kind"] == "edited":
                tiled.append(seg)
                continue
            if seg["start"] < start:
                tiled.append({**seg, "end": start})
            tiled.append({"start": max(seg["start"], start), "end": min(seg["end"], end), "kind": "edited",
                          "ref": e.frames.sha256, "artifact": _artifact_dict(e.frames)})
            if seg["end"] > end:
                tiled.append({**seg, "start": end})
        out = sorted(tiled, key=lambda s: s["start"])
    return out


# ── Bug 1 (2026-10-19): every render is keyed by (video, mode, edit set) ─────
# An identical request reuses the finished artifact; a changed edit set always
# renders anew; two requests for the same key share one render (single
# flight); one video renders one thing at a time. Each render is logged with
# its key, its artifact and its times.

render_log = logging.getLogger("voltage.render")
_render_locks: dict[str, threading.Lock] = {}
_render_locks_guard = threading.Lock()
RENDERS_KEPT = 12


def _lock_for(key: str) -> threading.Lock:
    with _render_locks_guard:
        return _render_locks.setdefault(key, threading.Lock())


def _render_edits(project_id: str, proposals: bool) -> tuple[list[ApprovedEdit], list[tuple[str, ApprovedEdit]]]:
    record = repo.get(project_id)
    edits = [e for e in repo.list_edits(project_id) if not e.reverted]
    previewed = _proposal_edits(project_id) if proposals else []
    return _arranged_edits(project_id, record, edits + [e for _, e in previewed]), previewed


def edit_set_hash(record: ProjectRecord, edits: Sequence[ApprovedEdit], mode: str) -> str:
    """What a render is built from, as a hash: the source, the mode, and
    every edit's take, place, mix and level. Ids alone are not enough — a
    moved or releveled take keeps its candidate but changes the sound."""
    parts = [{
        "audio": e.audio.sha256, "start": round(e.plan.selection.start, 3), "end": round(e.plan.selection.end, 3),
        "mix": e.plan.mix, "role": e.plan.role, "offset": e.plan.offset_db, "flex": getattr(e.plan, "flex", None), "fit": e.plan.fit,
        "text": e.plan.new_text,
    } for e in edits]
    body = json.dumps({"source": record.source.media.sha256, "mode": mode,
                       "mix": asdict(_mix_settings(record.source.project_id)),
                       "edits": sorted(parts, key=lambda p: (p["start"], p["audio"]))}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:16]


def _render_status(project_id: str, mode: str) -> dict:
    record = repo.get(project_id)
    edits, _ = _render_edits(project_id, mode == "proposals")
    h = edit_set_hash(record, edits, mode)
    done = (repo.settings(project_id).get("renders") or {}).get(h)
    in_flight = _lock_for(f"{project_id}:{h}").locked()
    return {"edit_hash": h, "render": done["render"] if done else None, "at": done["at"] if done else None,
            "rendering": in_flight and done is None, "edits": len(edits),
            "mix": (done.get("manifest") or {}).get("mix") if done else repo.settings(project_id).get("mix_report")}


# One processing model (2026-10-20): every render is a version the user can
# name. A version number is given once per edit set (v1, v2...): the same edit
# set rendered again is the same version; a render id names each render run.
_rendering: dict[str, dict] = {}          # video id -> the render running now
_versions_guard = threading.Lock()


def _version_for(project_id: str, h: str) -> int:
    with _versions_guard:
        versions = dict(repo.settings(project_id).get("render_versions") or {})
        if h not in versions:
            versions[h] = max(versions.values(), default=0) + 1
            repo.set_settings(project_id, render_versions=versions)
        return int(versions[h])


def _next_render_id(project_id: str) -> str:
    with _versions_guard:
        n = int(repo.settings(project_id).get("render_seq") or 0) + 1
        repo.set_settings(project_id, render_seq=n)
        return f"r{n}"


def _includes(edits: Sequence[ApprovedEdit], previewed: Sequence[tuple[str, ApprovedEdit]]) -> dict:
    """The takes a render carries: kept edits by edit id, proposals by item id."""
    preview_ids = {e.edit_id for _, e in previewed}
    return {"candidate_ids": sorted({e.candidate_id for e in edits if e.candidate_id}),
            "edit_ids": sorted(e.edit_id for e in edits if e.edit_id not in preview_ids),
            "item_ids": [item_id for item_id, _ in previewed]}


def _latest_render(project_id: str, mode: str) -> dict:
    """RenderState: the latest finished render of a mode, any render of it in
    progress, and whether the edit set has moved past the latest."""
    record = repo.get(project_id)
    edits, previewed = _render_edits(project_id, mode == "proposals")
    current = edit_set_hash(record, edits, mode)
    renders = repo.settings(project_id).get("renders") or {}
    mine = [(h, r) for h, r in renders.items() if r.get("mode") == mode and artifacts.find(project_id, r["render"]["sha256"]) is not None]
    latest = None
    if mine:
        h, r = max(mine, key=lambda hr: hr[1]["at"])
        latest = {"render_id": r.get("render_id"), "version": r.get("version") or _version_for(project_id, h),
                  "edit_set_hash": h, "created_at": r["at"], "mode": mode, "render": r["render"],
                  "manifest": {**r["manifest"], "edit_hash": h, "mode": mode}, "includes": r.get("includes")}
    running = _rendering.get(project_id)
    in_progress = None
    if running and running["mode"] == mode:
        job = activity.get(running["job_id"])
        in_progress = {**{k: running[k] for k in ("render_id", "version", "edit_set_hash", "started_at", "job_id", "includes")},
                       "eta_s": job.eta_s() if job else None}
    stale = (in_progress is None and (latest["edit_set_hash"] if latest else None) != current
             and (latest is not None or bool(edits) or bool(previewed)))
    return {"mode": mode, "current_hash": current, "latest": latest, "in_progress": in_progress, "stale": stale}


def _tell_render(project_id: str, mode: str) -> None:
    if events.listeners(project_id):
        try:
            events.publish(project_id, "render.updated", _latest_render(project_id, mode))
        except Exception:  # noqa: BLE001 - news, never the work
            log.exception("render.updated for %s", project_id)


def _export(record: ProjectRecord, proposals: bool = False, request_id: int | None = None,
            purpose: str = "preview", job_id: str | None = None) -> dict:
    project_id = record.source.project_id
    mode = "proposals" if proposals else "final"
    kind = "export" if purpose == "export" else "render_preview"
    edits, previewed = _render_edits(project_id, proposals)
    h = edit_set_hash(record, edits, mode)
    key = f"{project_id}:{h}"
    includes = _includes(edits, previewed)
    started = time.time()
    render_log.info("render request video=%s mode=%s hash=%s request=%s edits=%d", project_id, mode, h, request_id, len(edits))
    # Same key in flight: wait for it and take its artifact. Another key for this video: wait our turn.
    with _lock_for(key), _lock_for(f"{project_id}:video"):
        done = (repo.settings(project_id).get("renders") or {}).get(h)
        if done is not None and artifacts.find(project_id, done["render"]["sha256"]) is not None:
            render_log.info("render reuse video=%s mode=%s hash=%s sha=%s request=%s", project_id, mode, h, done["render"]["sha256"][:12], request_id)
            if not proposals:
                repo.set_settings(project_id, render={**done["record"], "at": done["at"]}, mix_report=done["manifest"].get("mix"))
            version = done.get("version") or _version_for(project_id, h)
            if job_id:
                activity.start(job_id, f"v{version} is up to date")
                activity.finish(job_id, step_label=f"v{version} ready", detail={"version": version, "mode": mode})
            return {**done["manifest"], "edit_hash": h, "mode": mode, "cached": True, "render_id": done.get("render_id"),
                    "version": version, "includes": done.get("includes") or includes}
        version = _version_for(project_id, h)
        render_id = _next_render_id(project_id)
        word = "export" if kind == "export" else "preview"
        detail = {"version": version, "mode": mode, "render_id": render_id, "includes": includes}
        line_ids = [*includes["item_ids"], *includes["edit_ids"]]
        if job_id:
            activity.update(job_id, detail=detail, line_ids=line_ids)
        else:
            job_id = activity.create(project_id, kind, turn_id=current_turn.get(), line_ids=line_ids, detail=detail).job_id
        activity.start(job_id, f"Rendering {word} v{version}")
        _rendering[project_id] = {"render_id": render_id, "version": version, "edit_set_hash": h, "mode": mode,
                                  "started_at": _now(), "job_id": job_id, "includes": includes}
        _tell_render(project_id, mode)
        try:
            out = _render_now(record, edits, previewed, proposals)
        except Exception as exc:
            activity.fail(job_id, "render_failed", f"The render failed: {exc}")
            raise
        finally:
            _rendering.pop(project_id, None)
        at = _now()
        record_ = {"sha256": out["render"]["sha256"], "duration": out["render"]["duration"],
                   "filename": f"{Path(record.source.filename).stem}-voltage.mp4"}
        if not proposals:
            # The latest finished render, for the Export page's receipt; a preview
            # with proposals in it is not the video the user takes away.
            repo.set_settings(project_id, render={**record_, "at": at, "edit_hash": h}, mix_report=out.get("mix"))
        renders = dict(repo.settings(project_id).get("renders") or {})
        renders[h] = {"mode": mode, "at": at, "render": out["render"], "record": record_, "manifest": out,
                      "render_id": render_id, "version": version, "includes": includes}
        if len(renders) > RENDERS_KEPT:
            for old in sorted(renders, key=lambda k: renders[k]["at"])[: len(renders) - RENDERS_KEPT]:
                renders.pop(old)
        repo.set_settings(project_id, renders=renders)
        activity.finish(job_id, step_label=f"v{version} ready")
        _tell_render(project_id, mode)
        render_log.info("render done video=%s mode=%s hash=%s sha=%s request=%s seconds=%.1f",
                        project_id, mode, h, out["render"]["sha256"][:12], request_id, time.time() - started)
        return {**out, "edit_hash": h, "mode": mode, "cached": False, "render_id": render_id, "version": version,
                "includes": includes}


def _render_now(record: ProjectRecord, edits: list[ApprovedEdit], previewed: list[tuple[str, ApprovedEdit]], proposals: bool) -> dict:
    project_id = record.source.project_id
    mixed: dict = {}
    manifest = render(record.source, edits)
    pieces = _pieces(record, manifest, edits)
    # Synchronous: with nothing but copies the video is stream-copied and only
    # the audio re-encoded, so even a 3-minute source renders in seconds; a
    # flexed or living piece re-encodes the picture.
    with tempfile.TemporaryDirectory() as tmp:
        path = compose(
            record.source, manifest.segments, Path(tmp) / "export.mp4",
            inserts=manifest.inserts, pieces=pieces, interpolator=settings.interpolator,
            stems=_stems(record, manifest), layers=manifest.layers,
            mix_settings=_mix_settings(project_id), words=_speech_spans(record, edits),
            lines=[(st.start, st.end) for st in statements_of(record.transcript)], on_mix=mixed.update,
        )
        rendered = artifacts.put_file(
            project_id, path, kind="video", container="mp4",
            duration=ffmpeg.duration_of(path),
        )
    held_at = {p.start: p.out for p in pieces if p.kind == "hold"}
    return {
        "render": _artifact_dict(rendered),
        # 2026-10-20: what the mix did with every added line (role, level, how
        # far a bed sits under the voices, whether each voice is heard) and the
        # loudness the whole render landed on.
        "mix": _mix_report(mixed, previewed),
        # 20e: the proposals this render carries (none for the final).
        "proposals": [item_id for item_id, _ in previewed],
        # Phase 16: every stretch of the output and where it came from.
        "pieces": retime.manifest(pieces),
        # The strip's view: a layered span counts as edited too (the manifest keeps layers apart so they mix).
        "segments": _segments_with_layers(manifest),
        "layers": [
            {"edit_id": e.edit_id, "start": e.plan.selection.start, "end": e.plan.selection.end, "role": role_of(e.plan), "offset_db": e.plan.offset_db}
            for e in manifest.layers
        ],
        "inserts": [
            {"at": i.at, "duration": i.duration, "artifact": _artifact_dict(i.edit.audio),
             "held": round(held_at.get(round(min(max(i.at, 0.0), record.source.duration) * ffmpeg.frame_rate(record.source.media.path)) / ffmpeg.frame_rate(record.source.media.path), 0.0), 3)}
            for i in manifest.inserts
        ],
    }


# ── Volt: the Export page's receipt ──────────────────────────────────────────

def _voice_words(project_id: str, owner: str, voice_id: str | None) -> str | None:
    """Whose voice a take is in, as the user knows it: "Sarah's voice",
    "Priya's own voice". None for a voice no one can name (a moved line
    keeps the original speech)."""
    if not voice_id or voice_id in ("original", "none"):
        return None
    for v in [*_catalogue(), *_my_voices(owner), *(repo.settings(project_id).get("made_voices") or [])]:
        if v["voice_id"] == voice_id:
            return f"{v['name']}'s voice"
    names = {s.label: s.name for s in repo.speakers(project_id)}
    for key, clone in repo.clones(project_id).items():
        if clone == voice_id:
            return "the speaker's own voice" if key == ProjectRepository.WHOLE_CLIP else f"{names.get(key, 'Speaker ' + key)}'s own voice"
    return None


def _change_dict(project_id: str, owner: str, e: ApprovedEdit) -> dict:
    mix = e.plan.mix
    kind = "changed" if mix == "replace" else "removed" if mix == "remove" else "added"
    whose = _voice_words(project_id, owner, e.plan.voice_profile_id) if mix != "remove" else None
    if mix == "remove":
        note = "room tone in its place"
    elif mix == "replace":
        note = f"in {whose}" if whose else "said again"
    elif mix == "concatenate":
        note = f"{whose}, the picture makes room" if whose else "the picture makes room"
    else:
        note = f"{whose}, over the picture" if whose else "over the picture"
    return {"edit_id": e.edit_id, "start": e.plan.selection.start, "text": e.plan.new_text, "kind": kind, "note": note}


@app.get("/videos/{project_id}/receipt")
@app.get("/projects/{project_id}/receipt", deprecated=True)
def get_receipt(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """What the project took: the turns, the takes voiced, the money, each
    change in the video in time order, what is still a draft, and the latest
    render if there is one."""
    _owned(project_id, owner)
    live = sorted((e for e in repo.list_edits(project_id) if not e.reverted), key=lambda e: (e.plan.selection.start, e.edit_id))
    plan = repo.latest_plan(project_id)
    # A take is audio Voltage voiced: a removal is room tone, a shifted line is
    # the original speech, and a moved or releveled take is the same audio again.
    takes = {c.audio.sha256 for c in repo.candidates(project_id) if c.plan.mix != "remove" and c.plan.voice_profile_id != "original"}
    return {
        "turns": repo.count_steps(project_id, "Thinking"),
        "takes": len(takes),
        "spent_usd": round(ledger.spent_usd(project_id), 4),
        "changes": [_change_dict(project_id, owner, e) for e in live],
        "drafts": sum(1 for i in (plan.items if plan else ()) if i.kind == "planned" and i.status == "ready"),
        "render": repo.settings(project_id).get("render"),
    }


# ── Phase 13: the agent ──────────────────────────────────────────────────────

class PlanApproveRequest(BaseModel):
    items: list[str] | None = None
    override: bool = False


def _item_dict(project_id: str, item: PlanItem) -> dict:
    candidate = repo.get_candidate(project_id, item.candidate_id) if item.candidate_id else None
    return {
        "item_id": item.item_id,
        "selection": {"start": item.selection.start, "end": item.selection.end},
        "old_text": item.old_text,
        "new_text": item.new_text,
        "speaker": item.speaker,
        "mix": item.mix,
        "delivery": item.delivery,
        "reason": item.reason,
        "kind": item.kind,
        "enabled": item.enabled,
        "status": item.status,
        "fit": item.fit,
        "candidate": _candidate_dict(candidate) if candidate else None,
        "edit_id": item.edit_id,
        "question": item.question,
        "error": item.error,
        "note": item.note,
        "progress": item.progress,
        "fit_failure": item.fit_failure,
        "beat": item.beat,
    }


def _plan_dict(plan: Plan | None) -> dict | None:
    if plan is None:
        return None
    return {
        "type": "plan",
        "plan_id": plan.plan_id,
        "goal": plan.goal,
        "summary": plan.summary,
        "mode": plan.mode,
        "status": plan.status,
        "created_at": plan.created_at,
        "estimate": plan.estimate,
        "findings": list(plan.findings),
        "question": plan.question,
        # UX-5: the brief so far, and how many questions may still come.
        "answers": [list(a) for a in plan.answers],
        "voice": plan.voice,
        "voice_asked": plan.voice_asked,
        "voice_note": plan.voice_note,
        "spend_usd": round(ledger.spent_usd_since(plan.project_id, plan.created_at), 4) if plan.created_at else 0.0,
        # P-1: how many takes the plan voiced — the receipt shows what the ledger knows.
        "takes_voiced": ledger.calls_since(plan.project_id, VoiceBudget.VENDOR, plan.created_at) if plan.created_at else 0,
        "log": list(plan.log),
        "items": [_item_dict(plan.project_id, i) for i in plan.items],
    }


def _lines(record: ProjectRecord) -> list[Line]:
    names = {s.label: s.name for s in repo.speakers(record.source.project_id)}
    rates: dict[str | None, float] = {}
    out = []
    for i, st in enumerate(statements_of(record.transcript)):
        if st.speaker not in rates:
            rates[st.speaker] = speaking_rate(record.transcript, st.speaker)
        room = room_after(record.transcript, Selection(st.start, st.end), record.source.duration)
        out.append(Line(
            i + 1, st.start, st.end, names.get(st.speaker) if st.speaker else None, st.text,
            syllables=syllables(st.text),
            budget=syllable_budget(rates[st.speaker], st.end - st.start + min(room, 1.0)),
        ))
    return out


# A rough time per line, for the plan's estimate.
SECONDS_PER_ITEM = 12


def _estimate(project_id: str, items: tuple[PlanItem, ...]) -> dict:
    """What running the ticked items should cost: voice characters at the
    ledger's rate, and a rough time."""
    runnable = [i for i in items if i.kind == "planned" and i.enabled and i.status == "planned"]
    chars = sum(voice.cost_of(EditPlan(i.selection, i.new_text, getattr(voice, "default_voice", "speaker-1"))) for i in runnable)
    return {
        "items": len(runnable),
        "voice_characters": chars,
        "usd": round(chars * budget.usd_per_1k / 1000, 4),
        "seconds": SECONDS_PER_ITEM * len(runnable),
    }


def _voice_name(voice_id: str | None) -> str | None:
    if not voice_id:
        return None
    return next((v["name"] for v in _catalogue() if v["voice_id"] == voice_id), None)


def _catalogue() -> list[dict]:
    try:
        return list(voice.voices())
    except VendorError:
        return []


@app.get("/videos/{project_id}/plans/{plan_id}")
@app.get("/projects/{project_id}/plans/{plan_id}", deprecated=True)
def get_plan(project_id: str, plan_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return _plan_dict(_plan_or_404(project_id, plan_id))


def _plan_or_404(project_id: str, plan_id: str) -> Plan:
    plan = repo.get_plan(project_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@app.post("/videos/{project_id}/plans/{plan_id}/approve")
@app.post("/projects/{project_id}/plans/{plan_id}/approve", deprecated=True)
def approve_plan(
    project_id: str, plan_id: str, req: PlanApproveRequest, owner: str = Depends(current_owner),
) -> dict:
    """Approve every ready item (or the ones named) and render. An item whose
    take failed continuity is skipped unless `override` is set."""
    record = _owned(project_id, owner)
    _plan_or_404(project_id, plan_id)
    return _ship(project_id, record, plan_id, req.items, req.override)


NUMBER_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six", 7: "seven", 8: "eight", 9: "nine", 10: "ten"}


def _count_lines(n: int, every: bool) -> str:
    """"the line", "all four lines", "3 lines"."""
    if n == 1:
        return "the line"
    word = NUMBER_WORDS.get(n, str(n))
    return f"all {word} lines" if every else f"{word} lines"


def _resolve_question(project_id: str, plan_id: str, why: str, by: str = "editor") -> None:
    """A waiting question whose subject changed outside the chat (2026-10-20):
    it is kept, marked resolved with why, and stops waiting; the card turns
    quiet and the next turn starts from the new state, not a stale gate."""
    plan = repo.get_plan(project_id, plan_id)
    if plan is None or plan.status != "clarifying" or not plan.question or plan.question.get("resolved"):
        return
    resolved = {**plan.question, "resolved": {"why": why, "by": by, "at": _now()}}
    repo.update_plan(project_id, plan_id, status="proposed", question=resolved)
    repo.append_log(project_id, plan_id, f"The question resolved itself: {why}")


def _ship(project_id: str, record: ProjectRecord, plan_id: str, item_ids: list[str] | None,
          override: bool = False) -> dict:
    """Approve the ready items (or the ones named) and render."""
    plan = repo.get_plan(project_id, plan_id)
    approved, skipped = [], []
    for item in plan.items:
        if item.status != "ready" or (item_ids and item.item_id not in item_ids):
            continue
        candidate = repo.get_candidate(project_id, item.candidate_id or "")
        if candidate is None:
            skipped.append({"item_id": item.item_id, "reason": "no take to approve"})
            continue
        overridden = not candidate.continuity.passed
        if overridden and not override:
            skipped.append({"item_id": item.item_id, "reason": "continuity check failed"})
            continue
        edit_id = _approve_candidate(project_id, candidate, overridden)
        approved.append({"item_id": item.item_id, "edit_id": edit_id, "overridden": overridden,
                         "speaker": item.speaker, "voice_profile_id": _voice_of(candidate.plan)})
    if approved:
        repo.append_log(project_id, plan_id,
                        f"Approved {len(approved)} {'change' if len(approved) == 1 else 'changes'}")
        ready = [i for i in plan.items if i.status == "ready"]
        _resolve_question(project_id, plan_id, f"you added {_count_lines(len(approved), len(approved) == len(ready) and len(ready) > 1)}")
    export = _export(record) if approved else None
    if export:
        repo.append_log(project_id, plan_id, "Rendered the edited video",
                        f"${ledger.spent_usd(project_id):.2f} in total")
    return {
        "approved": approved, "skipped": skipped, "export": export,
        "plan": _plan_dict(repo.get_plan(project_id, plan_id)),
    }


# ── UX-1: remove a line ──────────────────────────────────────────────────────

class RemoveRequest(BaseModel):
    start: float
    end: float


def _room_tone(record: ProjectRecord, seconds: float) -> "np.ndarray":
    """The recording's own quiet, enough to fill `seconds`: the gaps between
    words, only their genuinely quiet frames, tiled. Silence when the
    recording has no quiet to offer."""
    import numpy as np
    from app.continuity import signals
    from app.continuity.measured import ROOM_BELOW_SPEECH_DB, _concat, gap_spans, quiet_part
    rate = signals.RATE
    want = max(1, int(seconds * rate))
    try:
        room = _concat(record.source.media.path, gap_spans(record.transcript, record.source.duration), rate=rate)
        if room is not None:
            audio = signals.load(record.source.media.path, rate=rate)
            level = signals.speech_level_db(audio)
            if level is not None:
                room = quiet_part(room, rate, level - ROOM_BELOW_SPEECH_DB)
    except Exception:  # noqa: BLE001 - room tone is a nicety; silence is the fallback
        room = None
    if room is None or room.size < rate // 10:
        return np.zeros(want, dtype=np.float32)
    reps = want // room.size + 1
    return np.tile(room, reps)[:want].astype(np.float32)


@app.post("/videos/{project_id}/lines/remove")
@app.post("/projects/{project_id}/lines/remove", deprecated=True)
def remove_line(project_id: str, req: RemoveRequest, owner: str = Depends(current_owner)) -> dict:
    """Take a line out (UX-1): its words go, the room's own sound stays in
    their place, the picture is untouched. Approved at once — nothing is
    voiced — and undone like any edit, with Revert."""
    record = _owned(project_id, owner)
    if not any(w.end > req.start and w.start < req.end for w in record.transcript.words):
        raise HTTPException(status_code=422, detail="Nothing is said there to remove.")
    out = _remove_words(project_id, record, Selection(req.start, req.end))
    repo.add_message(project_id, "user", f"Proposed removing the line at {_clock(out['selection']['start'])}")
    return out


def _remove_words(project_id: str, record: ProjectRecord, span: Selection) -> dict:
    """The words in `span` proposed removed (20e): a plan item, ready, whose
    take is the room's own sound; Add it (ship) makes it part of the video.
    Nothing is voiced. The agent's `remove_line` and the UX-1 route share it."""
    selection = snap_to_word_boundaries(record.transcript, span)
    candidate = _room_tone_candidate(project_id, record, selection)
    words = " ".join(w.text for w in record.transcript.words if w.end > selection.start and w.start < selection.end)
    plan = _turn_plan(project_id, "Remove a line")
    item = PlanItem(item_id=f"i{len(plan.items) + 1}", selection=selection, old_text=words, new_text="",
                    mix="remove", reason="Removed by hand", kind="planned", enabled=True, status="ready",
                    candidate_id=candidate.candidate_id)
    plan = repo.update_plan(project_id, plan.plan_id, items=plan.items + (item,))
    return {
        "item_id": item.item_id, "candidate_id": candidate.candidate_id,
        "selection": {"start": selection.start, "end": selection.end}, "mix": "remove",
        "plan": _plan_dict(plan),
    }


@app.post("/videos/{project_id}/plans/{plan_id}/items/{item_id}/dismiss")
@app.post("/projects/{project_id}/plans/{plan_id}/items/{item_id}/dismiss", deprecated=True)
def dismiss_item(project_id: str, plan_id: str, item_id: str, owner: str = Depends(current_owner)) -> dict:
    """Discard a proposal (20e): the line leaves the plan; a shipped one is
    taken out with Revert instead."""
    _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    item = plan.item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    if item.status == "approved":
        raise HTTPException(status_code=409, detail="That line is in the video; undo it instead.")
    plan = repo.update_item(project_id, plan_id, item_id, status="dismissed", enabled=False)
    repo.append_log(project_id, plan_id, f"You discarded the line at {_clock(item.selection.start)}")
    _resolve_question(project_id, plan_id, f"you discarded the line at {_clock(item.selection.start)}")
    return _plan_dict(repo.get_plan(project_id, plan_id))


@app.post("/videos/{project_id}/plans/{plan_id}/items/{item_id}/ease")
def ease_item(project_id: str, plan_id: str, item_id: str, owner: str = Depends(current_owner)) -> dict:
    """p61: a line that ran long, voiced already: use that take with the
    picture easing so it fits. The take was kept when the fit failed; nothing
    is voiced again and nothing is paid."""
    _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    item = plan.item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    failure = item.fit_failure or {}
    eased = failure.get("eased_candidate_id")
    candidate = repo.get_candidate(project_id, eased) if eased and item.status == "failed" else None
    if candidate is None:
        raise HTTPException(status_code=409, detail="There is no voiced take to ease in for this line. Ask Voltage to shorten it.")
    ease = failure.get("ease_s")
    sel = candidate.plan.selection
    repo.update_item(project_id, plan_id, item_id, status="ready", candidate_id=candidate.candidate_id, error=None,
                     fit_failure=None, selection=Selection(sel.start, sel.end),
                     note=f"The picture eases {ease:.1f} s so this take fits." if ease else None)
    repo.append_log(project_id, plan_id, f"You let the picture ease for the line at {_clock(item.selection.start)}")
    return _plan_dict(repo.get_plan(project_id, plan_id))


# ── UX-1c: shift a line of the original speech ──────────────────────────────

class ShiftRequest(BaseModel):
    start: float
    end: float
    # Where the words should start instead, in seconds of the source.
    to: float


def _room_tone_candidate(project_id: str, record: ProjectRecord, selection: Selection) -> EditCandidate:
    """The room's own sound in place of the words at `selection`."""
    length = selection.end - selection.start
    from app.continuity import signals
    from app.continuity.measured import _write_wav
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "room.wav"
        _write_wav(path, _room_tone(record, length), signals.RATE)
        audio = artifacts.put_file(project_id, path, kind="audio", container="wav", duration=length)
    candidate = EditCandidate(
        candidate_id=repo.next_candidate_id(project_id),
        plan=EditPlan(selection, "", "none", mix="remove"),
        audio=audio, frames=record.source.media,
        continuity=ContinuityReport(None, None, None, None, True, (), ()),
    )
    repo.save_candidate(project_id, candidate)
    return candidate


@app.post("/videos/{project_id}/lines/shift")
@app.post("/projects/{project_id}/lines/shift", deprecated=True)
def shift_line(project_id: str, req: ShiftRequest, owner: str = Depends(current_owner)) -> dict:
    """Move a line of the original speech to another time, as it was
    spoken: the line is pinned at `to` in the arrangement, its old place
    gets the room's sound, and the other lines flow around it."""
    record = _owned(project_id, owner)
    if not any(w.end > req.start and w.start < req.end for w in record.transcript.words):
        raise HTTPException(status_code=422, detail="Nothing is said there to move.")
    # 2026-10-19: a move is the arrangement's now: the line is pinned there and the others flow.
    return _pin_line(project_id, record, Selection(req.start, req.end), req.to)


# ── The arrangement (2026-10-19): the transcript's order is the playback order ──
#
# A move is not an edit any more. The video keeps one arrangement: the order
# of its spoken lines, the lines pinned to a time, the tightest pause, and how
# a run past the end is handled. Lines follow one another (`app.arrange`); a
# line that ends up somewhere else plays there, its old place filled with the
# room's own sound, and a replacement travels with its line. The render builds
# those edits from the arrangement each time, so there is one row per line and
# one undo per action.

ARRANGEMENT_HISTORY = 50
ARRANGE_RATE = 48000


def _arrangement(project_id: str) -> arrange.Arrangement:
    return arrange.Arrangement.from_dict(repo.settings(project_id).get("arrangement"))


def _arrangement_lines(record: ProjectRecord) -> list[arrange.LineSpec]:
    return arrange.specs(statements_of(record.transcript))


def _line_replacements(record: ProjectRecord, edits: Sequence[ApprovedEdit]) -> dict[str, ApprovedEdit]:
    """Each spoken line's replacement in the video, if it has one: the latest
    kept take that covers most of it. It moves with its line."""
    out: dict[str, ApprovedEdit] = {}
    sts = statements_of(record.transcript)
    for e in edits:
        if e.reverted or e.plan.mix != "replace":
            continue
        for i, st in enumerate(sts):
            span = st.end - st.start
            overlap = min(e.plan.selection.end, st.end) - max(e.plan.selection.start, st.start)
            if span > 0 and overlap >= 0.5 * span:
                out[f"L{i}"] = e
    return out


def _arrangement_audio(project_id: str, record: ProjectRecord, name: str, make) -> MediaArtifact:
    """A sound the arrangement needs (a line's own words, the room's sound
    for its old place, the tail that plays over a held last frame), made once
    and kept by name with the video."""
    cache = dict(repo.settings(project_id).get("arrangement_audio") or {})
    got = cache.get(name)
    if got is not None and artifacts.find(project_id, got["sha256"]) is not None:
        return MediaArtifact(**got)
    with tempfile.TemporaryDirectory() as tmp:
        path, seconds = make(Path(tmp))
        audio = artifacts.put_file(project_id, path, kind="audio", container="wav", duration=seconds)
    cache[name] = asdict(audio)
    repo.set_settings(project_id, arrangement_audio=cache)
    return audio


def _original_words(project_id: str, record: ProjectRecord, spec: arrange.LineSpec) -> MediaArtifact:
    def make(tmp: Path):
        return ffmpeg.extract_segment(record.source.media.path, tmp / "line.wav", spec.orig_start, spec.orig_end,
                                      sample_rate=ARRANGE_RATE)
    return _arrangement_audio(project_id, record, f"{spec.key}:words:{spec.orig_start:.3f}-{spec.orig_end:.3f}", make)


def _room_in_place_of(project_id: str, record: ProjectRecord, spec: arrange.LineSpec) -> MediaArtifact:
    def make(tmp: Path):
        from app.continuity import signals
        from app.continuity.measured import _write_wav
        seconds = spec.orig_end - spec.orig_start
        _write_wav(tmp / "room.wav", _room_tone(record, seconds), signals.RATE)
        return tmp / "room.wav", seconds
    return _arrangement_audio(project_id, record, f"{spec.key}:room:{spec.orig_start:.3f}-{spec.orig_end:.3f}", make)


def _tail_of(project_id: str, record: ProjectRecord, audio: MediaArtifact, offset: float) -> MediaArtifact:
    """The part of a take from `offset` on: what is still to be heard once the clip has ended."""
    def make(tmp: Path):
        return ffmpeg.extract_segment(audio.path, tmp / "tail.wav", offset, audio.duration, sample_rate=ARRANGE_RATE)
    return _arrangement_audio(project_id, record, f"tail:{audio.sha256[:16]}:{offset:.3f}", make)


def _placements(record: ProjectRecord, arrangement: arrange.Arrangement) -> list[arrange.Placed]:
    return arrange.place(_arrangement_lines(record), arrangement)


def _arranged_edits(project_id: str, record: ProjectRecord, edits: list[ApprovedEdit]) -> list[ApprovedEdit]:
    """The edits a render plays once the arrangement has had its say: every
    line that plays somewhere else becomes the room's sound at its old place
    and its words (or its replacement) at the new one. A run past the end is
    never cut silently: the last frame holds while the line finishes, unless
    the user chose to trim it."""
    _migrate_moves(project_id, record)
    arrangement = _arrangement(project_id)
    lines = _arrangement_lines(record)
    if arrangement.is_default([ln.key for ln in lines]):
        return edits
    placed = arrange.place(lines, arrangement)
    moved = [p for p in placed if p.moved]
    if not moved:
        return edits
    spec = {ln.key: ln for ln in lines}
    texts = {f"L{i}": st.text for i, st in enumerate(statements_of(record.transcript))}
    taken = _line_replacements(record, edits)
    dropped = {taken[p.key].edit_id for p in moved if p.key in taken}
    out = [e for e in edits if e.edit_id not in dropped]
    duration = record.source.duration
    for p in moved:
        ln = spec[p.key]
        out.append(ApprovedEdit(
            edit_id=f"arr-{p.key}-out", candidate_id="arrangement",
            plan=EditPlan(Selection(ln.orig_start, ln.orig_end), "", "none", mix="remove"),
            audio=_room_in_place_of(project_id, record, ln), frames=record.source.media,
        ))
        take = taken.get(p.key)
        audio = take.audio if take is not None else _original_words(project_id, record, ln)
        start = round(min(p.start, duration), 3)
        end = round(min(duration, p.start + audio.duration), 3)
        plan = (replace(take.plan, selection=Selection(start, end), mix="layer", fit="start", flex=None)
                if take is not None else
                EditPlan(Selection(start, end), texts.get(p.key, ""), "original", fit="start", mix="layer"))
        out.append(ApprovedEdit(edit_id=f"arr-{p.key}-in", candidate_id=take.candidate_id if take else "arrangement",
                                plan=plan, audio=audio, frames=record.source.media))
        past = p.start + audio.duration - duration
        if past > 0.01 and arrangement.end != "trim":
            # Let the picture ease: the last frame holds while the rest is heard.
            tail = _tail_of(project_id, record, audio, max(0.0, duration - p.start))
            out.append(ApprovedEdit(
                edit_id=f"arr-{p.key}-hold", candidate_id="arrangement",
                plan=EditPlan(Selection(duration, duration), texts.get(p.key, ""), "original", mix="concatenate"),
                audio=tail, frames=record.source.media,
            ))
    return out


def _arrangement_dict(project_id: str, record: ProjectRecord) -> dict:
    _migrate_moves(project_id, record)
    arrangement = _arrangement(project_id)
    lines = _arrangement_lines(record)
    placed = arrange.place(lines, arrangement)
    spec = {ln.key: ln for ln in lines}
    sts = statements_of(record.transcript)
    taken = _line_replacements(record, [e for e in repo.list_edits(project_id) if not e.reverted])
    duration = record.source.duration
    over = arrange.overrun(placed, duration)
    saved = repo.settings(project_id)
    return {
        "arrangement": arrangement.as_dict(),
        "duration": duration,
        "lines": [{
            "key": p.key, "index": int(p.key[1:]) + 1, "text": sts[int(p.key[1:])].text,
            "speaker": sts[int(p.key[1:])].speaker,
            "orig_start": spec[p.key].orig_start, "orig_end": spec[p.key].orig_end,
            "length": spec[p.key].length, "gap": spec[p.key].gap,
            "start": p.start, "end": p.end, "pinned": p.pinned, "pushed_after": p.pushed_after, "moved": p.moved,
            "replaced_by": taken[p.key].edit_id if p.key in taken else None,
        } for p in placed],
        "overrun": over,
        "ease_ok": 0 < over <= arrange.EASE_LIMIT_S,
        "min_gap_default": arrange.DEFAULT_MIN_GAP,
        "can_undo": bool(saved.get("arrangement_history")),
    }


def _save_arrangement(project_id: str, record: ProjectRecord, new: arrange.Arrangement, said: str | None) -> None:
    """One action, one undo: the arrangement before it is kept to go back to."""
    lines = _arrangement_lines(record)
    keys = {ln.key for ln in lines}
    conflict = arrange.pin_conflict(lines, new.pins)
    if conflict:
        raise HTTPException(status_code=422, detail=conflict)
    new = arrange.Arrangement(
        order=tuple(k for k in new.order if k in keys), pins={k: round(max(0.0, v), 3) for k, v in new.pins.items() if k in keys},
        min_gap=None if new.min_gap is None else round(max(0.0, float(new.min_gap)), 3),
        end=new.end if new.end in ("hold", "trim") else None,
    )
    old = _arrangement(project_id)
    if new == old:
        return
    history = list(repo.settings(project_id).get("arrangement_history") or [])[-(ARRANGEMENT_HISTORY - 1):]
    repo.set_settings(project_id, arrangement=new.as_dict(), arrangement_history=history + [old.as_dict()])
    if said:
        repo.add_message(project_id, "user", said)


def _arrangement_said(record: ProjectRecord, before: list[arrange.Placed], after: list[arrange.Placed]) -> str | None:
    """What the user did, in a sentence for the chat, so Voltage knows."""
    was = {p.key: p.start for p in before}
    changed = [p for p in after if abs(was.get(p.key, p.start) - p.start) > 0.005]
    if not changed:
        return None
    first = changed[0]
    line = int(first.key[1:]) + 1
    more = f", and {len(changed) - 1} more line{'s' if len(changed) > 2 else ''} follow" if len(changed) > 1 else ""
    return f"Moved line {line} to {_clock(first.start)}{more}"


def _migrate_moves(project_id: str, record: ProjectRecord) -> None:
    """Moves made before the arrangement (two-edit shifts, takes moved off
    their line) become the arrangement once, so each line has one row: the
    old edits are undone, a moved take goes back on its line, and the line
    is placed where it was moved to."""
    saved = repo.settings(project_id)
    if saved.get("arrangement_v1"):
        return
    edits = [e for e in repo.list_edits(project_id)]
    lines = _arrangement_lines(record)
    targets: dict[str, float] = {}

    def line_at(start: float, end: float) -> str | None:
        best, overlap = None, 0.0
        for ln in lines:
            o = min(end, ln.orig_end) - max(start, ln.orig_start)
            if o > overlap:
                best, overlap = ln.key, o
        return best

    live = [e for e in edits if not e.reverted]
    for e in live:
        if e.plan.mix == "layer" and e.partner:
            partner = next((x for x in edits if x.edit_id == e.partner), None)
            if partner is None or partner.plan.mix != "remove":
                continue
            key = line_at(partner.plan.selection.start, partner.plan.selection.end)
            if key is not None:
                targets[key] = e.plan.selection.start
                repo.revert_edit(project_id, e.edit_id)
                repo.revert_edit(project_id, partner.edit_id)
    for e in live:
        if e.plan.mix != "replace":
            continue
        cand = repo.get_candidate(project_id, e.candidate_id)
        if cand is None or not any(n.startswith("moved to") for n in cand.fit_notes):
            continue
        origin = next((x for x in edits if x.audio.sha256 == e.audio.sha256 and x.edit_id != e.edit_id
                       and (c := repo.get_candidate(project_id, x.candidate_id)) is not None
                       and not any(n.startswith("moved") for n in c.fit_notes)), None)
        if origin is None:
            continue
        key = line_at(origin.plan.selection.start, origin.plan.selection.end)
        if key is None:
            continue
        repo.revert_edit(project_id, e.edit_id)
        if origin.reverted:
            _approve_candidate(project_id, repo.get_candidate(project_id, origin.candidate_id), overridden=origin.overridden)
        targets.setdefault(key, e.plan.selection.start)
    arrangement = _arrangement(project_id)
    if targets:
        # As an order where that is enough, a pin only where it is not.
        order = [ln.key for ln in lines]
        for key, to in sorted(targets.items(), key=lambda kv: kv[1]):
            order.remove(key)
            at = next((i for i, k in enumerate(order) if next(ln for ln in lines if ln.key == k).orig_start >= to - 1e-6), len(order))
            order.insert(at, key)
        arrangement = arrange.Arrangement(order=tuple(order), pins=dict(arrangement.pins), min_gap=arrangement.min_gap, end=arrangement.end)
        placed = {p.key: p for p in arrange.place(lines, arrangement)}
        pins = dict(arrangement.pins)
        for key, to in targets.items():
            if abs(placed[key].start - to) > 0.05:
                pins[key] = round(to, 3)
        arrangement = arrange.Arrangement(order=arrangement.order, pins=pins, min_gap=arrangement.min_gap, end=arrangement.end)
        if arrange.pin_conflict(lines, arrangement.pins):
            arrangement = arrange.Arrangement(order=arrangement.order, min_gap=arrangement.min_gap, end=arrangement.end)
        render_log.info("arrangement migrated video=%s moved=%s", project_id, sorted(targets))
    repo.set_settings(project_id, arrangement=arrangement.as_dict(), arrangement_v1=True)


@app.get("/videos/{project_id}/arrangement")
def get_arrangement(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Where every spoken line plays, in playback order."""
    return _arrangement_dict(project_id, _owned(project_id, owner))


class ArrangementRequest(BaseModel):
    # The lines in playback order, by key ("L0" is the first spoken line).
    order: list[str] = []
    # Lines held at a time the user typed: key -> seconds.
    pins: dict[str, float] = {}
    # Tighten gaps: every pause at most this long; None keeps the original pauses.
    min_gap: float | None = None
    # A run past the end: "hold" lets the picture ease, "trim" fades the last line out.
    end: Literal["hold", "trim"] | None = None


@app.put("/videos/{project_id}/arrangement")
def put_arrangement(project_id: str, req: ArrangementRequest, owner: str = Depends(current_owner)) -> dict:
    """The whole arrangement, as one action (one undo)."""
    record = _owned(project_id, owner)
    _migrate_moves(project_id, record)
    before = _placements(record, _arrangement(project_id))
    new = arrange.Arrangement(order=tuple(req.order), pins=dict(req.pins), min_gap=req.min_gap, end=req.end)
    _save_arrangement(project_id, record, new, _arrangement_said(record, before, _placements(record, new)))
    return _arrangement_dict(project_id, record)


@app.post("/videos/{project_id}/arrangement/undo")
def undo_arrangement(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Back to the arrangement before the last action."""
    record = _owned(project_id, owner)
    history = list(repo.settings(project_id).get("arrangement_history") or [])
    if not history:
        raise HTTPException(status_code=409, detail="Nothing to undo in the arrangement.")
    repo.set_settings(project_id, arrangement=history[-1], arrangement_history=history[:-1])
    repo.add_message(project_id, "user", "Undid the last move")
    return _arrangement_dict(project_id, record)


def _shift_by_pin(project_id: str, record: ProjectRecord, span: Selection, to: float) -> dict:
    try:
        return _pin_line(project_id, record, span, to)
    except HTTPException as e:
        return {"error": str(e.detail)}


def _pin_line(project_id: str, record: ProjectRecord, span: Selection, to: float) -> dict:
    """A line pinned to start at `to` (the agent's shift_line, and the old
    shift endpoint): the lines around it flow, its old place gets the room's sound."""
    _migrate_moves(project_id, record)
    lines = _arrangement_lines(record)
    best = max(lines, key=lambda ln: min(span.end, ln.orig_end) - max(span.start, ln.orig_start), default=None)
    if best is None or min(span.end, best.orig_end) - max(span.start, best.orig_start) <= 0:
        raise HTTPException(status_code=422, detail="Nothing is said there to move.")
    current = _arrangement(project_id)
    before = arrange.place(lines, current)
    to = round(min(max(0.0, to), record.source.duration), 3)
    new = arrange.Arrangement(order=current.order, pins={**current.pins, best.key: to}, min_gap=current.min_gap, end=current.end)
    _save_arrangement(project_id, record, new, _arrangement_said(record, before, arrange.place(lines, new)))
    placed = next(p for p in arrange.place(lines, new) if p.key == best.key)
    return {"key": best.key, "from": {"start": best.orig_start, "end": best.orig_end},
            "selection": {"start": placed.start, "end": placed.end}, "edit_id": f"arr-{best.key}"}


# ── UX-1b: move a take or a kept line anywhere on the timeline ────────────────

class MoveRequest(BaseModel):
    # Where the audio should start, in seconds of the source.
    start: float
    # Change how it meets the sound there too, if asked.
    mix: Literal["replace", "layer", "concatenate"] | None = None


def _moved(project_id: str, record: ProjectRecord, source: EditCandidate, start: float, mix: str | None) -> EditCandidate:
    """The same take at a new place: nothing is voiced again. A held line
    (concatenate) keeps no span of the source, so its selection is the point
    it is inserted at; anything else covers its own length from `start`."""
    duration = record.source.duration
    start = round(min(max(0.0, start), duration), 3)
    mix = mix or source.plan.mix
    if mix == "concatenate":
        selection = Selection(start, start)
    else:
        selection = Selection(start, round(min(duration, start + source.audio.duration), 3))
    candidate_id = repo.next_candidate_id(project_id)
    moved = EditCandidate(
        candidate_id=candidate_id,
        plan=replace(source.plan, selection=selection, mix=mix, fit="start"),
        audio=source.audio, frames=source.frames, continuity=source.continuity,
        fit_notes=tuple(n for n in source.fit_notes if not n.startswith("moved")) + (f"moved to {_clock(start)}",),
    )
    repo.save_candidate(project_id, moved)
    return moved


class RoleRequest(BaseModel):
    # What the line is in the mix: "voice", "bed" or "effect".
    role: Literal["voice", "bed", "effect"]
    # The fine-tune on top of the role's level, in dB (-24 to +6).
    offset_db: float = 0.0
    # Make the only speech in its span a Bed anyway: the user was asked and said so.
    confirm: bool = False


ONLY_VOICE = ("This is the only speech here. As a Bed it would just be quieter. "
              "Keep it as Voice, or play it quietly under (Voice at -8 dB)?")


def _only_voice(project_id: str, record: ProjectRecord, plan: EditPlan, skip: set[str]) -> bool:
    """Whether a line is the only speech in its span: none of the original's
    words play there, and no other added line that is a voice."""
    sel = plan.selection
    edits = [e for e in repo.list_edits(project_id) if not e.reverted]
    if any(a < sel.end and sel.start < b for a, b in _speech_spans(record, edits)):
        return False
    others = [e.plan for e in edits if e.edit_id not in skip and e.candidate_id not in skip
              and e.plan.mix in ("layer", "over", "concatenate")]
    others += [c.plan for c in (repo.get_candidate(project_id, i.candidate_id) for i in (repo.latest_plan(project_id).items if repo.latest_plan(project_id) else ())
               if i.status == "ready" and i.candidate_id and i.candidate_id not in skip) if c is not None and c.plan.mix in ("layer", "over", "concatenate")]
    return not any(role_of(p) == "voice" and p.selection.start < sel.end and sel.start < p.selection.end for p in others)


def _check_role(project_id: str, record: ProjectRecord, plan: EditPlan, role: str, confirm: bool, skip: set[str]) -> None:
    if role == "bed" and role_of(plan) != "bed" and not confirm and _only_voice(project_id, record, plan, skip):
        raise HTTPException(status_code=409, detail={
            "question": ONLY_VOICE,
            "options": [{"label": "Keep it as Voice", "role": "voice", "offset_db": float(plan.offset_db or 0.0)},
                        {"label": "Play it quietly under", "detail": "Voice at -8 dB", "role": "voice", "offset_db": -8.0},
                        {"label": "Make it a Bed anyway", "role": "bed", "offset_db": 0.0, "confirm": True}],
        })


def _reroled(project_id: str, source: EditCandidate, role: str, offset_db: float) -> EditCandidate:
    """The same take in another role, or fine-tuned (2026-10-20): nothing is voiced again."""
    offset = round(max(OFFSET_RANGE[0], min(OFFSET_RANGE[1], float(offset_db or 0.0))), 1) or None
    candidate = EditCandidate(
        candidate_id=repo.next_candidate_id(project_id),
        plan=replace(source.plan, role=None if role == "voice" else role, offset_db=offset),
        audio=source.audio, frames=source.frames, continuity=source.continuity,
        fit_notes=tuple(n for n in source.fit_notes if not n.startswith(("level", "role"))),
    )
    repo.save_candidate(project_id, candidate)
    # One processing model: a mix change is a job too, over as soon as it starts.
    activity.instant(project_id, "mix", "Mix changed", turn_id=current_turn.get(),
                     detail={"role": role, "offset_db": offset, "candidate_id": candidate.candidate_id})
    return candidate


@app.post("/videos/{project_id}/candidates/{candidate_id}/role")
def role_candidate(project_id: str, candidate_id: str, req: RoleRequest, owner: str = Depends(current_owner)) -> dict:
    """A proposed take as a Voice, a Bed or an Effect, or fine-tuned; the plan item follows it.
    The only speech in its span does not silently become a Bed: 409 with the question."""
    record = _owned(project_id, owner)
    source = repo.get_candidate(project_id, candidate_id)
    if source is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if source.plan.mix in ("remove", "replace"):
        raise HTTPException(status_code=422, detail="A line of the original speech is always a voice.")
    _check_role(project_id, record, source.plan, req.role, req.confirm, {candidate_id})
    out = _reroled(project_id, source, req.role, req.offset_db)
    plan = repo.latest_plan(project_id)
    if plan is not None:
        for item in plan.items:
            if item.candidate_id == candidate_id and item.status == "ready":
                repo.update_item(project_id, plan.plan_id, item.item_id, candidate_id=out.candidate_id)
    return _candidate_dict(out)


@app.post("/videos/{project_id}/edits/{edit_id}/role")
def role_edit(project_id: str, edit_id: str, req: RoleRequest, owner: str = Depends(current_owner)) -> dict:
    """An added line in the video as a Voice, a Bed or an Effect, or fine-tuned:
    the old edit is reverted and the same take approved in its new role, in one step."""
    record = _owned(project_id, owner)
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id and not e.reverted), None)
    if edit is None:
        raise HTTPException(status_code=404, detail="edit not found")
    _check_role(project_id, record, edit.plan, req.role, req.confirm, {edit_id, edit.candidate_id})
    out = _rerole_edit(project_id, edit_id, req.role, req.offset_db)
    if out is None:
        raise HTTPException(status_code=422, detail="A line of the original speech is always a voice.")
    return out


def _rerole_edit(project_id: str, edit_id: str, role: str, offset_db: float) -> dict | None:
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id and not e.reverted), None)
    if edit is None or edit.plan.mix in ("remove", "replace") or edit.partner:
        return None
    source = repo.get_candidate(project_id, edit.candidate_id) or EditCandidate(
        edit.candidate_id, edit.plan, edit.audio, edit.frames, ContinuityReport(None, None, None, None, True, (), ()),
    )
    out = _reroled(project_id, source, role, offset_db)
    repo.revert_edit(project_id, edit_id)
    new_id = _approve_candidate(project_id, out, overridden=edit.overridden)
    return {"edit_id": new_id, "reverted": edit_id, "candidate": _candidate_dict(out)}


@app.post("/videos/{project_id}/candidates/{candidate_id}/move")
@app.post("/projects/{project_id}/candidates/{candidate_id}/move", deprecated=True)
def move_candidate(
    project_id: str, candidate_id: str, req: MoveRequest, owner: str = Depends(current_owner),
) -> dict:
    """A take, placed somewhere else on the timeline. Returns the new
    candidate; the old one is kept, as every candidate is."""
    record = _owned(project_id, owner)
    source = repo.get_candidate(project_id, candidate_id)
    if source is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if source.plan.mix == "remove":
        raise HTTPException(status_code=422, detail="A removal has no audio to move.")
    moved = _moved(project_id, record, source, req.start, req.mix)
    # The plan item that carries this take follows it (20d), so Keep ships the moved take.
    plan = repo.latest_plan(project_id)
    if plan is not None:
        for item in plan.items:
            if item.candidate_id == candidate_id and item.status == "ready":
                repo.update_item(project_id, plan.plan_id, item.item_id, candidate_id=moved.candidate_id,
                                 selection=Selection(moved.plan.selection.start, moved.plan.selection.end))
    return _candidate_dict(moved)


@app.post("/videos/{project_id}/edits/{edit_id}/move")
@app.post("/projects/{project_id}/edits/{edit_id}/move", deprecated=True)
def move_edit(
    project_id: str, edit_id: str, req: MoveRequest, owner: str = Depends(current_owner),
) -> dict:
    """A kept line, placed somewhere else: the old edit is reverted and the
    same take approved at the new place, in one step."""
    record = _owned(project_id, owner)
    _migrate_moves(project_id, record)
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id and not e.reverted), None)
    if edit is None:
        raise HTTPException(status_code=404, detail="edit not found")
    if edit.plan.mix == "remove":
        raise HTTPException(status_code=422, detail="A removal has no audio to move.")
    if edit.plan.mix == "replace" and req.mix in (None, "replace"):
        # A replacement travels with its line (2026-10-19): moving it moves the line.
        line = next((k for k, e in _line_replacements(record, [edit]).items() if e.edit_id == edit_id), None)
        if line is not None:
            st = statements_of(record.transcript)[int(line[1:])]
            out = _pin_line(project_id, record, Selection(st.start, st.end), req.start)
            return {"edit_id": edit_id, "reverted": None, "pinned": out["key"], "selection": out["selection"]}
    source = repo.get_candidate(project_id, edit.candidate_id) or EditCandidate(
        edit.candidate_id, edit.plan, edit.audio, edit.frames, ContinuityReport(None, None, None, None, True, (), ()),
    )
    moved = _moved(project_id, record, source, req.start, req.mix)
    repo.revert_edit(project_id, edit_id)
    new_id = _approve_candidate(project_id, moved, overridden=edit.overridden, partner=edit.partner)
    if edit.partner:
        repo.relink_edit(project_id, edit.partner, new_id)
    return {"edit_id": new_id, "reverted": edit_id, "candidate": _candidate_dict(moved)}


# ── Phase 20: Voltage with tools ──────────────────────────────────────────────

def _message_dict(m) -> dict:
    out = {"role": m.role, "text": m.text, "kind": m.kind, "seq": m.seq}
    if m.cost is not None:
        out["cost"] = round(m.cost, 4)
    if m.data is not None:
        out["data"] = m.data
    return out


def _agent_on() -> bool:
    return bool(settings.agent and settings.anthropic_api_key)


_agent_instance: agent_loop.Agent | None = None


def _agent() -> agent_loop.Agent:
    """The agent over one Anthropic client, made on first use (tests swap it)."""
    global _agent_instance
    if _agent_instance is None:
        import anthropic
        headers = {"anthropic-workspace-id": settings.anthropic_workspace_id} if settings.anthropic_workspace_id else None
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key, default_headers=headers, timeout=600.0, max_retries=1)
        _agent_instance = agent_loop.Agent(client, model=settings.agent_model, effort=settings.agent_effort)
    return _agent_instance


def _hear_levels(record: ProjectRecord, start: float, end: float) -> dict:
    from app.continuity import signals
    x = signals.load(record.source.media.path, start, end)
    return {"noise_db": float(signals.noise_floor_db(x)) if len(x) else None,
            "speech_db": signals.speech_level_db(x) if len(x) else None}


def _sight_text(project_id: str) -> str:
    saved = repo.settings(project_id).get("sight") or {}
    bits = [saved.get("opening", ""), saved.get("setting", ""), saved.get("mood", "")]
    place = saved.get("place_confirmed") or saved.get("place_guess")
    if place:
        bits.append(f"Place: {place}" + ("" if saved.get("place_confirmed") else f" ({saved.get('confidence', 'a')} guess)"))
    return " ".join(b.strip() for b in bits if b and b.strip())


def _workbench() -> Workbench:
    def estimate_usd(text: str) -> tuple[int, float]:
        # A line is voiced as several takes by duration (Phase 14); each is billed.
        takes = max(1, int(getattr(voice, "takes_per_line", 1)))
        chars = voice.cost_of(EditPlan(Selection(0.0, 1.0), text, getattr(voice, "default_voice", "speaker-1"))) * takes
        return chars, round(chars * budget.usd_per_1k / 1000, 4)

    def design_cost(text: str | None = None) -> tuple[int, float]:
        chars = len(text) if text else int(getattr(voice, "design_cost", lambda: 0)())
        return chars, round(chars * budget.usd_per_1k / 1000, 4)

    def put_audio(project_id: str, data: bytes, container: str, duration: float):
        return artifacts.put_bytes(project_id, data, kind="audio", container=container, duration=duration)

    can_design = hasattr(voice, "design_voice")
    return Workbench(
        repo=repo, ledger=ledger, frames=_frames, lines=_lines, room_after=room_after,
        voices=_catalogue, library=getattr(voice, "library", lambda accent, language="en": []),
        estimate_usd=estimate_usd, generate=_generate, ensure_spend=_ensure_spend, ship=_ship,
        edits=lambda pid: [e for e in repo.list_edits(pid) if not e.reverted],
        render_state=lambda pid: _render_status(pid, "final"),
        revert=lambda pid, edit_id: _revert(pid, edit_id, by="Voltage"),
        rerole_take=lambda pid, candidate, role, offset_db: _reroled(pid, candidate, role, offset_db),
        mine=_my_voices,
        rerole_edit=lambda pid, edit_id, role, offset_db: _rerole_edit(pid, edit_id, role, offset_db),
        only_voice=lambda pid, plan, skip: _only_voice(pid, repo.get(pid), plan, set(skip)),
        default_voice=lambda: getattr(voice, "default_voice", "speaker-1"),
        hear=_hear_levels, sight_text=_sight_text, now=_now,
        design=voice.design_voice if can_design else None, design_cost=design_cost,
        save_voice=voice.save_voice if can_design else None,
        add_from_library=getattr(voice, "add_from_library", None),
        delete_voice=getattr(voice, "delete_voice", None),
        slots=getattr(voice, "slots", lambda: None), put_audio=put_audio,
        speakers=repo.speakers, voice_for=_voice_for, remove_words=_remove_words, shift_words=_shift_by_pin, move_take=_moved,
        project=_project_view, suggest=_suggest_brief, help_search=lambda query: search_help_articles(query, limit=3),
        spend=lambda pid: _spend_summary(repo.get(pid).owner if repo.get(pid) else LOCAL_OWNER, video_id=pid),
        measured=lambda: getattr(voice, "last_measure", None), held_take=_held_take, jobs=line_jobs,
    )


class TurnRequest(BaseModel):
    text: str
    # The user's yes to the paid or committing step Voltage asked about last turn.
    approve: bool = False


def _turn_plan(project_id: str, text: str) -> Plan:
    """The plan a turn works on: the latest one while it still holds work
    (a line planned or voiced and not shipped), else a new one. A turn that
    ends without a question marks its plan done, but the lines stay the
    user's to hear and ship; only once every line is shipped or dropped does
    the next goal start a fresh plan (20b)."""
    plan = repo.latest_plan(project_id)
    if plan is not None and plan.status != "done":
        return plan
    if plan is not None and any(i.kind == "planned" and i.status not in ("approved", "dismissed") for i in plan.items):
        return plan
    plan = Plan(plan_id=repo.next_plan_id(project_id), project_id=project_id, goal=text, summary="", items=(),
                mode=_settings(project_id)["autonomy"], status="proposed", created_at=_now())
    repo.save_plan(plan)
    return plan


@app.post("/videos/{project_id}/turns", status_code=202)
@app.post("/projects/{project_id}/turns", status_code=202, deprecated=True)
def take_turn(project_id: str, req: TurnRequest, owner: str = Depends(current_owner)) -> dict:
    """One turn of Voltage with tools (Phase 20): the user's words go in, the
    agent looks, listens, voices and asks through its tools, and the job's
    result is the plan and Voltage's closing line. Steps appear as messages
    while it runs (`GET /projects/{id}/messages?after=`)."""
    record = _owned(project_id, owner)
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say what you want.")
    # The tutorial's sample video replays a recorded run: no vendor, no agent.
    if is_tutorial is not None and is_tutorial(repo, project_id):
        return replay_turn(repo, project_id, text, owner)
    if not _agent_on():
        raise HTTPException(status_code=503, detail="Voltage needs Claude for this (set AVE_AGENT=1 and an Anthropic key).")
    return _start_turn(project_id, record, text, owner, approve=req.approve)


def _ceiling_refusal(project_id: str, record: ProjectRecord, owner: str, more_usd: float) -> str | None:
    """Why the turn's cap may not rise by `more_usd`: the video's ceiling, its
    project's or the month's would be passed; the sentence names the scope."""
    spent = ledger.spent_usd(project_id)
    if spent + more_usd > ledger.ceiling_usd + 1e-9:
        return (f"Allowing ${more_usd:.2f} more would take {record.source.filename or 'this video'} past its "
                f"{money(ledger.ceiling_usd)} video ceiling (${spent:.2f} spent). Raise the video ceiling in Settings first.")
    project = _folder_of(record)
    if project is not None and project.ceiling_usd is not None:
        ours = ledger.spent_usd_by_folder(project.project_id)
        if ours + more_usd > float(project.ceiling_usd) + 1e-9:
            return (f"Allowing ${more_usd:.2f} more would take {project.name} past its {money(float(project.ceiling_usd))} "
                    f"project ceiling (${ours:.2f} spent). Raise it on the project page first.")
    if settings.user_budget_usd is not None:
        mine = ledger.spent_usd_by_owner(owner, iso(month_start()))
        if mine + more_usd > settings.user_budget_usd + 1e-9:
            return (f"Allowing ${more_usd:.2f} more would take you past your {money(settings.user_budget_usd)} "
                    f"ceiling for {month_name()} (${mine:.2f} spent).")
    return None


@app.post("/videos/{project_id}/turns/allow-more", status_code=202)
def allow_more(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """The way through a question the turn's cap caused: raise this turn's cap
    by exactly what the refused step needs (worked out when the question was
    asked) and carry the same turn on. Refused, naming the scope, when the
    video's, the project's or the month's ceiling would be passed."""
    record = _owned(project_id, owner)
    plan = repo.latest_plan(project_id)
    question = plan.question if plan is not None and plan.status == "clarifying" else None
    cap = (question or {}).get("turn_cap")
    if not cap:
        raise HTTPException(status_code=409, detail="Nothing is waiting on this turn's cap.")
    if not _agent_on():
        raise HTTPException(status_code=503, detail="Voltage needs Claude for this (set AVE_AGENT=1 and an Anthropic key).")
    needed = round(float(cap["needed_usd"]), 2)
    refusal = _ceiling_refusal(project_id, record, owner, needed)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    carry = {"turn_id": cap.get("turn_id"), "since": cap.get("since"), "cap_usd": round(float(cap["cap_usd"]) + needed, 2),
             "needed_usd": needed}
    return _start_turn(project_id, record, str(question["options"][0]), owner, carry=carry)


def _start_turn(project_id: str, record: ProjectRecord, text: str, owner: str, approve: bool = False,
                carry: dict | None = None) -> dict:
    """Queue one turn. `carry` continues the turn a cap question ended: the
    same turn id and start, its cap raised (`cap_usd`), the paid step approved."""
    if any(j.kind == "turn" and j.project_id == project_id and not j.done for j in jobs.all()):
        raise HTTPException(status_code=409, detail="Voltage is still on the last thing you said.")
    prefs = _settings(project_id, owner)
    autonomy = prefs["autonomy"]
    plan = _turn_plan(project_id, text)
    # A question already resolved in the editor is no gate for this turn (2026-10-20).
    asked = plan.question if plan.question and not plan.question.get("resolved") else None
    # A yes to a gate question (a paid or committing step that waited): a go word, or its first option.
    gate = asked if asked and asked.get("gate") else None
    approve = approve or bool(gate and (is_go(text) or text.strip().lower() == str(gate["options"][0]).lower()))
    # Consent binds before anything synthesizes this speaker's voice: under
    # Just do it before the turn, under Check with me at the yes (and at "allow more").
    if record.consent is None and (autonomy == "draft" or approve or carry):
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    repo.add_message(project_id, "user", text)
    # The open question is answered by this turn, or superseded by it; either way it is kept, resolved.
    if asked and plan.status == "clarifying":
        answered = text.strip().lower() in {str(o.get("label") if isinstance(o, dict) else o).strip().lower() for o in asked.get("options") or []}
        resolved = {**asked, "resolved": {"why": "you answered" if answered or approve else "a newer turn started",
                                          "by": "chat", "answer": text[:200], "at": _now()}}
        repo.append_log(project_id, plan.plan_id, f"The question was {'answered' if answered or approve else 'left for a newer turn'}")
    else:
        resolved = None
    repo.update_plan(project_id, plan.plan_id, status="running", question=None)
    if resolved:
        repo.set_settings(project_id, last_question=resolved)
    job = jobs.create("turn", project_id)
    started_at = _now()
    # Spend scopes: the turn's id is the job's; every charge it causes carries it.
    # A carried-on turn keeps the first one's id and start, so "this turn" is one figure.
    turn_id = (carry or {}).get("turn_id") or job.job_id
    since = (carry or {}).get("since") or started_at
    cap_usd = float((carry or {}).get("cap_usd") or prefs["turn_usd"])
    repo.set_settings(project_id, last_turn={"id": turn_id, "at": since, **({"cap_usd": cap_usd} if carry else {})})
    # One processing model (2026-10-20): the turn as the editor shows it, and
    # on a Go every line it will voice queued at once.
    hash_before = _final_hash(project_id)
    _stops.discard(turn_id)
    if approve or carry:
        _queue_lines(project_id, plan.plan_id, turn_id)
    _set_turn(project_id, turn_id=turn_id, status="running", step="Thinking", started_at=_now(), finished_at=None,
              spent_usd=0.0, lines_voiced=0, render=None)
    held: dict = {}
    # The words the user picked, with the sentence under the label when there was one.
    picked = ""
    if asked and asked.get("details"):
        for label, detail in zip(asked.get("options") or [], asked["details"]):
            if detail and str(label).strip().lower() == text.strip().lower():
                picked = f" (They picked “{label}”: {detail})"

    def work(report) -> dict:
        token = current_turn.set(turn_id)

        def told(progress: float, step: str) -> None:
            report(progress, step)
            _set_turn(project_id, step=step)
        try:
            out = turn_work(told)
            closed = _close_turn(project_id, plan.plan_id, turn_id, since, hash_before, held.get("turn"), out)
            return {**out, **closed, "spend": _spend_summary(owner, video_id=project_id)}
        finally:
            current_turn.reset(token)

    def turn_work(report) -> dict:
        try:
            _ensure_spend(project_id)
        except SpendCeilingReached as exc:
            repo.update_plan(project_id, plan.plan_id, status="proposed")
            repo.add_message(project_id, "assistant", str(exc))
            return {"plan": _plan_dict(repo.get_plan(project_id, plan.plan_id)), "reply": str(exc), "question": None,
                    "ceiling": exc.scope}
        budget_ = TurnBudget(usd=cap_usd)
        if carry:
            # The raise is for the step the cap refused; this continuation's own thinking is not charged to it.
            budget_.excused = lambda: ledger.spent_usd_since(project_id, started_at, vendor="anthropic")
        turn = AgentTurn(project_id=project_id, record=record, plan_id=plan.plan_id, autonomy=autonomy,
                         spend_approved=approve or bool(carry) or autonomy == "draft", budget=budget_, started_at=since,
                         report=report, commit_approved=approve, ask_before=prefs["ask_before"],
                         stop_requested=lambda: turn_id in _stops)
        held["turn"] = turn
        lines = _lines(record)
        names = [s.name for s in repo.speakers(project_id)]
        # 2026-10-20: the style line is shown before the first paid step: at the start of the first turn it is there.
        understood = repo.settings(project_id).get("understanding")
        style = (understood or {}).get("style") or {}
        if style.get("line") and not style.get("shown"):
            repo.add_message(project_id, "assistant", f"Style for this video: {style['line']}", kind="step",
                             data={"tool": "style", "t": 0.0})
            repo.set_settings(project_id, understanding={**understood, "style": {**style, "shown": True}})
        from app.agent.context import opening
        # F2: the turn records the brief version its opening view read.
        view = _project_view(project_id)
        if view is not None:
            repo.set_settings(project_id, last_turn={**(repo.settings(project_id).get("last_turn") or {}),
                                                     "brief_version": view.get("brief_version")})
            _set_turn(project_id, brief_version=view.get("brief_version"))
        head = opening(repo.get_plan(project_id, plan.plan_id), duration=record.source.duration,
                       filename=record.source.filename, speakers=names, lines=len(lines), autonomy=autonomy,
                       spent_usd=ledger.spent_usd(project_id), ceiling_usd=ledger.ceiling_usd,
                       turn_usd=cap_usd, sight=_sight_text(project_id) if not lines else "",
                       edits=[e for e in repo.list_edits(project_id) if not e.reverted], project=view,
                       understanding=understanding_mod.context_lines(repo.settings(project_id).get("understanding")))
        allowed = (f" (They allowed ${carry['needed_usd']:.2f} more for this turn: its cap is now ${cap_usd:.2f}, "
                   "so the step that went over it may run now. Carry on with it.)") if carry else ""
        content = [{"type": "text", "text": head}, {"type": "text", "text": f"The user says: {text}"
                   + (" (They are answering yes to what you asked.)" if approve else "") + allowed + picked}]
        history = repo.turns(project_id)

        def on_step(step: str, cost: float, tool: str = "", data: dict | None = None) -> None:
            # The trace shows which tool a step was and when in the turn it landed;
            # a search_help step also carries the articles it found (data.help).
            # No em dashes in Voltage's own lines (quoted words and the user's own style excepted).
            step = plain(step, text)
            repo.add_message(project_id, "assistant", step, kind="step", cost=cost or None,
                             data={"tool": tool, "t": round(budget_.elapsed(), 1), **(data or {})})
            repo.append_log(project_id, plan.plan_id, step, f"${cost:.2f}" if cost else "")
            report(min(0.95, 0.05 + 0.9 * turn.budget.calls_made / turn.budget.calls), step)

        def on_card(text_: str, data: dict) -> None:
            repo.add_message(project_id, "assistant", text_, kind="previews", data=data)

        try:
            outcome = _agent().run(_workbench(), turn, history, content, meter=_meter(project_id, "agent"),
                                   on_step=on_step, on_card=on_card, effort=prefs["effort"],
                                   persist=lambda role, c: repo.append_turn(project_id, role, c))
        except Exception as exc:  # noqa: BLE001 — the user hears a sentence; the log has the rest
            logging.getLogger(__name__).exception("turn failed")
            why = str(exc)[:200] or type(exc).__name__
            sentence = f"Something went wrong on my side ({why}). Say it again and I'll retry."
            repo.add_message(project_id, "assistant", sentence)
            repo.update_plan(project_id, plan.plan_id, status="proposed")
            return {"type": "turn", "plan": _plan_dict(repo.get_plan(project_id, plan.plan_id)), "reply": sentence,
                    "question": None, "spent_usd": 0.0, "calls": 0, "stopped": "error", "error": why}
        if outcome.stopped == agent_loop.STOPPED:
            # The user's Stop: Voltage's closing words say what finished and what did not.
            outcome = replace(outcome, reply=_stopped_words(project_id, turn_id), question=None)
        question = outcome.question
        status = "clarifying" if question else "done"
        # 2026-10-20: the closing words may end with the next chips; the user sees the words, the box the chips.
        words, raw_chips = chips.split_reply(outcome.reply or "")
        outcome = replace(outcome, reply=words or None)
        _after_turn_chips(project_id, record, text, raw_chips)
        # p60: the closing words are checked against the record; a claim it does not support is corrected.
        from app.agent.reply_check import corrections
        fixes = corrections(outcome.reply or "", repo.get_plan(project_id, plan.plan_id).items, _lines(record))
        if fixes:
            logging.getLogger(__name__).info("reply corrected for %s: %s", project_id, fixes)
            outcome = replace(outcome, reply=(outcome.reply or "").rstrip() + "\n\n" + " ".join(fixes))
        if outcome.reply:
            outcome = replace(outcome, reply=plain(outcome.reply, text))
            from app.agent.reply_lint import lint
            if issues := lint(outcome.reply, text):
                logging.getLogger(__name__).info("reply lint for %s: %s", project_id, ", ".join(issues))
            repo.add_message(project_id, "assistant", outcome.reply)
        # What Voltage's own thinking cost this turn, as a step of its own (20d):
        # the tools say what they spent; this is the rest of the turn's money.
        thought = ledger.spent_usd_since(project_id, started_at, vendor="anthropic")
        if thought > 0:
            repo.add_message(project_id, "assistant", "Thinking", kind="step", cost=round(thought, 4),
                             data={"tool": "thinking", "t": round(budget_.elapsed(), 1)})
        if question:
            # The card says what the turn has left of its cap, in one sentence.
            spent_now = ledger.spent_usd_since(project_id, since)
            left = budget_.usd - (spent_now - (budget_.excused() if budget_.excused else 0.0))
            question = {**question, "left_usd": round(max(0.0, left), 2), "cap_usd": round(budget_.usd, 2),
                        "text": plain(question["text"], text),
                        "options": [plain(o, text) for o in question.get("options") or []], "guess": plain(question.get("guess"), text)}
            if question.get("details"):
                question["details"] = [plain(d, text) for d in question["details"]]
            # A question the turn's cap caused: the first option is the way through,
            # raising this turn's cap by exactly what the refused step needs.
            needed = budget_.needed_usd(spent_now) if not question.get("gate") else 0.0
            if needed > 0:
                opts = question["options"]
                details = question.get("details") or [None] * len(opts)
                question["options"] = [f"Go ahead, allow ${needed:.2f} more", *opts]
                question["details"] = [f"Raises this turn's cap to ${budget_.usd + needed:.2f} and carries on.", *details]
                question["turn_cap"] = {"needed_usd": needed, "cap_usd": round(budget_.usd, 2), "turn_id": turn_id, "since": since}
            repo.add_message(project_id, "assistant", question["text"])
            repo.append_log(project_id, plan.plan_id, f"Asked: {question['text']}")
        updated = repo.get_plan(project_id, plan.plan_id)
        repo.update_plan(project_id, plan.plan_id, status=status, question=question, summary=outcome.reply or updated.summary,
                         estimate=_estimate(project_id, updated.items))
        return {"type": "turn", "plan": _plan_dict(repo.get_plan(project_id, plan.plan_id)), "reply": outcome.reply,
                "question": question, "spent_usd": round(outcome.spent_usd, 4), "calls": outcome.calls,
                "stopped": outcome.stopped, "suggestions": _chips_now(project_id, record)["suggestions"]}

    def failed_turn() -> None:
        repo.update_plan(project_id, plan.plan_id, status="proposed")
        _cancel_leftovers(project_id, turn_id, "The turn failed")
        _stops.discard(turn_id)
        _set_turn(project_id, status="failed", step="Failed", finished_at=_now())

    submitted = runner.submit(job, _guarded(work, failed_turn))
    return _job_dict(submitted)


def _final_hash(project_id: str) -> str:
    edits, _ = _render_edits(project_id, False)
    return edit_set_hash(repo.get(project_id), edits, "final")


def _stopped_words(project_id: str, turn_id: str) -> str:
    steps = activity.of_turn(project_id, turn_id)
    voiced = sum(1 for j in steps if j.kind == "voice_line" and j.status == "done")
    cancelled = sum(1 for j in steps if j.kind == "voice_line" and j.status in ("cancelled", "queued"))
    words = f"Stopped. {voiced} {'line' if voiced == 1 else 'lines'} voiced"
    return words + (f", {cancelled} cancelled." if cancelled else ".")


def _close_turn(project_id: str, plan_id: str, turn_id: str, since: str, hash_before: str, turn, out: dict) -> dict:
    """The end of a turn (2026-10-20): a turn that voiced or shipped anything
    renders a preview as its last step, so its lines are in the video the user
    hears; the lines it queued and never voiced are cancelled; the turn's view
    says what it spent and which version it made."""
    render = None
    voiced = turn is not None and bool(turn.takes)
    if out.get("stopped") != "error" and (voiced or _final_hash(project_id) != hash_before):
        plan_now = repo.get_plan(project_id, plan_id)
        proposals = any(i.kind == "planned" and i.status == "ready" and i.candidate_id for i in (plan_now.items if plan_now else ()))
        _set_turn(project_id, step="Rendering preview")
        try:
            made = _export(repo.get(project_id), proposals=proposals)
            render = {"version": made["version"], "mode": made["mode"], "render_id": made["render_id"]}
        except Exception:  # noqa: BLE001 - the render's job says it failed; the turn's work stands
            log.exception("the turn's preview render failed for %s", project_id)
    _cancel_leftovers(project_id, turn_id)
    _stops.discard(turn_id)
    turn_usd = round(ledger.spent_usd_since(project_id, since), 4)
    steps = activity.of_turn(project_id, turn_id)
    lines_voiced = sum(1 for j in steps if j.kind == "voice_line" and j.status == "done")
    _set_turn(project_id, status="failed" if out.get("stopped") == "error" else "done", step="Done", finished_at=_now(),
              spent_usd=turn_usd, lines_voiced=lines_voiced, render=render)
    return {"turn_usd": turn_usd, "render": render}


def _guarded(work, on_fail):
    def run(report):
        try:
            return work(report)
        except Exception:
            on_fail()
            raise
    return run


@app.get("/videos/{project_id}/messages")
@app.get("/projects/{project_id}/messages", deprecated=True)
def list_messages(project_id: str, after: int = 0, owner: str = Depends(current_owner)) -> list[dict]:
    """The thread after a message (by `seq`): what Voltage said and did."""
    _owned(project_id, owner)
    return [_message_dict(m) for m in repo.messages(project_id, after)]


# ── One processing model (2026-10-20): jobs, Stop, Retry, the live channel ──

# A finished turn's steps stay in the active view this long, so a reload just
# after "Done" still rebuilds the step list.
RECENT_TURN_SECONDS = 600


def _recent(at: str | None) -> bool:
    if not at:
        return False
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds() <= RECENT_TURN_SECONDS
    except ValueError:
        return False


def _jobs_view(project_id: str, active: bool) -> dict:
    view = _turn_view(project_id)
    live = bool(view) and (view.get("status") in ("running", "stopping") or _recent(view.get("finished_at")))
    if not active:
        found = activity.list(project_id, limit=50)
        return {"jobs": [j.to_dict() for j in found], "turn": view}
    found = {j.job_id: j for j in activity.list(project_id, active=True, limit=200)}
    if live and view.get("turn_id"):
        for j in activity.of_turn(project_id, view["turn_id"]):
            found.setdefault(j.job_id, j)
    ordered = sorted(found.values(), key=lambda j: int(j.job_id[1:]), reverse=True)
    return {"jobs": [j.to_dict() for j in ordered], "turn": view if live else None}


@app.get("/videos/{project_id}/jobs")
def list_jobs(project_id: str, active: int = 0, owner: str = Depends(current_owner)) -> dict:
    """The video's jobs, newest first. `active=1`: what is queued or running,
    plus the steps of the turn running now (or just finished), so a reload
    restores the status strip, the row chips and the step list."""
    _owned(project_id, owner)
    return _jobs_view(project_id, bool(active))


@app.post("/videos/{project_id}/jobs/{job_id}/retry", status_code=202)
def retry_job(project_id: str, job_id: str, owner: str = Depends(current_owner)) -> dict:
    """A failed line voiced again with the same words and voice, or a failed
    render run again; a new job, through the same flow."""
    _owned(project_id, owner)
    job = activity.get(job_id)
    if job is None or job.video_id != project_id:
        raise HTTPException(status_code=404, detail="job not found")
    if not job.to_dict()["retryable"]:
        raise HTTPException(status_code=409, detail="Only a line or a render that failed can be tried again.")
    if job.kind == "voice_line":
        if not job.params or not job.line_ids:
            raise HTTPException(status_code=409, detail="This line was never started, so there is nothing to try again. Ask Voltage for it.")
        if activity.active_for_line(project_id, job.line_ids[0]) is not None:
            raise HTTPException(status_code=409, detail="This line is already being voiced.")
        fresh = activity.create(project_id, "voice_line", line_ids=job.line_ids,
                                detail={**job.detail, "manual": True, "retry_of": job.job_id}, params=job.params)
        _in_background(project_id, fresh.job_id, lambda: _retry_line(project_id, fresh.job_id))
        return fresh.to_dict()
    mode = job.detail.get("mode") or "final"
    fresh = activity.create(project_id, job.kind, detail={"mode": mode, "manual": True, "retry_of": job.job_id})
    _in_background(project_id, fresh.job_id, lambda: _export(repo.get(project_id), proposals=mode == "proposals",
                                                             purpose="export" if job.kind == "export" else "preview",
                                                             job_id=fresh.job_id))
    return fresh.to_dict()


@app.post("/videos/{project_id}/jobs/stop")
def stop_jobs(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Stop: every queued job is cancelled; running ones finish; the turn
    ends after the step it is on."""
    _owned(project_id, owner)
    cancelled = 0
    for job in activity.list(project_id, active=True, limit=200):
        if job.status == "queued":
            activity.cancel(job.job_id, "Stopped")
            cancelled += 1
    view = _turn_view(project_id)
    if view and view.get("status") == "running" and view.get("turn_id"):
        _stops.add(view["turn_id"])
        _set_turn(project_id, status="stopping", step="Stopping after this step")
    return {"cancelled": cancelled}


PING_SECONDS = 15.0


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


@app.get("/videos/{project_id}/events")
async def video_events(project_id: str, request: Request, limit: int | None = None,
                       owner: str = Depends(current_owner)) -> StreamingResponse:
    """The live channel: job.updated, turn.updated and render.updated as they
    happen, opening with the state as it is now, and a ping every 15 s.
    `limit` ends the stream after that many events (tests)."""
    _owned(project_id, owner)
    q = events.subscribe(project_id)

    async def stream():
        sent = 0
        try:
            state = await asyncio.to_thread(_jobs_view, project_id, True)
            opening = [("job.updated", j) for j in reversed(state["jobs"])]
            if state["turn"]:
                opening.append(("turn.updated", state["turn"]))
            for event, data in opening:
                yield _sse(event, data)
                sent += 1
                if limit and sent >= limit:
                    return
            last = time.monotonic()
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event, data = await asyncio.to_thread(q.get, True, 1.0)
                except queue.Empty:
                    if time.monotonic() - last >= PING_SECONDS:
                        last = time.monotonic()
                        # The ping also sweeps: a hung job fails while someone is watching.
                        await asyncio.to_thread(activity.sweep)
                        yield ": ping\n\n"
                    continue
                yield _sse(event, data)
                sent += 1
                if limit and sent >= limit:
                    return
        finally:
            events.unsubscribe(project_id, q)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Help, the tutorial, onboarding: the coordinator's routers ────────────────

def _mount_optional_routers() -> None:
    import importlib
    for name in ("app.onboarding", "app.help", "app.tutorial"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            log.info("%s is not here yet; its routes are not mounted", name)
            continue
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)


_mount_optional_routers()
