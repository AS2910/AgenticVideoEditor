import logging
import tempfile
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

import shutil

from fastapi import Depends, FastAPI, HTTPException, File, Form, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel

from typing import Literal

from app.domain.models import (
    Source, Selection, ContinuityReport, EditCandidate, ApprovedEdit, MediaArtifact,
    Consent, EditPlan,
)
from app.domain.plan import Plan, PlanItem
from app.domain.transcript import (
    assign_speakers, room_after, snap_to_word_boundaries, speaker_of, statements_of,
)
from app.media.fit import speaking_rate, syllable_budget, syllables
from app.config import load_settings
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
from app.orchestrator.clones import CloneService, VoiceChoice
from app.orchestrator.pipeline import run_edit
from app.store.db import Database
from app.usage import Ledger, SpendCeilingReached, WHISPER_USD_PER_MINUTE, claude_usd
from app import auth
from app.store.repository import ProjectRecord, ProjectRepository, LOCAL_OWNER
from app.store.artifacts import ArtifactStore
from app.render.renderer import render
from app.render.compose import compose
from app.render import retime
from app.jobs.store import JobStore, Job
from app.jobs.runner import JobRunner
from app.agent import loop as agent_loop
from app.agent.guards import TurnBudget, is_go
from app.agent.tools import Turn as AgentTurn, Workbench

app = FastAPI(title="Agentic Video Editor")
log = logging.getLogger(__name__)

# Media lands under `backend/var/artifacts` unless AVE_DATA_DIR overrides it
# (tests point that at a temp dir; deployment points it at real storage).
settings = load_settings()

# Wiring (module-level singletons for this in-memory slice).
database = Database(settings.data_dir / "ave.db")
repo = ProjectRepository(database)
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
    return datetime.now(timezone.utc).isoformat()


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
    """The project's ceiling, and with sign-in the person's across projects."""
    record = repo.get(project_id)
    ledger.ensure_can_spend(
        project_id,
        owner=record.owner if record and settings.auth_mode != "off" else None,
        owner_ceiling_usd=settings.user_budget_usd if settings.auth_mode != "off" else None,
    )


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
    """The caller's project, or 404. Someone else's project is indistinguishable
    from a missing one, so ids leak nothing."""
    record = repo.get(project_id)
    if record is None or record.owner != owner:
        raise HTTPException(status_code=404, detail="project not found")
    return record


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
    sight = planner.look(frames, record.source.duration, meter=_meter(project_id, "looking"))
    repo.set_settings(project_id, sight=asdict(sight))
    return sight


class SightRequest(BaseModel):
    # The place, as the user confirms or corrects it; empty clears a confirmation.
    place: str = ""


@app.put("/projects/{project_id}/sight")
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


@app.get("/projects/{project_id}/frames")
def list_frames(project_id: str, owner: str = Depends(current_owner)) -> list[dict]:
    """The clip's frames, by index and time; each is served at /frames/{index}."""
    record = _owned(project_id, owner)
    return _frames_dict(record)


@app.get("/projects/{project_id}/frames/{index}")
def get_frame(project_id: str, index: int, owner: str = Depends(current_owner)) -> FileResponse:
    record = _owned(project_id, owner)
    frames = _frames(record)
    if not 0 <= index < len(frames):
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(frames[index].path, media_type="image/jpeg")


def _project_dict(record: ProjectRecord) -> dict:
    source = record.source
    return {
        "project_id": source.project_id,
        "filename": source.filename,
        "duration": source.duration,
        "media": _artifact_dict(source.media),
        "consent": _consent_dict(record.consent),
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
        # UX-5: a clip with no speech shows its frames where the transcript would be.
        "frames": _frames_dict(record) if not record.transcript.words and not record.transcript.statements else [],
    }


NEEDS_CLAUDE = "Voltage needs Claude for this (set ANTHROPIC_API_KEY)."
EFFORTS = ("medium", "high", "xhigh")
DEFAULT_AUTONOMY = "ask"


def _settings(project_id: str) -> dict:
    """What Voltage may do on this project (20d): the autonomy, what one
    turn may spend, and how hard it thinks; the project's ceiling is read-only."""
    saved = repo.settings(project_id)
    return {
        "autonomy": saved.get("autonomy", DEFAULT_AUTONOMY),
        "turn_usd": float(saved.get("turn_usd") or settings.agent_turn_usd),
        "effort": saved.get("effort") or settings.agent_effort,
        "ceiling_usd": ledger.ceiling_usd,
    }


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


@app.post("/projects")
async def create_project(
    file: UploadFile = File(...),
    consent: bool = Form(False),
    owner: str = Depends(current_owner),
) -> dict:
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
    repo.create(source, transcript, granted, owner=owner)
    if transcriber_label.startswith("openai"):
        minutes = source.duration / 60
        ledger.record(project_id, "openai", "transcription", minutes, "minutes",
                      minutes * WHISPER_USD_PER_MINUTE)
    if any(w.speaker for w in transcript.words):
        _record_diarization(project_id, source.duration)
    return _project_dict(repo.get(project_id))


@app.get("/voices")
def list_voices() -> dict:
    """The voices a new line can be spoken in, and which one is the default.
    Multi-voice comes later (a voice per speaker); today a voice is per edit."""
    return {"default": voice.default_voice, "voices": voice.voices()}


@app.get("/projects")
def list_projects(owner: str = Depends(current_owner)) -> dict:
    """The caller's projects, newest first — enough to show and reopen them:
    a frame (the source media), where each stands, and its last change (UX-3)."""
    return {"projects": [_summary(r) for r in repo.list(owner)]}


def _summary(r: ProjectRecord) -> dict:
    pid = r.source.project_id
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
        "project_id": pid,
        "filename": r.source.filename,
        "duration": r.source.duration,
        "created_at": r.created_at,
        "edits": len(live),
        "media": _artifact_dict(r.source.media),
        "state": state,
        "last_change": last,
        "variant_of": settings_.get("variant_of"),
    }


@app.get("/projects/{project_id}")
def get_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Everything needed to reopen a project: source, transcript, approved
    edits and the chat."""
    record = _owned(project_id, owner)
    return {
        **_project_dict(record),
        "edits": [
            {
                "edit_id": e.edit_id,
                "candidate_id": e.candidate_id,
                "new_text": e.plan.new_text,
                "selection": {"start": e.plan.selection.start, "end": e.plan.selection.end},
                "mix": e.plan.mix,
                "delivery": e.plan.delivery,
                "flex": e.plan.flex,
                "overridden": e.overridden,
                "reverted": e.reverted,
                "partner": e.partner,
            }
            for e in repo.list_edits(project_id)
        ],
        "messages": [_message_dict(m) for m in repo.messages(project_id)],
        # Phase 20: the composer talks to Voltage with tools when this is on.
        "agent": _agent_on(),
    }


@app.get("/projects/{project_id}/usage")
def get_usage(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """What the project has spent, per vendor, against its limits. USD is an
    estimate from list prices."""
    _owned(project_id, owner)
    return {
        "spent_usd": round(ledger.spent_usd(project_id), 4),
        "ceiling_usd": ledger.ceiling_usd,
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


class SettingsUpdate(BaseModel):
    autonomy: Literal["ask", "draft"] | None = None
    # 20d: what one turn may spend, and how hard Voltage thinks.
    turn_usd: float | None = None
    effort: Literal["medium", "high", "xhigh"] | None = None


@app.put("/projects/{project_id}/settings")
def update_settings(
    project_id: str, req: SettingsUpdate, owner: str = Depends(current_owner),
) -> dict:
    """What Voltage may do on this project: the autonomy, a turn's spend
    cap (between a cent and the project's ceiling) and the effort."""
    _owned(project_id, owner)
    turn_usd = None if req.turn_usd is None else round(min(ledger.ceiling_usd, max(0.01, req.turn_usd)), 2)
    repo.set_settings(project_id, autonomy=req.autonomy, turn_usd=turn_usd, effort=req.effort)
    return {"settings": _settings(project_id)}


class SpeakerUpdate(BaseModel):
    name: str | None = None
    # A voice id to speak this speaker's new lines in; null returns them to
    # the chat's voice. Omitted = unchanged.
    voice_id: str | None = None
    clear_voice: bool = False


@app.get("/projects/{project_id}/speakers")
def get_speakers(project_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return {"speakers": _speakers(project_id)}


@app.put("/projects/{project_id}/speakers/{label}")
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


@app.post("/projects/{project_id}/speakers/detect")
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


class ReadRequest(BaseModel):
    # Read the clip again even though a reading is saved.
    again: bool = False


@app.post("/projects/{project_id}/reading")
def read_project(project_id: str, req: ReadRequest, owner: str = Depends(current_owner)) -> dict:
    """Voltage's first look at the clip (UX-2): one specific opening line for
    the goal stage, and a role for each speaker ("the Customer") to confirm
    or rename. Saved with the project; read once unless asked again."""
    record = _owned(project_id, owner)
    saved = repo.settings(project_id).get("reading")
    if saved and not req.again:
        return saved
    lines = _lines(record)
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
        out = {"opening": sight.opening, "roles": [], "sight": asdict(sight)}
        repo.set_settings(project_id, reading=out)
        return out
    try:
        _ensure_spend(project_id)
        if planner is None:
            raise HTTPException(status_code=503, detail=NEEDS_CLAUDE)
        reading = planner.read(lines, meter=_meter(project_id, "reading"))
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    by_name = {s.name: s.label for s in repo.speakers(project_id)}
    out = {
        "opening": reading.opening,
        "roles": [
            {"label": by_name[r.speaker], "role": r.role, "why": r.why}
            for r in reading.roles if r.speaker in by_name
        ],
        "at": _now(),
    }
    repo.set_settings(project_id, reading=out)
    return out


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, owner: str = Depends(current_owner)) -> None:
    """Delete the project and all of its media. This is also how consent is
    withdrawn (design spec §2): nothing of the speaker is kept."""
    _owned(project_id, owner)
    # A clone of the speaker's voice goes with the project (Phase 15a). If the
    # vendor cannot be reached the project is still deleted here; the failure
    # is logged by name so the clone can be removed by hand.
    left = clones.purge(project_id)
    if left:
        logging.getLogger("ave").warning(
            "project %s deleted, but these voice clone(s) are still at ElevenLabs: %s", project_id, ", ".join(left))
    # Voices Voltage made for the clip (designed, or added from the library;
    # 20b) go with it too, so slots come back.
    for made in repo.settings(project_id).get("made_voices") or []:
        try:
            getattr(voice, "delete_voice", lambda v: None)(made["voice_id"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ave").warning("project %s deleted, but voice %s (%s) is still at ElevenLabs: %s",
                                             project_id, made.get("name"), made["voice_id"], exc)
    repo.delete(project_id)
    shutil.rmtree(artifacts.root / project_id, ignore_errors=True)


@app.post("/projects/{project_id}/variants")
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
    repo.create(source, record.transcript, record.consent, owner=owner)
    for s in repo.speakers(project_id):
        repo.set_speaker(new_id, s.label, name=s.name, voice_id=s.voice_id)
    saved = {k: v for k, v in repo.settings(project_id).items() if k != "reading"} | {"variant_of": project_id}
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


@app.post("/projects/{project_id}/consent")
def grant_consent(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Confirm rights for a project uploaded without them.

    Lets a refused generation be recovered without re-uploading.
    """
    _owned(project_id, owner)
    recorded = repo.grant_consent(project_id, Consent(granted_at=_now()))
    return {"project_id": project_id, "consent": _consent_dict(recorded)}


@app.get("/projects/{project_id}/artifacts/{sha256}")
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
        "project_id": job.project_id,
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
    max_regenerations: int | None = None,
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
                                      max_regenerations)
            except SpanMismatch:
                candidate = None
            if candidate is not None:
                return candidate
            report(0.1, "No room to play over the picture; holding it instead")
        return _generate(project_id, record, candidate_id, selection, text, voice_id,
                         fit, "concatenate", report, delivery, voice_notes, voice_settings, model, flex_max,
                         max_regenerations)
    plan = EditPlan(selection, text, voice_id, fit=fit, mix=mix, delivery=delivery,
                    voice_settings=voice_settings or None, model=model or None, flex_max=flex_max)
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


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dict(job)


@app.post("/projects/{project_id}/edits")
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
                repo.update_item(project_id, plan.plan_id, item.item_id, status="approved", edit_id=edit_id)
    return edit_id


@app.post("/projects/{project_id}/edits/{edit_id}/revert")
def revert_edit(project_id: str, edit_id: str, owner: str = Depends(current_owner)) -> dict:
    """Undo an approved edit (Phase 12). The edit is kept and marked, so
    nothing is lost; the render skips it and the transcript shows the line as
    shot. Reverting again is harmless."""
    _owned(project_id, owner)
    if not _revert(project_id, edit_id):
        raise HTTPException(status_code=404, detail="edit not found")
    return {"edit_id": edit_id, "reverted": True}


def _revert(project_id: str, edit_id: str, by: str = "You") -> bool:
    """Undo an approved edit; False when there is no such edit."""
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id), None)
    if edit is None or not repo.revert_edit(project_id, edit_id):
        return False
    # A shifted line is two edits; undoing one undoes the other.
    if edit.partner:
        repo.revert_edit(project_id, edit.partner)
    # A shipped plan line goes back to a draft (ready, with its take), so the
    # review shows it held rather than shipped (UX-3).
    plan = repo.latest_plan(project_id)
    if plan is not None:
        for item in plan.items:
            if item.edit_id == edit_id and item.status == "approved":
                repo.update_item(project_id, plan.plan_id, item.item_id, status="ready", edit_id=None)
                repo.append_log(project_id, plan.plan_id, f"{by} undid the line at {_clock(item.selection.start)}")
    return True


@app.post("/projects/{project_id}/export")
def export_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    return _export(_owned(project_id, owner))


def _cuts(project_id: str, record: ProjectRecord) -> list[float]:
    """Where the picture cuts (Phase 16), found once and kept with the project."""
    saved = repo.settings(project_id).get("shots")
    if saved and saved.get("sha") == record.source.media.sha256:
        return [float(c) for c in saved.get("cuts", ())]
    found = shots.cuts(record.source.media.path)
    repo.set_settings(project_id, shots={"sha": record.source.media.sha256, "cuts": found})
    return found


def _pieces(record: ProjectRecord, manifest) -> list[retime.Piece]:
    """The export as pieces (Phase 16): flexed lines, living holds for added
    lines, copies between. The picture's motion steers where time is added."""
    source = record.source
    edits = [e for e in repo.list_edits(source.project_id) if not e.reverted]
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


def _export(record: ProjectRecord) -> dict:
    project_id = record.source.project_id
    manifest = render(record.source, repo.list_edits(project_id))
    pieces = _pieces(record, manifest)
    # Synchronous: with nothing but copies the video is stream-copied and only
    # the audio re-encoded, so even a 3-minute source renders in seconds; a
    # flexed or living piece re-encodes the picture.
    with tempfile.TemporaryDirectory() as tmp:
        path = compose(
            record.source, manifest.segments, Path(tmp) / "export.mp4",
            inserts=manifest.inserts, pieces=pieces, interpolator=settings.interpolator,
            stems=_stems(record, manifest),
        )
        rendered = artifacts.put_file(
            project_id, path, kind="video", container="mp4",
            duration=ffmpeg.duration_of(path),
        )
    held_at = {p.start: p.out for p in pieces if p.kind == "hold"}
    return {
        "render": _artifact_dict(rendered),
        # Phase 16: every stretch of the output and where it came from.
        "pieces": retime.manifest(pieces),
        "segments": [
            {
                "start": s.start,
                "end": s.end,
                "kind": s.kind,
                "ref": s.ref,
                "artifact": _artifact_dict(s.artifact) if s.artifact else None,
            }
            for s in manifest.segments
        ],
        "inserts": [
            {"at": i.at, "duration": i.duration, "artifact": _artifact_dict(i.edit.audio),
             "held": round(held_at.get(round(min(max(i.at, 0.0), record.source.duration) * ffmpeg.frame_rate(record.source.media.path)) / ffmpeg.frame_rate(record.source.media.path), 0.0), 3)}
            for i in manifest.inserts
        ],
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


@app.get("/projects/{project_id}/plans/{plan_id}")
def get_plan(project_id: str, plan_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return _plan_dict(_plan_or_404(project_id, plan_id))


def _plan_or_404(project_id: str, plan_id: str) -> Plan:
    plan = repo.get_plan(project_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@app.post("/projects/{project_id}/plans/{plan_id}/approve")
def approve_plan(
    project_id: str, plan_id: str, req: PlanApproveRequest, owner: str = Depends(current_owner),
) -> dict:
    """Approve every ready item (or the ones named) and render. An item whose
    take failed continuity is skipped unless `override` is set."""
    record = _owned(project_id, owner)
    _plan_or_404(project_id, plan_id)
    return _ship(project_id, record, plan_id, req.items, req.override)


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
        approved.append({"item_id": item.item_id, "edit_id": edit_id, "overridden": overridden})
    if approved:
        repo.append_log(project_id, plan_id,
                        f"Approved {len(approved)} {'change' if len(approved) == 1 else 'changes'}")
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


@app.post("/projects/{project_id}/lines/remove")
def remove_line(project_id: str, req: RemoveRequest, owner: str = Depends(current_owner)) -> dict:
    """Take a line out (UX-1): its words go, the room's own sound stays in
    their place, the picture is untouched. Approved at once — nothing is
    voiced — and undone like any edit, with Revert."""
    record = _owned(project_id, owner)
    if not any(w.end > req.start and w.start < req.end for w in record.transcript.words):
        raise HTTPException(status_code=422, detail="Nothing is said there to remove.")
    out = _remove_words(project_id, record, Selection(req.start, req.end))
    repo.add_message(project_id, "user", f"Removed the line at {_clock(out['selection']['start'])}")
    return out


def _remove_words(project_id: str, record: ProjectRecord, span: Selection) -> dict:
    """The words in `span` taken out, the room's sound left in their place;
    approved at once (nothing is voiced). The agent's `remove_line` and the
    UX-1 route share it."""
    selection = snap_to_word_boundaries(record.transcript, span)
    candidate = _room_tone_candidate(project_id, record, selection)
    edit_id = _approve_candidate(project_id, candidate, overridden=False)
    return {
        "edit_id": edit_id, "candidate_id": candidate.candidate_id,
        "selection": {"start": selection.start, "end": selection.end}, "mix": "remove",
    }


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


@app.post("/projects/{project_id}/lines/shift")
def shift_line(project_id: str, req: ShiftRequest, owner: str = Depends(current_owner)) -> dict:
    """Move a line of the original speech to another time, as it was
    spoken: its words leave their place (the room's sound stays there) and
    play over the picture from `to`. Nothing is voiced. Two edits, undone
    together; the placed half can be moved again like any kept line."""
    record = _owned(project_id, owner)
    if not any(w.end > req.start and w.start < req.end for w in record.transcript.words):
        raise HTTPException(status_code=422, detail="Nothing is said there to move.")
    out = _shift_words(project_id, record, Selection(req.start, req.end), req.to)
    repo.add_message(project_id, "user", f"Moved the line at {_clock(out['from']['start'])} to {_clock(out['selection']['start'])}")
    return out


def _shift_words(project_id: str, record: ProjectRecord, span: Selection, to: float) -> dict:
    """A line of the original speech moved to `to`, as spoken: two edits,
    the room's sound where it was and the words placed over the picture."""
    source = snap_to_word_boundaries(record.transcript, span)
    duration = record.source.duration
    to = round(min(max(0.0, to), duration), 3)
    length = source.end - source.start
    words = " ".join(w.text for w in record.transcript.words if w.end > source.start and w.start < source.end)
    with tempfile.TemporaryDirectory() as tmp:
        path, got = ffmpeg.extract_segment(record.source.media.path, Path(tmp) / "line.wav", source.start, source.end)
        audio = artifacts.put_file(project_id, path, kind="audio", container="wav", duration=got)
    placed = EditCandidate(
        candidate_id=repo.next_candidate_id(project_id),
        plan=EditPlan(Selection(to, round(min(duration, to + length), 3)), words, "original", fit="start", mix="layer"),
        audio=audio, frames=record.source.media,
        continuity=ContinuityReport(None, None, None, None, True, (), ()),
        fit_notes=(f"moved from {_clock(source.start)}",),
    )
    repo.save_candidate(project_id, placed)
    removed = _room_tone_candidate(project_id, record, source)
    removed_id = _approve_candidate(project_id, removed, overridden=False)
    placed_id = _approve_candidate(project_id, placed, overridden=False, partner=removed_id)
    repo.relink_edit(project_id, removed_id, placed_id)
    return {
        "edit_id": placed_id, "removed_edit_id": removed_id, "candidate": _candidate_dict(placed),
        "from": {"start": source.start, "end": source.end},
        "selection": {"start": placed.plan.selection.start, "end": placed.plan.selection.end}, "mix": "layer",
    }


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


@app.post("/projects/{project_id}/candidates/{candidate_id}/move")
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


@app.post("/projects/{project_id}/edits/{edit_id}/move")
def move_edit(
    project_id: str, edit_id: str, req: MoveRequest, owner: str = Depends(current_owner),
) -> dict:
    """A kept line, placed somewhere else: the old edit is reverted and the
    same take approved at the new place, in one step."""
    record = _owned(project_id, owner)
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id and not e.reverted), None)
    if edit is None:
        raise HTTPException(status_code=404, detail="edit not found")
    if edit.plan.mix == "remove":
        raise HTTPException(status_code=422, detail="A removal has no audio to move.")
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
        revert=lambda pid, edit_id: _revert(pid, edit_id, by="Voltage"),
        default_voice=lambda: getattr(voice, "default_voice", "speaker-1"),
        hear=_hear_levels, sight_text=_sight_text, now=_now,
        design=voice.design_voice if can_design else None, design_cost=design_cost,
        save_voice=voice.save_voice if can_design else None,
        add_from_library=getattr(voice, "add_from_library", None),
        delete_voice=getattr(voice, "delete_voice", None),
        slots=getattr(voice, "slots", lambda: None), put_audio=put_audio,
        speakers=repo.speakers, voice_for=_voice_for, remove_words=_remove_words, shift_words=_shift_words, move_take=_moved,
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


@app.post("/projects/{project_id}/turns", status_code=202)
def take_turn(project_id: str, req: TurnRequest, owner: str = Depends(current_owner)) -> dict:
    """One turn of Voltage with tools (Phase 20): the user's words go in, the
    agent looks, listens, voices and asks through its tools, and the job's
    result is the plan and Voltage's closing line. Steps appear as messages
    while it runs (`GET /projects/{id}/messages?after=`)."""
    record = _owned(project_id, owner)
    if not _agent_on():
        raise HTTPException(status_code=503, detail="Voltage needs Claude for this (set AVE_AGENT=1 and an Anthropic key).")
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say what you want.")
    if any(j.kind == "turn" and j.project_id == project_id and not j.done for j in jobs.all()):
        raise HTTPException(status_code=409, detail="Voltage is still on the last thing you said.")
    prefs = _settings(project_id)
    autonomy = prefs["autonomy"]
    plan = _turn_plan(project_id, text)
    # A yes to a gate question (a paid or committing step that waited): a go word, or its first option.
    gate = plan.question if plan.question and plan.question.get("gate") else None
    approve = req.approve or bool(gate and (is_go(text) or text.strip().lower() == str(gate["options"][0]).lower()))
    # Consent binds before anything synthesizes this speaker's voice: under
    # Just do it before the turn, under Check with me at the yes.
    if record.consent is None and (autonomy == "draft" or approve):
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    repo.add_message(project_id, "user", text)
    repo.update_plan(project_id, plan.plan_id, status="running", question=None)
    job = jobs.create("turn", project_id)
    started_at = _now()

    def work(report) -> dict:
        try:
            _ensure_spend(project_id)
        except SpendCeilingReached as exc:
            repo.update_plan(project_id, plan.plan_id, status="proposed")
            repo.add_message(project_id, "assistant", str(exc))
            return {"plan": _plan_dict(repo.get_plan(project_id, plan.plan_id)), "reply": str(exc), "question": None}
        budget_ = TurnBudget(usd=prefs["turn_usd"])
        turn = AgentTurn(project_id=project_id, record=record, plan_id=plan.plan_id, autonomy=autonomy,
                         spend_approved=approve or autonomy == "draft", budget=budget_, started_at=started_at,
                         report=report, commit_approved=approve)
        lines = _lines(record)
        names = [s.name for s in repo.speakers(project_id)]
        from app.agent.context import opening
        head = opening(repo.get_plan(project_id, plan.plan_id), duration=record.source.duration,
                       filename=record.source.filename, speakers=names, lines=len(lines), autonomy=autonomy,
                       spent_usd=ledger.spent_usd(project_id), ceiling_usd=ledger.ceiling_usd,
                       turn_usd=prefs["turn_usd"], sight=_sight_text(project_id) if not lines else "",
                       edits=[e for e in repo.list_edits(project_id) if not e.reverted])
        content = [{"type": "text", "text": head}, {"type": "text", "text": f"The user says: {text}"
                   + (" (They are answering yes to what you asked.)" if approve else "")}]
        history = repo.turns(project_id)

        def on_step(step: str, cost: float) -> None:
            repo.add_message(project_id, "assistant", step, kind="step", cost=cost or None)
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
        question = outcome.question
        status = "clarifying" if question else "done"
        if outcome.reply:
            repo.add_message(project_id, "assistant", outcome.reply)
        # What Voltage's own thinking cost this turn, as a step of its own (20d):
        # the tools say what they spent; this is the rest of the turn's money.
        thought = ledger.spent_usd_since(project_id, started_at, vendor="anthropic")
        if thought > 0:
            repo.add_message(project_id, "assistant", "Thinking", kind="step", cost=round(thought, 4))
        if question:
            repo.add_message(project_id, "assistant", question["text"])
            repo.append_log(project_id, plan.plan_id, f"Asked: {question['text']}")
        updated = repo.get_plan(project_id, plan.plan_id)
        repo.update_plan(project_id, plan.plan_id, status=status, question=question, summary=outcome.reply or updated.summary,
                         estimate=_estimate(project_id, updated.items))
        return {"type": "turn", "plan": _plan_dict(repo.get_plan(project_id, plan.plan_id)), "reply": outcome.reply,
                "question": question, "spent_usd": round(outcome.spent_usd, 4), "calls": outcome.calls,
                "stopped": outcome.stopped}

    def failed_turn() -> None:
        repo.update_plan(project_id, plan.plan_id, status="proposed")

    submitted = runner.submit(job, _guarded(work, failed_turn))
    return _job_dict(submitted)


def _guarded(work, on_fail):
    def run(report):
        try:
            return work(report)
        except Exception:
            on_fail()
            raise
    return run


@app.get("/projects/{project_id}/messages")
def list_messages(project_id: str, after: int = 0, owner: str = Depends(current_owner)) -> list[dict]:
    """The thread after a message (by `seq`): what Voltage said and did."""
    _owned(project_id, owner)
    return [_message_dict(m) for m in repo.messages(project_id, after)]
