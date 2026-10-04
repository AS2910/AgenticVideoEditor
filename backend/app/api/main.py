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
    Consent, EditPlan, Intent,
)
from app.domain.plan import Plan, PlanItem
from app.domain.transcript import (
    assign_speakers, room_after, room_before, snap_to_word_boundaries, speaker_of, statements_of,
)
from app.media.fit import speaking_rate, syllable_budget, syllables
from app.config import load_settings
from app.media import frames as frames_mod
from app.media import ffmpeg, ingest
from app.adapters.base import VendorError
from app.adapters.mock import MockLipSyncAdapter
from app.adapters.openai_whisper import TranscriptionError
from app.adapters.selection import (
    select_continuity, select_interpreter, select_planner, select_transcriber, select_voice,
)
from app.errors import NonRetryableError
from app.budget import VoiceBudget, BudgetExceeded
from app.orchestrator.intent import Turn, edit_context
from app.orchestrator.planner import ItemView, Line, Proposal, Question, Revision, MAX_QUESTIONS, Frame, Sight
from app.orchestrator.questions import fit_question, mix_question
from app.media.ffmpeg import SpanMismatch
from app.orchestrator.pipeline import run_edit
from app.store.db import Database
from app.usage import Ledger, SpendCeilingReached, WHISPER_USD_PER_MINUTE, claude_usd
from app import auth
from app.store.repository import ProjectRecord, ProjectRepository, LOCAL_OWNER
from app.store.artifacts import ArtifactStore
from app.render.renderer import render
from app.render.compose import compose
from app.jobs.store import JobStore, Job
from app.jobs.runner import JobRunner, with_retries

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
transcriber, transcriber_label = select_transcriber(settings)
voice, voice_label = select_voice(settings, artifacts, budget)
lipsync = MockLipSyncAdapter(artifacts)
continuity, continuity_label = select_continuity(voice.identity, artifacts)
interpreter, interpreter_label = select_interpreter(settings)
planner, planner_label = select_planner(settings)
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
        "lipsync": "mock",
        "continuity": continuity_label,
        "intent": interpreter_label,
        "planner": planner_label,
        "auth": settings.auth_mode,
    }


_MEDIA_TYPES = {"mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm",
                "wav": "audio/wav", "m4a": "audio/mp4"}


class EditRequest(BaseModel):
    prompt: str
    start: float
    end: float
    voice_profile_id: str = "speaker-1"
    # Set when answering a question: the line already read from the prompt,
    # so it is not read again (and cannot come back different).
    text: str | None = None
    fit: Literal["start", "stretch"] | None = None
    mix: Literal["replace", "layer", "concatenate", "over"] | None = None
    # How it is said (UX-1): one of DELIVERIES, or the user's own words.
    delivery: str | None = None
    # What the chat shows for this turn when it isn't the prompt itself — the
    # label of an option picked in answer to a question.
    display: str | None = None
    # What to do when the line runs longer than the selection (Phase 12):
    # "pause" runs it into the pause after the selection when there is room,
    # "stretch" speeds it up, "ask" asks. Unset = the project's setting.
    on_long: Literal["pause", "shorten", "stretch", "ask"] | None = None


# How a line longer than its selection is placed, unless the project says
# otherwise: into the pause after it, without asking, when there is room.
DEFAULT_LONG_LINES = "pause"
# How much the agent does on its own (Phase 13): "ask" shows the plan and
# waits for Run — the controlled default; "draft" voices it straight away.
DEFAULT_AUTONOMY = "ask"
# For the plan's time estimate: one line took ~15 s live with three takes.
SECONDS_PER_ITEM = 12
# Slack allowed when the overrun is judged against the pause: timings are
# Whisper's, and a line a few hundredths long is not worth a question.
PAUSE_SLACK = 0.05
# Phase 14: a long line may also start a little early, into the pause before
# it, when the pause after is not quite enough.
BORROW_BEFORE = 0.15


class ApproveRequest(BaseModel):
    candidate_id: str
    # Approve even though continuity failed. Explicit, per approval, and
    # recorded on the edit — never a default.
    override: bool = False


def _continuity_dict(report: ContinuityReport) -> dict:
    return {
        "voice_match": report.voice_match,
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
        },
        "audio": _artifact_dict(candidate.audio),
        "frames": _artifact_dict(candidate.frames),
        "continuity": _continuity_dict(candidate.continuity),
        "fit_notes": list(candidate.fit_notes),
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
        return Sight(**{**saved, "beats": tuple(saved.get("beats", ()))})
    frames = [Frame(at=f.at, path=str(f.path)) for f in _frames(record)]
    sight = planner.look(frames, record.source.duration, meter=_meter(project_id, "looking"))
    repo.set_settings(project_id, sight=asdict(sight))
    return sight


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


def _settings(project_id: str) -> dict:
    saved = repo.settings(project_id)
    return {
        "long_lines": saved.get("long_lines", DEFAULT_LONG_LINES),
        "autonomy": saved.get("autonomy", DEFAULT_AUTONOMY),
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
                "overridden": e.overridden,
                "reverted": e.reverted,
                "partner": e.partner,
            }
            for e in repo.list_edits(project_id)
        ],
        "messages": [{"role": m.role, "text": m.text} for m in repo.messages(project_id)],
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
    long_lines: Literal["pause", "shorten", "stretch", "ask"] | None = None
    autonomy: Literal["ask", "draft"] | None = None


@app.put("/projects/{project_id}/settings")
def update_settings(
    project_id: str, req: SettingsUpdate, owner: str = Depends(current_owner),
) -> dict:
    """Per-project preferences. `long_lines` is remembered from the first
    answer about a line that runs long: "pause" (run into the pause after it
    when there is room), "stretch", or "ask" each time."""
    _owned(project_id, owner)
    repo.set_settings(project_id, long_lines=req.long_lines, autonomy=req.autonomy)
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


@app.post("/projects/{project_id}/edits/preview", status_code=202)
def preview_edit(
    project_id: str, req: EditRequest, owner: str = Depends(current_owner),
) -> dict:
    """Start generation and hand back a job to poll.

    Generation takes minutes once lip-sync is a real vendor (design spec §7),
    so this cannot be a synchronous call.
    """
    record = _owned(project_id, owner)
    if record.consent is None:
        # Design spec §2/§7: non-negotiable, and this is the moment it binds —
        # the last point before anything synthesizes this speaker's voice.
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)

    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    context = edit_context(record.transcript, selection, record.source.duration)
    # The chat so far comes from the server's record, not the client.
    history = [Turn(m.role, m.text) for m in repo.messages(project_id)]
    repo.add_message(project_id, "user", req.display or req.prompt)
    candidate_id = repo.next_candidate_id(project_id)
    job = jobs.create("preview", project_id)

    meter = _meter(project_id, "intent")

    def work(report) -> dict:
        # No new paid work once the project has reached its spend ceiling.
        _ensure_spend(project_id)
        if req.text is not None:
            intent = Intent(action="speak", new_text=req.text)
        else:
            report(0.02, "Reading your request")
            intent = interpreter.interpret(req.prompt, history, context, meter=meter)
        if intent.action != "speak":
            repo.add_message(project_id, "assistant", intent.reply)
            return {"type": "reply", "text": intent.reply}

        # Replacing speech is the obvious reading of an edit over words; over
        # music or silence it is not, so the user is asked.
        mix = req.mix or intent.mix or ("replace" if context.has_speech else None)
        if mix is None:
            return _asked(mix_question(intent.new_text, context))

        voice_id = _voice_for(project_id, record, selection, req.voice_profile_id)
        try:
            candidate = _generate(
                project_id, record, candidate_id, selection, intent.new_text, voice_id,
                req.fit, mix, req.on_long, report, delivery=req.delivery,
            )
        except SpanMismatch as exc:
            if req.fit is not None:
                raise   # the user already chose a placement and it still fails
            return _asked(fit_question(
                intent.new_text, mix, exc.natural, exc.target,
                selection.start, record.source.duration,
            ))
        return _candidate_dict(candidate)

    def _asked(question: dict) -> dict:
        repo.add_message(project_id, "assistant", question["question"])
        return question

    runner.submit(job, work)
    return _job_dict(job)


def _meter(project_id: str, what: str):
    """Records a Claude call against the project, as `what` in the ledger."""
    def meter(model: str, input_tokens: int, output_tokens: int) -> None:
        ledger.record(project_id, "anthropic", what, input_tokens + output_tokens, "tokens",
                      claude_usd(model, input_tokens, output_tokens))
    return meter


def _voice_for(project_id: str, record: ProjectRecord, selection: Selection, requested: str,
               speaker: str | None = None) -> str:
    """A line in one speaker's words is spoken in that speaker's voice, if
    one is set; otherwise in the voice asked for. `speaker` names who says it
    when that is not the selection's speaker (an added line)."""
    speaker = speaker or speaker_of(record.transcript, selection)
    voices = {s.label: s.voice_id for s in repo.speakers(project_id)}
    return voices.get(speaker) or requested


# An added line can play over the picture only if the pause after its line
# can hold speech at all.
MIN_OVER_ROOM = 0.3


def _generate(
    project_id: str, record: ProjectRecord, candidate_id: str, selection: Selection,
    text: str, voice_id: str, fit: str | None, mix: str, on_long: str | None, report,
    delivery: str | None = None,
) -> EditCandidate:
    """One line through generation and continuity, placed by the project's
    long-line policy, saved as a candidate. Raises SpanMismatch when the line
    does not fit and the policy says to ask.

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
                                      None, "layer", "ask", report, delivery)
            except SpanMismatch:
                candidate = None
            if candidate is not None:
                return candidate
            report(0.1, "No room to play over the picture; holding it instead")
        return _generate(project_id, record, candidate_id, selection, text, voice_id,
                         fit, "concatenate", on_long, report, delivery)
    plan = EditPlan(selection, text, voice_id, fit=fit, mix=mix, delivery=delivery)
    cost = voice.cost_of(plan)
    if not budget.can_afford(project_id, cost):
        raise BudgetExceeded(cost, budget.remaining(project_id))

    def generate(plan: EditPlan) -> EditCandidate:
        return run_edit(
            candidate_id, plan, record.source, voice, lipsync, continuity, report,
            transcript=record.transcript,
            max_regenerations=settings.max_regenerations,
        )

    try:
        candidate = generate(plan)
    except SpanMismatch as exc:
        if plan.fit is not None:
            raise
        # A longer line is placed without asking when the project says how
        # (Phase 12). The take that did not fit is held by the adapter, so
        # placing it costs nothing more.
        policy = on_long or _settings(project_id)["long_lines"]
        placed, early = _long_line_fit(policy, exc, selection, record.transcript, record.source.duration)
        if early > 0:
            # Start a touch early, into the pause before the line.
            selection = Selection(selection.start - early, selection.end)
            plan = replace(plan, selection=selection)
        if placed is None and policy == "shorten" and exc.natural > exc.target:
            # Prefer a shorter wording: the agent's own fix, without asking.
            report(0.1, "Asking for a shorter line")
            shorter = _shorter_line(project_id, record, selection, text, exc.target / exc.natural)
            if shorter:
                report(0.12, "Voicing the shorter line")
                try:
                    candidate = generate(replace(plan, new_text=shorter))
                except SpanMismatch:
                    raise exc from None
                repo.save_candidate(project_id, candidate)
                return candidate
        if placed is None:
            raise
        report(0.1, "Placing the line")
        candidate = generate(replace(plan, fit=placed))
    # Retained so approval commits this exact candidate rather than re-running
    # generation, which real vendors would not reproduce byte-for-byte.
    repo.save_candidate(project_id, candidate)
    return candidate


def _shorter_line(project_id: str, record: ProjectRecord, selection: Selection,
                  text: str, share: float) -> str | None:
    """A shorter wording from the planner, or None (offline, or nothing better)."""
    names = {s.label: s.name for s in repo.speakers(project_id)}
    speaker = speaker_of(record.transcript, selection)
    context = edit_context(record.transcript, selection, record.source.duration)
    line = Line(0, selection.start, selection.end, names.get(speaker or ""), context.selected)
    try:
        return planner.shorten(text, share, line, meter=_meter(project_id, "wording"))
    except (VendorError, NonRetryableError):
        return None


def _long_line_fit(policy: str, exc: SpanMismatch, selection: Selection,
                   transcript, duration: float) -> tuple[str | None, float]:
    """How to place a line that ran long — (fit, seconds to start early) — or
    (None, 0) to ask the user.

    Only a *long* line is placed automatically — a short one always asks,
    since silence or a slowed line is a real choice. "stretch" speeds it up;
    "pause" lets it run into the pause after the selection if that pause (plus
    a little slack) can hold the overrun and the video does not end first;
    when it is not quite enough, up to BORROW_BEFORE of the pause before the
    line is used too (Phase 14).
    """
    if exc.natural <= exc.target or policy in ("ask", "shorten"):
        return None, 0.0
    if policy == "stretch":
        return "stretch", 0.0
    overrun = exc.natural - exc.target
    room = room_after(transcript, selection, duration)
    if selection.start + exc.natural > duration + PAUSE_SLACK:
        return None, 0.0
    if overrun <= room + PAUSE_SLACK:
        return "start", 0.0
    before = min(BORROW_BEFORE, room_before(transcript, selection))
    if overrun <= room + before + PAUSE_SLACK:
        return "start", round(min(before, max(0.0, overrun - room)), 3)
    return None, 0.0


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
    edit = next((e for e in repo.list_edits(project_id) if e.edit_id == edit_id), None)
    if edit is None or not repo.revert_edit(project_id, edit_id):
        raise HTTPException(status_code=404, detail="edit not found")
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
                repo.append_log(project_id, plan.plan_id, f"You undid the line at {_clock(item.selection.start)}")
    return {"edit_id": edit_id, "reverted": True}


class RewordRequest(BaseModel):
    start: float
    end: float
    # The user's own draft of the line so far, if they have started one.
    draft: str | None = None
    # What kind of rewording; the default is a tighter, more natural line.
    instruction: str | None = None


DEFAULT_REWORD = "so it is shorter and more natural, keeping its meaning and the speaker's tone"


@app.post("/projects/{project_id}/lines/reword")
def reword_line(
    project_id: str, req: RewordRequest, owner: str = Depends(current_owner),
) -> dict:
    """Ask Claude for a new wording of the line in a span (Phase 12, the
    hands-on editor's "Ask Voltage for wording"). Nothing is spoken: this is a
    text suggestion the user can edit before previewing. Needs the Claude
    interpreter; offline there is no one to ask."""
    record = _owned(project_id, owner)
    if getattr(interpreter, "identity", "rules") != "claude":
        raise HTTPException(
            status_code=503,
            detail="Wording suggestions need Claude. Set ANTHROPIC_API_KEY to turn them on.",
        )
    try:
        _ensure_spend(project_id)
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    context = edit_context(record.transcript, selection, record.source.duration)
    how = (req.instruction or "").strip() or DEFAULT_REWORD
    draft = (req.draft or "").strip()
    rate = speaking_rate(record.transcript, speaker_of(record.transcript, selection))
    room = room_after(record.transcript, selection, record.source.duration)
    budget = syllable_budget(rate, selection.end - selection.start + min(room, 1.0))
    limit = (f" It must be no more than {budget} syllables, so it can be spoken in the time "
             f"the line has (the original is {syllables(context.selected)}).")
    if draft and draft != context.selected:
        prompt = (f'The user has drafted this wording for the selected line: "{draft}". '
                  f"Improve the draft {how}.{limit} Reply with the full new line.")
    else:
        prompt = f"Rewrite the selected line {how}.{limit} Reply with the full new line."

    def meter(model: str, input_tokens: int, output_tokens: int) -> None:
        ledger.record(project_id, "anthropic", "wording", input_tokens + output_tokens, "tokens",
                      claude_usd(model, input_tokens, output_tokens))

    intent = interpreter.interpret(prompt, [], context, meter=meter)
    if intent.action != "speak" or not intent.new_text:
        raise HTTPException(status_code=422, detail=intent.reply or "Could not suggest a wording.")
    return {"text": intent.new_text, "selection": {"start": selection.start, "end": selection.end}}


@app.post("/projects/{project_id}/export")
def export_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    return _export(_owned(project_id, owner))


def _export(record: ProjectRecord) -> dict:
    project_id = record.source.project_id
    manifest = render(record.source, repo.list_edits(project_id))
    # Synchronous: the video is stream-copied and only the audio re-encoded,
    # so even a 3-minute source renders in seconds.
    with tempfile.TemporaryDirectory() as tmp:
        path = compose(
            record.source, manifest.segments, Path(tmp) / "export.mp4",
            inserts=manifest.inserts,
        )
        rendered = artifacts.put_file(
            project_id, path, kind="video", container="mp4",
            duration=ffmpeg.duration_of(path),
        )
    return {
        "render": _artifact_dict(rendered),
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
            {"at": i.at, "duration": i.duration, "artifact": _artifact_dict(i.edit.audio)}
            for i in manifest.inserts
        ],
    }


# ── Phase 13: the agent ──────────────────────────────────────────────────────

class PlanRequest(BaseModel):
    goal: str
    # Overrides the project's autonomy setting for this plan.
    mode: Literal["ask", "draft"] | None = None
    # UX-5: the voice a line placed on a silent clip is spoken in (the chat's default voice).
    voice_profile_id: str | None = None


class ItemUpdate(BaseModel):
    enabled: bool | None = None
    new_text: str | None = None
    delivery: str | None = None
    mix: Literal["replace", "over", "concatenate"] | None = None
    # For a suggestion: True adds it to the plan, False leaves it.
    include: bool | None = None


class RunRequest(BaseModel):
    items: list[str] | None = None


class AnswerRequest(BaseModel):
    fit: Literal["start", "stretch"] | None = None
    mix: Literal["replace", "layer", "concatenate"] | None = None
    # The agent's own fix, or the user's: a different wording.
    text: str | None = None


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
        "questions_left": max(0, MAX_QUESTIONS - len(plan.answers)) if plan.question else 0,
        "voice": plan.voice,
        "spend_usd": round(ledger.spent_usd_since(plan.project_id, plan.created_at), 4) if plan.created_at else 0.0,
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


def _items_of(proposal: Proposal, statements, names: dict[str, str] | None = None,
              duration: float | None = None) -> tuple[PlanItem, ...]:
    """`names` maps a speaker's display name (lower-cased) to their label, so a
    change that names who says it lands on the right person. A change placed
    by time (UX-5) becomes an item on its own span, with nothing to replace."""
    names = names or {}
    items: list[PlanItem] = []
    for kind, changes in (("planned", proposal.edits), ("suggestion", proposal.suggestions)):
        for change in changes:
            if change.placed:
                end = min(change.end, duration) if duration else change.end
                if end <= change.start:
                    continue
                items.append(PlanItem(
                    item_id=f"i{len(items) + 1}", selection=Selection(round(change.start, 2), round(end, 2)),
                    old_text="", new_text=change.new_text, speaker=None,
                    mix="concatenate" if change.mix == "concatenate" else "layer",
                    reason=change.reason, kind=kind,
                    enabled=kind == "planned", status="planned" if kind == "planned" else "suggested",
                ))
                continue
            if not 1 <= change.line <= len(statements):
                continue
            st = statements[change.line - 1]
            speaker = names.get((change.speaker or "").lower(), st.speaker)
            items.append(PlanItem(
                item_id=f"i{len(items) + 1}", selection=Selection(st.start, st.end),
                old_text=st.text, new_text=change.new_text, speaker=speaker,
                mix=change.mix, reason=change.reason, kind=kind,
                enabled=kind == "planned", status="planned" if kind == "planned" else "suggested",
            ))
    return tuple(items)


@app.post("/projects/{project_id}/plans")
def create_plan(project_id: str, req: PlanRequest, owner: str = Depends(current_owner)) -> dict:
    """Plan edits across the whole video from a goal. Under "draft" the plan
    is voiced straight away and the job to poll is returned with it; under
    "ask" nothing is voiced or charged until Run."""
    record = _owned(project_id, owner)
    goal = req.goal.strip()
    if not goal:
        raise HTTPException(status_code=422, detail="Say what the video should say.")
    return _new_plan(project_id, record, goal, req.mode, req.voice_profile_id)


def _new_plan(project_id: str, record: ProjectRecord, goal: str, mode: str | None,
              voice_id: str | None = None) -> dict:
    lines = _lines(record)
    # UX-5: a clip with no speech is planned from what the picture shows.
    silent = not lines
    try:
        _ensure_spend(project_id)
        sight = _sight(project_id, record) if silent else None
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    mode = mode or _settings(project_id)["autonomy"]
    if mode == "draft" and record.consent is None:
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    earlier = repo.latest_plan(project_id)
    history = [earlier.goal] if earlier else []
    repo.add_message(project_id, "user", goal)
    try:
        if silent:
            proposal = planner.plan(goal, [], history, meter=_meter(project_id, "planning"),
                                    sight=sight, duration=record.source.duration)
        else:
            proposal = planner.plan(goal, lines, history, meter=_meter(project_id, "planning"))
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    plan = Plan(
        plan_id=repo.next_plan_id(project_id), project_id=project_id, goal=goal,
        summary=proposal.summary, items=(), mode=mode, status="proposed", created_at=_now(),
        voice=voice_id,
    )
    repo.save_plan(plan)
    repo.append_log(project_id, plan.plan_id,
                    "Looked at the picture and read your goal" if silent else f"Read your goal and all {len(lines)} lines",
                    "Claude" if planner_label.startswith("anthropic") else "")
    return _take_proposal(project_id, record, plan.plan_id, proposal, mode)


def _take_proposal(project_id: str, record: ProjectRecord, plan_id: str, proposal: Proposal, mode: str) -> dict:
    """Store what the planner proposed. With a question open, the plan waits
    as "clarifying" (the items are kept, built on the planner's guess); else it
    is proposed, and under "draft" it starts running."""
    names = {s.name.lower(): s.label for s in repo.speakers(project_id)}
    items = _items_of(proposal, statements_of(record.transcript), names, record.source.duration)
    planned = [i for i in items if i.kind == "planned"]
    speakers = {i.speaker for i in planned if i.speaker}
    question = ({"text": proposal.question.text, "options": list(proposal.question.options),
                 "guess": proposal.question.guess} if proposal.question else None)
    plan = repo.update_plan(
        project_id, plan_id, summary=proposal.summary, items=items, findings=proposal.findings,
        question=question, status="clarifying" if question else "proposed",
        estimate=_estimate(project_id, items),
    )
    if question:
        repo.append_log(project_id, plan_id, f"Asked: {question['text']}")
        repo.add_message(project_id, "assistant", question["text"])
        return _plan_dict(repo.get_plan(project_id, plan_id))
    repo.append_log(project_id, plan_id,
                    f"Planned {len(planned)} {'change' if len(planned) == 1 else 'changes'}"
                    + (f" across {len(speakers)} speakers" if len(speakers) > 1 else ""))
    repo.add_message(project_id, "assistant", proposal.summary)
    out = _plan_dict(repo.get_plan(project_id, plan_id))
    if mode == "draft" and plan.runnable:
        job = _run_plan(project_id, record, plan_id, [i.item_id for i in plan.runnable])
        out["job_id"] = job.job_id
        out["status"] = "running"
    return out


class ClarifyRequest(BaseModel):
    # One of the question's options, or the user's own words. Empty = the guess.
    answer: str | None = None
    # UX-5: take the planner's guess for this and every further question.
    all_guesses: bool = False


@app.post("/projects/{project_id}/plans/{plan_id}/clarify")
def clarify_plan(
    project_id: str, plan_id: str, req: ClarifyRequest, owner: str = Depends(current_owner),
) -> dict:
    """Answer the planner's question; it plans again with the answer."""
    record = _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    if not plan.question:
        raise HTTPException(status_code=409, detail="This plan has no open question.")
    answer = (req.answer or "").strip() or plan.question.get("guess") or plan.question["options"][0]
    repo.add_message(project_id, "user", answer)
    repo.append_log(project_id, plan_id, f"You said: {answer}")
    lines = _lines(record)
    silent = not lines
    answers = plan.answers + ((plan.question["text"], answer),)
    try:
        _ensure_spend(project_id)
        if silent:
            # UX-5, the brief: the planner may ask again, one question at a
            # time, up to MAX_QUESTIONS; "Go with your guesses" answers the
            # rest with its own guesses.
            sight = _sight(project_id, record)
            while True:
                proposal = planner.plan(plan.goal, [], [], meter=_meter(project_id, "planning"),
                                        answer=answers[-1], sight=sight, duration=record.source.duration,
                                        answers=answers)
                if proposal.question is None or len(answers) >= MAX_QUESTIONS:
                    break
                if not req.all_guesses:
                    break
                guess = proposal.question.guess or (proposal.question.options[0] if proposal.question.options else "")
                repo.append_log(project_id, plan_id, f"Asked: {proposal.question.text} — went with its guess: {guess}")
                answers = answers + ((proposal.question.text, guess),)
            if proposal.question is not None and len(answers) >= MAX_QUESTIONS:
                proposal = replace(proposal, question=None)
        else:
            proposal = planner.plan(plan.goal, lines, [], meter=_meter(project_id, "planning"),
                                    answer=(plan.question["text"], answer))
            # On a clip with speech, asking twice is not allowed: a second question is dropped, the guess stands.
            proposal = replace(proposal, question=None) if proposal.question else proposal
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    repo.update_plan(project_id, plan_id, answers=answers)
    return _take_proposal(project_id, record, plan_id, proposal, plan.mode)


@app.get("/projects/{project_id}/plans/{plan_id}")
def get_plan(project_id: str, plan_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned(project_id, owner)
    return _plan_dict(_plan_or_404(project_id, plan_id))


def _plan_or_404(project_id: str, plan_id: str) -> Plan:
    plan = repo.get_plan(project_id, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="plan not found")
    return plan


@app.put("/projects/{project_id}/plans/{plan_id}/items/{item_id}")
def update_item(
    project_id: str, plan_id: str, item_id: str, req: ItemUpdate,
    owner: str = Depends(current_owner),
) -> dict:
    """Before (or between) runs: untick an item, reword it, or add / leave a
    suggestion. Rewording a voiced item sends it back to planned."""
    _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    item = plan.item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    changes: dict = {}
    if req.include is True and item.kind == "suggestion":
        changes.update(kind="planned", enabled=True, status="planned")
        repo.append_log(project_id, plan_id, f"You added the suggestion at {_clock(item.selection.start)}")
    elif req.include is False:
        # Leave it — also for a suggestion that was added and thought better of.
        changes.update(kind="suggestion", enabled=False, status="dismissed")
    if req.enabled is not None:
        changes["enabled"] = req.enabled
    if req.delivery is not None:
        changes["delivery"] = req.delivery.strip() or None
        if item.status in ("ready", "needs-you", "failed"):
            changes.update(status="planned", candidate_id=None, question=None, error=None)
    if req.mix is not None and item.mix != "replace":
        changes["mix"] = req.mix
        if item.status in ("ready", "needs-you", "failed"):
            changes.update(status="planned", candidate_id=None, question=None, error=None)
    if req.new_text is not None:
        text = req.new_text.strip()
        if not text:
            raise HTTPException(status_code=422, detail="The new wording is empty.")
        if text != item.new_text:
            changes.update(new_text=text, fit=None, note="Your wording")
            if item.status in ("ready", "needs-you", "failed"):
                changes.update(status="planned", candidate_id=None, question=None, error=None)
    updated = repo.update_item(project_id, plan_id, item_id, **changes)
    updated = repo.update_plan(project_id, plan_id, estimate=_estimate(project_id, updated.items),
                               status=_status_after_edit(updated))
    return _plan_dict(updated)


def _status_after_edit(plan: Plan) -> str:
    """A finished plan with something planned again waits for Go ahead."""
    if plan.status == "done" and plan.runnable:
        return "proposed"
    return plan.status


# ── UX-2: revise the plan in words, and stop it ──────────────────────────────

class ReviseRequest(BaseModel):
    instruction: str


@app.post("/projects/{project_id}/plans/{plan_id}/revise")
def revise_plan(
    project_id: str, plan_id: str, req: ReviseRequest, owner: str = Depends(current_owner),
) -> dict:
    """Change the plan in your own words — "not the second one", "warmer at
    0:17", "shorter" — applied to the plan in place, so the takes already
    voiced survive. A new goal altogether makes a new plan instead."""
    record = _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    instruction = req.instruction.strip()
    if not instruction:
        raise HTTPException(status_code=422, detail="Say what to change about the plan.")
    if plan.status in ("running", "stopping"):
        raise HTTPException(status_code=409, detail="Stop the plan first, or wait for it to finish.")
    lines = _lines(record)
    statements = statements_of(record.transcript)
    names = {s.label: s.name for s in repo.speakers(project_id)}
    views = [
        ItemView(i.item_id, _line_index(statements, i.selection), i.old_text, i.new_text, i.mix, i.delivery,
                 i.enabled, i.status, names.get(i.speaker or ""))
        for i in plan.items if i.kind == "planned" or i.status == "suggested"
    ]
    repo.add_message(project_id, "user", instruction)
    try:
        _ensure_spend(project_id)
        revision = planner.revise(instruction, views, lines, plan.goal, meter=_meter(project_id, "planning"))
    except SpendCeilingReached as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc
    except NonRetryableError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except VendorError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if revision.new_goal:
        return _new_plan(project_id, record, instruction, plan.mode)
    repo.append_log(project_id, plan_id, f"You said: {instruction}")
    touched = _apply_revision(project_id, record, plan, revision)
    repo.add_message(project_id, "assistant", revision.summary)
    repo.append_log(project_id, plan_id, revision.summary if touched else "Nothing in the plan changed")
    updated = repo.get_plan(project_id, plan_id)
    updated = repo.update_plan(project_id, plan_id, summary=revision.summary,
                               estimate=_estimate(project_id, updated.items),
                               status=_status_after_edit(updated))
    return _plan_dict(updated)


def _line_index(statements, selection: Selection) -> int:
    for n, st in enumerate(statements):
        if abs(st.start - selection.start) < 0.05:
            return n + 1
    return 0


def _apply_revision(project_id: str, record: ProjectRecord, plan: Plan, revision: Revision) -> int:
    """Apply a revision to the plan's items in place. Returns how many items
    changed. An item whose words, placement or delivery change goes back to
    planned (its take no longer says what it should); one merely left out or
    put back keeps its take."""
    touched = 0
    for change in revision.changes:
        item = plan.item(change.item_id)
        if item is None:
            continue
        changes: dict = {}
        revoice = False
        if change.enabled is not None and change.enabled != item.enabled:
            changes["enabled"] = change.enabled
            if item.kind == "suggestion" and change.enabled:
                changes.update(kind="planned", status="planned")
        if change.new_text and change.new_text != item.new_text:
            changes.update(new_text=change.new_text, fit=None, note="Reworded as you asked")
            revoice = True
        if change.mix and item.mix != "replace" and change.mix != item.mix:
            changes["mix"] = change.mix
            revoice = True
        if change.clear_delivery and item.delivery:
            changes["delivery"] = None
            revoice = True
        elif change.delivery and change.delivery != item.delivery:
            changes["delivery"] = change.delivery
            revoice = True
        if revoice and item.status in ("ready", "needs-you", "failed"):
            changes.update(status="planned", candidate_id=None, question=None, error=None)
        if changes:
            repo.update_item(project_id, plan.plan_id, item.item_id, **changes)
            touched += 1
    if revision.additions:
        statements = statements_of(record.transcript)
        by_name = {s.name.lower(): s.label for s in repo.speakers(project_id)}
        current = repo.get_plan(project_id, plan.plan_id)
        new_items = list(current.items)
        for change in revision.additions:
            if not 1 <= change.line <= len(statements):
                continue
            st = statements[change.line - 1]
            new_items.append(PlanItem(
                item_id=f"i{len(new_items) + 1}", selection=Selection(st.start, st.end), old_text=st.text,
                new_text=change.new_text, speaker=by_name.get((change.speaker or "").lower(), st.speaker),
                mix=change.mix, reason=change.reason, kind="planned", enabled=True, status="planned",
            ))
            touched += 1
        repo.update_plan(project_id, plan.plan_id, items=tuple(new_items))
    return touched


# Plans asked to stop: checked by the running job between lines.
_stops: set[str] = set()


@app.post("/projects/{project_id}/plans/{plan_id}/stop")
def stop_plan(project_id: str, plan_id: str, owner: str = Depends(current_owner)) -> dict:
    """Stop a running plan after the line it is on. What is done stays done;
    the rest waits as planned, for Go ahead later."""
    _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    if plan.status != "running":
        raise HTTPException(status_code=409, detail="The plan is not running.")
    _stops.add(plan_id)
    repo.append_log(project_id, plan_id, "You stopped the plan")
    return _plan_dict(repo.update_plan(project_id, plan_id, status="stopping"))


def _clock(t: float) -> str:
    return f"{int(t // 60)}:{int(t % 60):02d}"


def _placement_note(candidate: EditCandidate, selection: Selection) -> str | None:
    overrun = candidate.plan.selection.end - selection.end
    if candidate.plan.mix != "concatenate" and overrun > 0.01:
        return f"Ran {overrun:.1f} s into the pause after it"
    return None


def _agent_fix(project_id: str, record: ProjectRecord, item: PlanItem, exc: SpanMismatch, report) -> dict:
    """The question for a line that does not fit — with the agent's own fix,
    a shorter wording, offered first when the line runs long."""
    question = fit_question(
        item.new_text, item.mix, exc.natural, exc.target, item.selection.start, record.source.duration,
    )
    if exc.natural > exc.target:
        room = room_after(record.transcript, item.selection, record.source.duration)
        over = exc.natural - exc.target
        where = ("there's no pause after it to run into" if room < PAUSE_SLACK
                 else f"the pause after it is only {room:.1f} s")
        question["question"] = f"The new line runs {over:.1f} s long and {where}."
        report(0.5, "Asking for a shorter line")
        names = {s.label: s.name for s in repo.speakers(project_id)}
        line = Line(0, item.selection.start, item.selection.end, names.get(item.speaker or ""), item.old_text)
        try:
            shorter = planner.shorten(item.new_text, exc.target / exc.natural, line,
                                      meter=_meter(project_id, "wording"))
        except (VendorError, NonRetryableError):
            shorter = None
        if shorter:
            question["options"].insert(0, {
                "label": f"Use a shorter line: “{shorter}”", "fit": None, "mix": None,
                "warning": None, "text": shorter,
            })
    return question


def _run_plan(project_id: str, record: ProjectRecord, plan_id: str, item_ids: list[str]) -> Job:
    """One job voicing several items, each with its own status."""
    job = jobs.create("plan", project_id)
    repo.update_plan(project_id, plan_id, status="running")

    def work(report) -> dict:
        plan = repo.get_plan(project_id, plan_id)
        targets = [i for i in plan.items if i.item_id in item_ids and i.kind == "planned" and i.enabled]
        total = max(1, len(targets))
        for n, item in enumerate(targets):
            if plan_id in _stops:
                _stops.discard(plan_id)
                left = len(targets) - n
                repo.append_log(project_id, plan_id,
                                f"Stopped with {left} {'line' if left == 1 else 'lines'} still planned")
                break
            repo.update_item(project_id, plan_id, item.item_id, status="working", error=None)
            base = n / total

            def step(progress: float, text: str, n=n, base=base, item_id=item.item_id) -> None:
                report(base + progress / total, f"{n + 1} of {total}: {text}")
                repo.update_item(project_id, plan_id, item_id, progress=text)

            step(0.05, "Synthesizing the new line")
            try:
                _ensure_spend(project_id)
                voice_id = _voice_for(project_id, record, item.selection,
                                      plan.voice or getattr(voice, "default_voice", "speaker-1"),
                                      speaker=item.speaker)
                candidate_id = repo.next_candidate_id(project_id)
                candidate = with_retries(lambda: _generate(
                    project_id, record, candidate_id, item.selection, item.new_text, voice_id,
                    item.fit, item.mix, None, step, delivery=item.delivery,
                ))
            except SpanMismatch as exc:
                question = _agent_fix(project_id, record, item, exc, step)
                repo.update_item(project_id, plan_id, item.item_id, status="needs-you", question=question,
                                 progress=None)
                repo.append_log(project_id, plan_id,
                                f"Needs you: the line at {_clock(item.selection.start)} does not fit")
                continue
            except (BudgetExceeded, SpendCeilingReached) as exc:
                repo.update_item(project_id, plan_id, item.item_id, status="failed", error=str(exc), progress=None)
                repo.append_log(project_id, plan_id, "Stopped: the project's budget is used up")
                break
            except NonRetryableError as exc:
                repo.update_item(project_id, plan_id, item.item_id, status="failed", error=str(exc), progress=None)
                continue
            except VendorError:
                repo.update_item(project_id, plan_id, item.item_id, status="failed", progress=None,
                                 error="Generation failed after several attempts. Redo to try again.")
                continue
            retried = next((w for w in candidate.continuity.warnings if w.startswith("Regenerated")), None)
            takes = 1 + (int(retried.split()[1].rstrip("×")) if retried else 0)
            cost = voice.cost_of(candidate.plan)
            shortened = candidate.plan.new_text != item.new_text
            held = item.mix == "over" and candidate.plan.mix == "concatenate"
            repo.update_item(project_id, plan_id, item.item_id, status="ready", candidate_id=candidate_id,
                             question=None, error=None, progress=None,
                             new_text=candidate.plan.new_text,
                             note=("Shortened to fit" if shortened else None)
                             or ("Held the picture: no room to play over it" if held else None)
                             or ("Plays over the picture" if item.mix == "over" else None)
                             or _placement_note(candidate, item.selection) or item.note)
            repo.append_log(project_id, plan_id,
                            f"Voiced the line at {_clock(item.selection.start)}"
                            + (f" ({retried.rstrip('.').lower()})" if retried else ""),
                            f"{cost * takes} characters" if cost else "")
        _stops.discard(plan_id)
        plan = repo.get_plan(project_id, plan_id)
        still = any(i.status == "working" for i in plan.items)
        # Stopped, or a line left planned: the plan waits for Go ahead again.
        status = "running" if still else "proposed" if plan.runnable else "done"
        repo.update_plan(project_id, plan_id, status=status)
        return _plan_dict(repo.get_plan(project_id, plan_id))

    runner.submit(job, work)
    return job


@app.post("/projects/{project_id}/plans/{plan_id}/run", status_code=202)
def run_plan(
    project_id: str, plan_id: str, req: RunRequest, owner: str = Depends(current_owner),
) -> dict:
    """Voice the ticked items (or the ones named). Returns the job to poll;
    the plan itself shows each item's status as it goes."""
    record = _owned(project_id, owner)
    if record.consent is None:
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    plan = _plan_or_404(project_id, plan_id)
    if plan.status == "clarifying":
        raise HTTPException(status_code=409, detail="Answer Voltage's question first (or take its guess).")
    if plan.status in ("running", "stopping"):
        raise HTTPException(status_code=409, detail="The plan is already running.")
    ids = req.items or [i.item_id for i in plan.runnable]
    if not ids:
        raise HTTPException(status_code=422, detail="Nothing is ticked to run.")
    return _job_dict(_run_plan(project_id, record, plan_id, ids))


@app.post("/projects/{project_id}/plans/{plan_id}/items/{item_id}/answer", status_code=202)
def answer_item(
    project_id: str, plan_id: str, item_id: str, req: AnswerRequest,
    owner: str = Depends(current_owner),
) -> dict:
    """Answer a needs-you item — the agent's shorter line, a different
    wording, or how to place it — and voice it again."""
    record = _owned(project_id, owner)
    if record.consent is None:
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    plan = _plan_or_404(project_id, plan_id)
    item = plan.item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    changes: dict = {"question": None, "status": "planned", "error": None}
    if req.text:
        changes.update(new_text=req.text.strip(), fit=None, note="The shorter line you picked")
        repo.append_log(project_id, plan_id, f"You picked the shorter line at {_clock(item.selection.start)}")
    else:
        changes.update(fit=req.fit)
        repo.append_log(project_id, plan_id,
                        f"You chose how to place the line at {_clock(item.selection.start)}")
    if req.mix:
        changes["mix"] = req.mix
    repo.update_item(project_id, plan_id, item_id, **changes)
    return _job_dict(_run_plan(project_id, record, plan_id, [item_id]))


@app.post("/projects/{project_id}/plans/{plan_id}/items/{item_id}/redo", status_code=202)
def redo_item(
    project_id: str, plan_id: str, item_id: str, owner: str = Depends(current_owner),
) -> dict:
    """Another take of one item."""
    record = _owned(project_id, owner)
    if record.consent is None:
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    plan = _plan_or_404(project_id, plan_id)
    item = plan.item(item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="item not found")
    repo.update_item(project_id, plan_id, item_id, status="planned", candidate_id=None,
                     question=None, error=None, enabled=True)
    repo.append_log(project_id, plan_id, f"Redoing the line at {_clock(item.selection.start)}")
    return _job_dict(_run_plan(project_id, record, plan_id, [item_id]))


@app.post("/projects/{project_id}/plans/{plan_id}/approve")
def approve_plan(
    project_id: str, plan_id: str, req: PlanApproveRequest, owner: str = Depends(current_owner),
) -> dict:
    """Approve every ready item (or the ones named) and render. An item whose
    take failed continuity is skipped unless `override` is set."""
    record = _owned(project_id, owner)
    plan = _plan_or_404(project_id, plan_id)
    approved, skipped = [], []
    for item in plan.items:
        if item.status != "ready" or (req.items and item.item_id not in req.items):
            continue
        candidate = repo.get_candidate(project_id, item.candidate_id or "")
        if candidate is None:
            skipped.append({"item_id": item.item_id, "reason": "no take to approve"})
            continue
        overridden = not candidate.continuity.passed
        if overridden and not req.override:
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
    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    length = selection.end - selection.start
    from app.continuity import signals
    from app.continuity.measured import _write_wav
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "room.wav"
        _write_wav(path, _room_tone(record, length), signals.RATE)
        audio = artifacts.put_file(project_id, path, kind="audio", container="wav", duration=length)
    candidate_id = repo.next_candidate_id(project_id)
    candidate = EditCandidate(
        candidate_id=candidate_id,
        plan=EditPlan(selection, "", "none", mix="remove"),
        audio=audio, frames=record.source.media,
        continuity=ContinuityReport(None, None, None, None, True, (), ()),
    )
    repo.save_candidate(project_id, candidate)
    edit_id = _approve_candidate(project_id, candidate, overridden=False)
    repo.add_message(project_id, "user", f"Removed the line at {_clock(selection.start)}")
    return {
        "edit_id": edit_id, "candidate_id": candidate_id,
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
    source = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    duration = record.source.duration
    to = round(min(max(0.0, req.to), duration), 3)
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
    repo.add_message(project_id, "user", f"Moved the line at {_clock(source.start)} to {_clock(to)}")
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
    return _candidate_dict(_moved(project_id, record, source, req.start, req.mix))


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
