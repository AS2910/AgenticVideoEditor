import asyncio
import io
import contextlib
import json
import zipfile
import re
import queue
import time
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
import logging
import tempfile
from contextvars import ContextVar
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import shutil
from urllib.parse import quote
from types import SimpleNamespace

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
from app.media import ffmpeg, ingest, sniff
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
from app.store.db import Database, location as database_location
from app.flags import FlagStore
from app import analytics, dataexport, errors_report
from app.safety import figures as figures_mod, liveness as liveness_mod, provenance as provenance_mod
from app.purge import PurgeScheduler
from app.usage import (
    Ledger, SpendCeilingReached, WHISPER_USD_PER_MINUTE, claude_usd, current_actor, current_turn, money, month_name, month_start,
)
from app import auth
from app import linkimport
import httpx
from app.store.workspaces import personal
from app.store import briefs, checks as checks_store, events as activity_log, rules, stages
from app.store import shares as shares_store, presets as presets_store, languages as langs
from app.store import comments as comments_store
from app.store import bin as bin_store
from app.store import home as home_store
from app.store import templates as templates_store
from app.store import learned as learned_store
from app.store import members as members_store
from app.notify import inbox
from app.notify import digest as digest_mod, email as email_mod
from starlette.concurrency import run_in_threadpool
from app.render import captions as captions_mod, deliver as deliver_mod
from app.jobs import exports as exports_mod
from app.agent import project_check as pcheck
from app.adapters import pronounce
from app.adapters.elevenlabs import vendor_context
from app.store.actors import VOLTAGE, Actor, user as user_actor
from app.store.repository import Project, ProjectRecord, ProjectRepository, LOCAL_OWNER
from app.store.artifacts import ArtifactStore
from app.render.renderer import render
from app.render.compose import compose
from app.render import retime
from app.jobs.store import JobStore, Job
from app.jobs.runner import JobRunner
from app.jobs.activity import ActivityJobs, KINDS as JOB_KINDS
from app.jobs import batch as batch_mod
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

# Media lands under `backend/var/artifacts` unless AVE_DATA_DIR overrides it
# (tests point that at a temp dir; deployment points it at real storage).
settings = load_settings()
# Launch item 2: in production a missing secret stops the start, all named at once.
from app.config import ensure_production_ready  # noqa: E402
ensure_production_ready(settings)

# No API docs in production (they list every route); never debug pages.
app = FastAPI(title="Agentic Video Editor", debug=False,
              **({"docs_url": None, "redoc_url": None, "openapi_url": None} if settings.production else {}))
log = logging.getLogger(__name__)

# Wiring (module-level singletons for this in-memory slice).
database = Database(database_location(settings.data_dir / "ave.db"))
repo = ProjectRepository(database)
# Step 0 (FLAGS): every phase of the projects plan ships behind a flag, on per owner.
flags = FlagStore(database, settings.flag_owners, settings.launch_profile)
# G7: every tracked step lands in this database's analytics_events.
analytics.configure(database)
# G8: the error-reporting hook (log provider; SENTRY_DSN is read but not connected).
error_reporter = errors_report.reporter_for(settings.sentry_dsn, database)
# G6: trust and safety behind interfaces, all fake (SETUP_NEEDED.md): liveness
# for consent, the public-figure check on the clone path, and an invisible
# watermark and a C2PA-style manifest on every export.
def _recording_seconds(path: Path) -> float:
    """How long a recording is, decoded (a browser's WebM often has no duration in its header)."""
    with tempfile.TemporaryDirectory() as tmp:
        return ffmpeg.extract_audio(path, Path(tmp) / "a.wav", sample_rate=16000)[1]


liveness = liveness_mod.FakeLiveness(_recording_seconds)
public_figures = figures_mod.ListCheck()
watermarker = provenance_mod.FakeWatermarker()
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
# AVE_JOB_WORKERS (default 16, rehearsal item 3, LOAD.md): at four, 50 people's turns queued for two
# minutes behind each other. A batch (F4) still runs three videos' turns at a time.
runner = JobRunner(jobs, max_workers=settings.job_workers)
# 2026-10-20 (one processing model): every piece of work the user waits on is
# an Activity job, persisted; the editor hears each change on its live channel.
events = EventBus()
def _on_job(j) -> None:
    events.publish(j.video_id, "job.updated", j.to_dict())
    notice = globals().get("_job_notice")      # G4, defined further down
    if notice is not None and j.done:
        notice(j)


activity = ActivityJobs(database, on_change=_on_job)
activity.interrupt_leftovers()
# Renders and retries started from the editor run here, off the request thread
# and apart from the turns' pool, so a long turn never holds a preview back.
work_pool = ThreadPoolExecutor(max_workers=settings.work_workers, thread_name_prefix="ave-work")
# Phase 9c: who signs people in. None while AVE_AUTH=off.
oidc: auth.Provider | None = (
    auth.GoogleProvider(settings.google_client_id or "", settings.google_client_secret or "")
    if settings.auth_mode == "google" else None
)


# ── Launch item 4: readiness ─────────────────────────────────────────────────
# /health says the process is up (and which vendors are real); /ready says it
# can take traffic: the database answers, every migration is applied, the data
# dir takes writes, ffmpeg runs. A load balancer sends traffic only on 200.

def _check_database() -> None:
    with database.tx() as c:
        c.execute("SELECT 1").fetchone()


def _check_migrations() -> None:
    from app.store import migrate
    with database.tx() as c:
        missing = [m["version"] for m in migrate.status(c) if not m["applied_at"]]
    if missing:
        raise RuntimeError(f"{len(missing)} migrations not applied")


def _check_storage() -> None:
    probe = settings.data_dir / ".ready-probe"
    probe.write_text("ok")
    probe.unlink()


def _check_ffmpeg() -> None:
    if not ffmpeg.available():
        raise RuntimeError("ffmpeg is not installed")


@app.get("/ready")
def ready() -> JSONResponse:
    checks = []
    for name, check in (("database", _check_database), ("migrations", _check_migrations),
                        ("storage", _check_storage), ("ffmpeg", _check_ffmpeg)):
        try:
            check()
            checks.append({"name": name, "ok": True})
        except Exception as exc:  # noqa: BLE001 - a failed check is reported, never raised
            log.error("readiness check %s failed: %s", name, exc)
            checks.append({"name": name, "ok": False})
    ok = all(c["ok"] for c in checks)
    return JSONResponse(status_code=200 if ok else 503, content={"ready": ok, "checks": checks})


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
    # C1: yes to "This video is Approved. Adding this moves it back to Draft."
    confirm_stage: bool = False


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


# Launch item 2: what each kind of upload may weigh (a video's cap is ingest.MAX_SOURCE_BYTES).
MAX_AUDIO_UPLOAD_BYTES = 100 << 20


def _too_big(kind: str) -> str:
    if kind == "video":
        return (f"That video is over {_size(ingest.MAX_SOURCE_BYTES)}. Videos can be up to {_size(ingest.MAX_SOURCE_BYTES)} "
                f"and {int(ingest.MAX_SOURCE_SECONDS // 60)} minutes.")
    return f"That recording is over {_size(MAX_AUDIO_UPLOAD_BYTES)}. A minute or two of clear speech is plenty."


def _size(n: int) -> str:
    return f"{n / (1 << 30):g} GB" if n >= 1 << 30 else f"{n >> 20} MB"


async def _spool(upload: UploadFile, dest: Path, kind: str = "video") -> str:
    """Stream an upload to disk, refusing too large a file and, from its first
    bytes, anything that is not the kind asked for (`video`, `audio`).
    Returns the format the bytes say it is."""
    cap = ingest.MAX_SOURCE_BYTES if kind == "video" else MAX_AUDIO_UPLOAD_BYTES
    written, found = 0, ""
    with dest.open("wb") as out:
        while chunk := await upload.read(1 << 20):
            if not written:
                try:
                    found = sniff.video(chunk[:sniff.HEAD_BYTES]) if kind == "video" else sniff.audio(chunk[:sniff.HEAD_BYTES])
                except sniff.SniffError as exc:
                    raise HTTPException(status_code=415, detail=str(exc)) from None
            written += len(chunk)
            if written > cap:
                raise HTTPException(status_code=413, detail=_too_big(kind))
            out.write(chunk)
    if not written:
        raise HTTPException(status_code=422, detail="That file is empty.")
    return found


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


@dataclass(frozen=True)
class Acting:
    """G2: who is acting in this request. `user` is the signed-in person;
    `owner` whose work it is (the workspace owner when a member works in
    someone's workspace, else themselves); `role` owner | editor | reviewer."""
    user: str
    owner: str
    role: str
    workspace_id: str | None = None
    email: str | None = None


acting: ContextVar[Acting | None] = ContextVar("acting", default=None)


def signed_in_identity(request: Request) -> "auth.Identity | None":
    if settings.auth_mode == "off":
        return None
    payload = auth.verify(request.cookies.get(auth.SESSION_COOKIE), settings.session_secret or "", max_age=auth.SESSION_SECONDS)
    who = auth.identity_from(payload)
    if who is not None and who.provider == "acct":
        # Launch item 5: an account's session holds while the account exists and
        # its password (or address) has not changed since the session began.
        from app.store import accounts as accounts_store
        account = accounts_store.by_id(database, who.sub)
        if account is None or not account.verified or int((payload or {}).get("sv", 0)) != account.session_version:
            return None
        who = replace(who, email=account.email)
    return who


def signed_in_user(request: Request) -> str:
    """The signed-in person (not the workspace they act in); 401 when nobody is."""
    if settings.auth_mode == "off":
        return LOCAL_OWNER
    who = signed_in_identity(request)
    if who is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return who.owner


def _resolve_acting(request: Request) -> Acting | None:
    """The person, and the workspace they chose when they are a member of
    it and its owner has roles on (`golive.g2`); otherwise their own."""
    if settings.auth_mode == "off":
        return Acting(LOCAL_OWNER, LOCAL_OWNER, "owner")
    who = signed_in_identity(request)
    if who is None:
        return None
    wid = request.cookies.get("ave_workspace")
    if wid:
        role = members_store.role_in(database, wid, who.owner)
        ws = members_store.workspace(database, wid) if role and role != "owner" else None
        if ws is not None and flags.enabled("golive.g2", ws["owner"]):
            return Acting(who.owner, ws["owner"], role, wid, who.email)
    return Acting(who.owner, who.owner, "owner", None, who.email)


def current_owner(request: Request) -> str:
    """Who is calling — the auth seam (Phase 9c).

    With AVE_AUTH=off everyone is the local owner. With sign-in on, the
    session cookie names the owner, every route is scoped by it, and a
    state-changing request must carry the header a cross-site form cannot.
    G2: a member working in someone's workspace acts for its owner (the
    middleware has already checked their role allows the request).
    """
    if settings.auth_mode == "off":
        return LOCAL_OWNER
    who = signed_in_identity(request)
    if who is None:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(auth.CSRF_HEADER) != auth.CSRF_VALUE:
        raise HTTPException(status_code=403, detail="This request did not come from Voltage.")
    me = acting.get()
    if me is not None and me.user == who.owner:
        return me.owner
    return who.owner


# ── Launch item 2: media and exports only through signed, expiring URLs ─────
# A media route takes no cookie: the URL carries `mt`, a token this server
# signed for one owner that expires after MEDIA_SECONDS. The app fetches one
# (`GET /me/media-token`) and adds it to every media address it builds; a
# link copied out of the app stops working when its token expires.

MEDIA_SECONDS = 12 * 3600
MEDIA_KIND = "media"


def mint_media_token(owner: str, now: float | None = None) -> dict:
    issued = int(now if now is not None else time.time())
    token = auth.sign({"k": MEDIA_KIND, "o": owner}, share_key, now=issued)
    return {"token": token, "expires_at": iso(datetime.fromtimestamp(issued + MEDIA_SECONDS, timezone.utc)),
            "expires_in": MEDIA_SECONDS}


def media_owner(request: Request, mt: str | None = None) -> str:
    """Whose media a signed URL opens. A missing, altered or expired token is 403."""
    payload = auth.verify(mt, share_key, max_age=MEDIA_SECONDS)
    if not payload or payload.get("k") != MEDIA_KIND or not isinstance(payload.get("o"), str):
        raise HTTPException(status_code=403, detail="This media link has expired. Reload the page to get a fresh one.")
    return payload["o"]


@app.get("/me/media-token")
def get_media_token(owner: str = Depends(current_owner)) -> dict:
    """A fresh signed token for the caller's media addresses (`?mt=`)."""
    return mint_media_token(owner)


# ── Launch item 3: spend protection ──────────────────────────────────────────
# Every paid path asks `_ensure_paid_open` first: new paid work stops for
# everyone while the admin's switch (`launch.paid_paused`, set for everyone)
# is on, or once the day's spend across all users reaches AVE_DAILY_SPEND_CAP_USD
# (until midnight UTC). Free steps keep working; a turn already running
# stops at its next paid step (voicing checks it too: `budget.before_charge`).

from app.usage import PAUSED_WORDS, PaidPaused  # noqa: E402


def _day_start() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT00:00:00.000Z")


def paid_state() -> dict:
    """Whether new paid work is paused, why, and the day's numbers."""
    today = ledger.spent_usd_everyone_since(_day_start())
    cap = settings.daily_cap_usd
    switch = flags.enabled("launch.paid_paused")
    capped = cap is not None and today >= cap
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%dT00:00:00.000Z")
    return {"paused": switch or capped, "reason": "switch" if switch else ("daily_cap" if capped else None),
            "message": PAUSED_WORDS if (switch or capped) else None,
            "today_usd": round(today, 4), "cap_usd": cap, "resumes_at": tomorrow if capped and not switch else None}


def _ensure_paid_open() -> None:
    state = paid_state()
    if state["paused"]:
        analytics.track("paid.paused_refusal", (acting.get().user if acting.get() else None), {"reason": state["reason"]})
        raise PaidPaused(state["reason"])


budget.before_charge = _ensure_paid_open


@app.get("/status")
def get_status() -> dict:
    """Public: whether new paid work is paused, for the banner (no numbers)."""
    state = paid_state()
    return {"paid_paused": state["paused"], "message": state["message"], "resumes_at": state["resumes_at"]}


def _admin_or_404(request: Request) -> str:
    from app.analytics_api import is_admin
    me = acting.get()
    user = me.user if me else current_owner(request)
    if not is_admin(user):
        raise HTTPException(status_code=404, detail="Not found")
    return user


@app.get("/admin/spend")
def get_admin_spend(request: Request) -> dict:
    """Admins: today's spend across everyone, by vendor, the cap and the switch."""
    _admin_or_404(request)
    state = paid_state()
    return {**state, "by_vendor": ledger.by_vendor_since(_day_start()), "switch": flags.enabled("launch.paid_paused")}


class PauseRequest(BaseModel):
    paused: bool


@app.put("/admin/paid-pause")
def set_paid_pause(req: PauseRequest, request: Request) -> dict:
    """Admins: the kill switch. On, new paid work stops for everyone and the banner shows."""
    who = _admin_or_404(request)
    from app.flags import ALL
    flags.set("launch.paid_paused", ALL, req.paused)
    log.warning("paid work %s by %s", "paused" if req.paused else "resumed", who)
    analytics.track("paid.switch", who, {"paused": req.paused})
    return get_admin_spend(request)


@app.get("/admin/flags")
def get_admin_flags(request: Request, owner: str) -> dict:
    """Admins (launch item 10): every feature flag for one person, on or off and why."""
    _admin_or_404(request)
    return {"owner": owner, "profile": settings.launch_profile, "flags": flags.explain(owner)}


class FlagChange(BaseModel):
    owner: str
    flag: str
    enabled: bool | None = None       # None: back to the profile's default


@app.put("/admin/flags")
def set_admin_flag(req: FlagChange, request: Request) -> dict:
    """Admins: turn a feature on or off for one person (or `*` for everyone), or clear it."""
    who = _admin_or_404(request)
    from app.flags import is_known
    if not is_known(req.flag) or not req.owner.strip():
        raise HTTPException(status_code=422, detail="Name a known flag and an owner id (or * for everyone).")
    if req.enabled is None:
        flags.clear(req.flag, req.owner.strip())
    else:
        flags.set(req.flag, req.owner.strip(), req.enabled)
    log.warning("flag %s for %s set to %s by %s", req.flag, req.owner, req.enabled, who)
    return get_admin_flags(request, req.owner.strip())


def _ensure_owner_spend(owner: str) -> None:
    """Paid work not tied to one video (an upload's transcription, a voice of
    your own): the pause, the person's month and their credits."""
    _ensure_paid_open()
    ledger.ensure_can_spend(_user_store(owner), owner=owner, owner_ceiling_usd=settings.user_budget_usd,
                            filename="Your voices", member=_member_limit())
    _ensure_credits(owner)


def _ensure_spend(project_id: str) -> None:
    """The video's ceiling, its project's when one is set (Folders), and the
    owner's for the month; the refusal names the scope that was reached."""
    _ensure_paid_open()
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
        member=_member_limit(),
    )
    if record is not None:
        _ensure_credits(record.owner)


def _ensure_credits(owner: str) -> None:
    """G3: with billing on, paid work stops when the owner's credits are used up
    (the hard ceiling; CreditsUsedUp is a SpendCeilingReached, so every caller
    already turns it into the sentence)."""
    if not flags.enabled("golive.g3", owner):
        return
    from app import billing
    if not billing.has_account(database, owner):
        return
    ok, got = billing.can_spend(database, owner, lambda at: ledger.spent_usd_by_owner(owner, at))
    if not ok:
        analytics.track("billing.credits_out", owner, {"granted": got["granted"], "used": got["used"]})
        raise billing.CreditsUsedUp(got["used"], got["granted"])


def _member_limit() -> tuple[str, str, float] | None:
    """G2: (who, workspace, limit) when a member with a monthly limit is acting."""
    me = acting.get()
    if me is None or me.role == "owner" or me.workspace_id is None:
        return None
    found = members_store.member(database, me.workspace_id, me.user)
    if found is None or found.spend_limit_usd is None:
        return None
    return me.user, me.workspace_id, float(found.spend_limit_usd)


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
    who = signed_in_identity(request)
    return {
        "mode": settings.auth_mode,
        "user": {"sub": who.sub, "email": who.email, "name": who.name, "picture": who.picture,
                 "provider": who.provider} if who else None,
    }


GOOGLE_TERMS_FIRST = "To make an account with Google, use the button on this page: it shows the Terms you accept."


def _new_person_refused(owner: str, email: str | None) -> bool:
    """Launch item 5: with invite-only on, someone who has never signed in
    may not start now without an invite (Google and emailed links alike)."""
    from app.accounts_api import invite_only, may_join
    if not invite_only() or email_mod.address_for(database, owner):
        return False
    return not may_join(email or "", None)


@app.get("/auth/me")
def auth_me(request: Request) -> dict:
    """Whether sign-in is on, and who is signed in."""
    if settings.auth_mode == "off":
        _signed_in(LOCAL_OWNER)
    return _me(request)


_funnel_started: set[str] = set()


def _signed_in(owner: str) -> None:
    """G7: the funnel's first steps, once per owner (the store dedupes; this set saves the look)."""
    if owner in _funnel_started:
        return
    analytics.track("signed_up", owner)
    analytics.track("first_sign_in", owner)
    _funnel_started.add(owner)
    # G3: a new owner (no work yet, Bin included) starts on the free trial's credits.
    if owner != LOCAL_OWNER and flags.enabled("golive.g3", owner) \
            and not repo.list_projects(owner, include_deleted=True) and not repo.list(owner, include_deleted=True):
        from app import billing
        billing.account(database, owner)


@app.get("/auth/login")
def auth_login(request: Request, terms: str | None = None) -> Response:
    """Off to Google. The state and the PKCE verifier ride in a short-lived
    signed cookie, so the callback can check them. `terms=1` comes from the
    sign-in page's button, which says that continuing accepts the Terms and
    the Privacy notice (rehearsal item 1: a Google sign-up records it)."""
    if oidc is None:
        raise HTTPException(status_code=404, detail="Sign-in is off.")
    from app.accounts_api import TERMS_VERSION
    state = auth._b64(auth.secrets.token_bytes(16))
    verifier, challenge = auth.pkce_pair()
    response = RedirectResponse(oidc.authorize_url(_redirect_uri(), state, challenge), status_code=302)
    login = {"state": state, "verifier": verifier, **({"terms": TERMS_VERSION} if terms == "1" else {})}
    response.set_cookie(
        auth.LOGIN_COOKIE, auth.sign(login, settings.session_secret or ""),
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
    if _new_person_refused(who.owner, who.email):
        from app.accounts_api import INVITE_ONLY
        raise HTTPException(status_code=403, detail=INVITE_ONLY)
    from app.accounts_api import record_terms, terms_record
    if terms_record(database, who.owner) is None:
        if not login.get("terms") and not email_mod.address_for(database, who.owner):
            # A new person who reached Google without the sign-in page's Terms line: back to it.
            return RedirectResponse(settings.public_url + "/#login?error=" + quote(GOOGLE_TERMS_FIRST), status_code=302)
        if login.get("terms"):
            record_terms(database, who.owner, str(login["terms"]), via="google")
    email_mod.remember_address(database, who.owner, who.email)      # C2: where their review digest goes
    _signed_in(who.owner)                                             # G7: the funnel's first steps
    try:                                                              # G1: a new owner's sample project
        from app.tutorial import sample
        sample.ensure(who.owner)
    except Exception:  # noqa: BLE001 - the sample is a nicety; sign-in never fails over it
        log.exception("could not make the sample project for a new owner")
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
def get_frame(project_id: str, index: int, owner: str = Depends(media_owner)) -> FileResponse:
    record = _owned(project_id, owner)
    frames = _frames(record)
    if not 0 <= index < len(frames):
        raise HTTPException(status_code=404, detail="frame not found")
    return FileResponse(frames[index].path, media_type="image/jpeg")


def _stage_for_turn(video_id: str) -> str | None:
    """C1: the video's stage as Voltage's ship sees it; None without `projects.review`."""
    record = repo.get(video_id)
    return record.stage if record is not None and _review_on(record.owner) else None


def _project_dict(record: ProjectRecord) -> dict:
    """A video record. `video_id` is its own id; `project_id` the folder it
    is in, or null (Folders)."""
    source = record.source
    folder = _folder_of(record)
    return {
        "video_id": source.project_id,
        "project_id": folder.project_id if folder else None,
        "project_name": folder.name if folder else None,
        # A1: the brief it was made with against the project's current one ("Brief changed" in the header).
        "brief_version": folder.brief_version if folder else None,
        "made_with_brief": record.made_with_brief,
        "brief_changed": briefs.stale(record.made_with_brief, folder.brief_version if folder else None),
        # C1: its stage; an add on an Approved video warns first.
        "stage": record.stage,
        # D4: an archived project's videos are read-only.
        "project_archived": bool(folder and folder.archived_at),
        # B2: the language set it belongs to ("Out of sync with master" in the header).
        **_language_fields(record),
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
    if folder is not None:
        _not_archived(folder.project_id, owner)
    filename = Path(file.filename or "upload.mp4").name
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / filename
        await _spool(file, staged)
        # Rehearsal item 3 (the load test): the probe, the store and the transcription are slow and
        # blocking; on the event loop they froze every other request while one upload ran.
        return await run_in_threadpool(_ingest_staged, staged, filename, consent, folder, owner)


def _ingest_staged(staged: Path, filename: str, consent: bool, folder: Project | None, owner: str) -> dict:
    """A file on disk becomes a video: probed (refused before an id is
    given, so a refusal leaves no trace), stored, transcribed, charged.
    Shared by the upload and G1's import from a link."""
    try:
        # Launch item 2: the bytes say what it is (an upload was sniffed while spooling; a link import here).
        container = sniff.video(sniff.head_of(staged))
    except sniff.SniffError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    if staged.stat().st_size > ingest.MAX_SOURCE_BYTES:
        raise HTTPException(status_code=413, detail=_too_big("video"))
    try:
        probed = ingest.probe_source(staged)
    except ingest.IngestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if transcriber_label.startswith("openai"):
        # Launch item 3: transcription is paid; it is refused before anything is stored.
        try:
            _ensure_owner_spend(owner)
        except SpendCeilingReached as exc:
            raise HTTPException(status_code=402, detail=str(exc)) from exc
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
    analytics.track("video_uploaded", owner, {"video_id": project_id, "seconds": round(source.duration, 1),
                                              "project_id": folder.project_id if folder else None})
    return _project_dict(repo.get(project_id))


# ── G1: the sample project and upload from a link ────────────────────────────
#
# The sample project (app/tutorial/sample.py) is made once per new owner, the
# first time Home loads (`POST /me/sample`) or they sign in. An import from a
# link (app/linkimport.py: Google Drive, Dropbox; YouTube behind the
# interface but off) is one Activity job (kind "import", keyed by the
# owner's own store id, `user-<owner>`, since no video exists yet): download
# with a 2 GB cap and progress, sniff, then the upload's own ingest. Both
# need `golive.g1`.

_samples_lock = threading.Lock()
# Tests swap in a client on an httpx.MockTransport; None means a real one.
_link_http: "httpx.Client | None" = None
# Tests run an import inline; the server runs it on the work pool.
IMPORT_IN_BACKGROUND = True


def _g1_flag(owner: str) -> None:
    if not flags.enabled("golive.g1", owner):
        raise HTTPException(status_code=404, detail="Not found")


@app.post("/me/sample")
def ensure_sample(owner: str = Depends(current_owner)) -> dict:
    """Home's first load: the sample project for a new owner, once ever."""
    from app.tutorial import sample
    return sample.ensure(owner)


class LinkImportRequest(BaseModel):
    url: str
    project_id: str | None = None
    consent: bool = False


def _import_key(owner: str) -> str:
    return _user_store(owner)


def _import_dict(job) -> dict:
    out = job.to_dict()
    out["detail"] = {k: v for k, v in out["detail"].items() if k != "owner"}
    return out


@app.get("/imports/sources")
def import_sources(owner: str = Depends(current_owner)) -> dict:
    """Where a link can come from, and why one is off."""
    _g1_flag(owner)
    return {"sources": [{"name": i.name, "label": i.label, "enabled": i.enabled, "why_off": i.why_off}
                        for i in linkimport.IMPORTERS], "max_bytes": linkimport.MAX_LINK_BYTES}


@app.post("/imports", status_code=202)
def start_import(req: LinkImportRequest, owner: str = Depends(current_owner)) -> dict:
    """Import a video from a share link. 422 with a sentence for a link that
    cannot work (not Drive or Dropbox, YouTube while it is off, not a file);
    otherwise the job, which says how far the download is."""
    _g1_flag(owner)
    folder = _owned_project(req.project_id, owner) if req.project_id else None
    if folder is not None:
        _not_archived(folder.project_id, owner)
    try:
        resolved = linkimport.resolve(req.url)
    except linkimport.ImportRefused as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    job = activity.create(_import_key(owner), "import", step_label="Queued",
                          detail={"owner": owner, "source": resolved.provider, "source_label": resolved.label,
                                  "project_id": folder.project_id if folder else None})
    with database.tx() as c:
        c.execute("UPDATE jobs SET workspace_id = ? WHERE job_id = ?", (personal(c, owner), job.job_id))
        analytics.track_in(c, "import.started", owner, {"source": resolved.provider})

    def run() -> None:
        _run_import(job.job_id, resolved, folder, req.consent, owner)
    if IMPORT_IN_BACKGROUND:
        work_pool.submit(run)
    else:
        run()
    return _import_dict(activity.get(job.job_id))


def _run_import(job_id: str, resolved, folder: Project | None, consent: bool, owner: str) -> None:
    activity.start(job_id, f"Downloading from {resolved.label}")
    last = [0.0]

    def progress(got: int, total: int | None) -> None:
        now = time.time()
        if now - last[0] < 0.5 and (total is None or got < total):
            return
        last[0] = now
        activity.update(job_id, progress=0.85 * got / total if total else None,
                        detail={"bytes": got, "total_bytes": total})
    try:
        with tempfile.TemporaryDirectory() as tmp:
            client = _link_http or httpx.Client()
            try:
                path = linkimport.download(resolved, Path(tmp), client=client, on_progress=progress)
            finally:
                if client is not _link_http:
                    client.close()
            activity.update(job_id, step_label="Reading the video", progress=0.9)
            video = _ingest_staged(path, path.name, consent, folder, owner)
        activity.finish(job_id, step_label="Ready", detail={"video_id": video["video_id"], "filename": video["filename"]})
        analytics.track("import.finished", owner, {"source": resolved.provider, "video_id": video["video_id"]})
    except linkimport.ImportRefused as exc:
        activity.fail(job_id, "import_failed", str(exc))
        analytics.track("import.failed", owner, {"source": resolved.provider})
    except HTTPException as exc:
        activity.fail(job_id, "import_failed", str(exc.detail))
        analytics.track("import.failed", owner, {"source": resolved.provider})
    except Exception as exc:  # noqa: BLE001 - an import that breaks says so; the server stays up
        log.exception("import %s failed", job_id)
        activity.fail(job_id, "import_failed", f"The import stopped: {str(exc)[:200] or type(exc).__name__}")
        analytics.track("import.failed", owner, {"source": resolved.provider})


@app.get("/imports")
def list_imports(owner: str = Depends(current_owner)) -> dict:
    """The caller's recent imports, newest first."""
    _g1_flag(owner)
    return {"imports": [_import_dict(j) for j in activity.list(_import_key(owner), limit=20)]}


@app.get("/imports/{job_id}")
def get_import(job_id: str, owner: str = Depends(current_owner)) -> dict:
    _g1_flag(owner)
    job = activity.get(job_id)
    if job is None or job.kind != "import" or job.detail.get("owner") != owner:
        raise HTTPException(status_code=404, detail="import not found")
    return _import_dict(job)


# ── 20i: the user's own voices ───────────────────────────────────────────────
# Uploaded under a name, cloned once at the vendor, kept per owner (not per
# project), and offered wherever a voice is picked: the editor's Voice select,
# the speakers bar, and the agent's list ("in my voice" means one of these).

MIN_MY_VOICE_SECONDS = 10.0


def _all_my_voices(owner: str) -> list[dict]:
    """The owner's voices, those in the Bin (F8, `deleted_at`) included."""
    return json.loads(repo.get_meta(f"my_voices:{owner}") or "[]")


def _my_voices(owner: str) -> list[dict]:
    """The owner's voices; one in the Bin cannot be picked or listed."""
    return [v for v in _all_my_voices(owner) if not v.get("deleted_at")]


def _set_my_voices(owner: str, voices: list[dict]) -> None:
    """Write the owner's live voices; those in the Bin are kept as they are."""
    live = {v["voice_id"] for v in voices}
    binned = [v for v in _all_my_voices(owner) if v.get("deleted_at") and v["voice_id"] not in live]
    repo.set_meta(f"my_voices:{owner}", json.dumps([*voices, *binned]))


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
    _refuse_public_figure(owner, label)                  # G6: not a known public figure's name
    if any(v["name"].lower() == label.lower() for v in _my_voices(owner)):
        raise HTTPException(status_code=409, detail=f"You already have a voice called {label}.")


CLONING_CLOSED = ("Voice cloning is not open yet. Pick a voice from the library or design one; "
                  "cloning opens once we can check that a voice is really yours.")


def _voices_can_be_made(attr: str = "can_clone", owner: str | None = None) -> None:
    """Making a voice of the user's own needs a vendor that keeps it; under
    dry-run a mock id would outlive the setup that made it. A clone also
    needs `voices.cloning` for the owner (rehearsal item 1)."""
    if attr == "can_clone" and owner is not None and not flags.enabled("voices.cloning", owner):
        raise HTTPException(status_code=403, detail=CLONING_CLOSED)
    if settings.dry_run or not getattr(voice, attr, False):
        raise HTTPException(status_code=503, detail="Voices cannot be made in this setup (no vendor that clones).")
    try:
        _ensure_paid_open()            # launch item 3: a clone is paid work at the vendor
    except PaidPaused as exc:
        raise HTTPException(status_code=402, detail=str(exc)) from exc


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
        "cloning": flags.enabled("voices.cloning", owner),     # rehearsal item 1: closed for the public
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
    _voices_can_be_made(owner=owner)
    label = _voice_name_or_422(name)
    _no_voice_called(owner, label)
    filename = Path(file.filename or "voice.wav").name
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / filename
        await _spool(file, staged, "audio")

        def make() -> tuple:            # off the event loop (rehearsal item 3): ffmpeg and the vendor block
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
            return voice_id, seconds, artifacts.put_file(_user_store(owner), wav, kind="audio", container="wav", duration=seconds)
        voice_id, seconds, sample = await run_in_threadpool(make)
    ticked = _now()   # the request carries the ticked box: this is the moment of consent
    entry = {"voice_id": voice_id, "name": label, "seconds": round(seconds, 1), "at": ticked,
             "kind": "recorded", "sample_sha": sample.sha256, "description": None, "consent_granted_at": ticked}
    _set_my_voices(owner, [*_my_voices(owner), entry])
    return _voice_entry(entry)


@app.get("/voices/sample/{sha256}")
def get_voice_sample(sha256: str, owner: str = Depends(media_owner)) -> FileResponse:
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
    record = _owned(req.video_id, owner)        # someone else's video is not found, before anything else is said
    if not req.consent:
        raise HTTPException(status_code=403, detail="Say it is your voice, or one you have the right to use.")
    _voices_can_be_made(owner=owner)
    label = _voice_name_or_422(req.name)
    _no_voice_called(owner, label)
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
        _ensure_owner_spend(owner)
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
    """Remove one of your own voices (F8): it goes to the Bin, hidden and
    not pickable; the purge deletes it at the vendor after 30 days."""
    every = _all_my_voices(owner)
    if not any(v["voice_id"] == voice_id and not v.get("deleted_at") for v in every):
        raise HTTPException(status_code=404, detail="No such voice of yours.")
    at = _now()
    repo.set_meta(f"my_voices:{owner}", json.dumps(
        [{**v, "deleted_at": at, "deleted_by": owner} if v["voice_id"] == voice_id and not v.get("deleted_at") else v
         for v in every]))
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
    seen = _reviewer_filter()
    if seen is not None:
        found = [r for r in found if r.source.project_id in seen[0]]
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
        "stage": r.stage,
        # D4: Home hides a video whose project is archived, and sorts by when it last changed.
        "project_archived": bool(folder and folder.archived_at),
        "last_edited_at": _last_edited(pid, r.created_at),
        # C1/C2: the review comments on it still open.
        "open_comments": comments_store.open_counts(database, [pid]).get(pid, 0),
        # A1: the brief version its last shipped edit was made with, and whether the project's is newer.
        "made_with_brief": r.made_with_brief,
        "brief_changed": briefs.stale(r.made_with_brief, folder.brief_version if folder else None),
        # B2: a language version's language and whether it is in step; a master's versions.
        **_language_fields(r),
    }


@app.get("/videos/{project_id}/events/log")
def list_video_events(project_id: str, limit: int = 50, before: int | None = None,
                      owner: str = Depends(current_owner)) -> dict:
    """F7: what happened to one video, newest first (the live channel is
    `/videos/{id}/events`; this is the record)."""
    _owned(project_id, owner)
    return activity_log.for_video(database, project_id, limit, before)


# ── C1: stages and the project board ─────────────────────────────────────────
# Manual moves come through POST /videos/{id}/stage; the automatic ones live
# in app.store.stages (a new edit on an Approved video, a review link sent, a
# reviewer's answer). Every move is one `stage.moved` event.

def _review_on(owner: str) -> bool:
    return flags.enabled("projects.review", owner)


def _review_flag(owner: str) -> None:
    if not _review_on(owner):
        raise HTTPException(status_code=404, detail="Not found")


def _stage_gate(video_ids: list[str], owner: str, confirmed: bool, change: bool = False) -> None:
    """C1: before an add from the editor or a board lands on an Approved
    video, the user is warned (409 with the sentence and the videos) and
    answers with `confirm_stage`. Off without `projects.review`. Decision 0:
    a sync, a role change or a line move (`change`) asks the same way."""
    if confirmed or not _review_on(owner):
        return
    held = [v for v in video_ids if stages.current(database, v) == "approved"]
    if not held:
        return
    names = [r.source.filename for r in (repo.get(v) for v in held) if r is not None]
    if change:
        message, anyway = stages.APPROVED_CHANGE_WARNING, "Change anyway"
    else:
        message, anyway = (stages.APPROVED_WARNING if len(held) == 1 else (
            f"{len(held)} videos are Approved ({', '.join(names)}). Adding these moves them back to Draft.")), "Add anyway"
    raise HTTPException(status_code=409, detail={"code": "stage_approved", "message": message, "videos": held,
                                                 "options": [anyway, "Cancel"]})


def _left_approved(project_id: str, owner: str) -> None:
    """Decision 0: a confirmed line move that writes no edit (a shift, the
    arrangement) still takes an Approved video back to Draft, as an edit does."""
    if _review_on(owner):
        stages.after_new_edit(database, project_id, user_actor(owner))


class StageMoveRequest(BaseModel):
    to: str
    why: str = ""


@app.post("/videos/{project_id}/stage")
def move_stage(project_id: str, req: StageMoveRequest, owner: str = Depends(current_owner)) -> dict:
    """C1: a manual move (the board's drag, or its Move to menu). One event
    per move; a move to the stage it is in changes nothing and logs nothing."""
    _review_flag(owner)
    _owned(project_id, owner)
    try:
        moved = stages.move(database, project_id, req.to, user_actor(owner), req.why)
    except stages.StageError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    now = stages.current(database, project_id) or "draft"
    return {"video_id": project_id, "stage": now, "label": stages.LABELS[now], "moved": moved is not None,
            "move": moved.to_dict() if moved else None}


@app.get("/videos/{project_id}/stage")
def get_stage(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """F5: the video's stage and every move it made, newest first. Moves
    come through app.store.stages only (C1 adds the ways to make one)."""
    record = _owned(project_id, owner)
    return {"stage": record.stage, "label": stages.LABELS[record.stage],
            "history": [m.to_dict() for m in stages.history(database, project_id)]}


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
    # F8: a video or project in the Bin, or purged, keeps its charges under its name.
    videos = {r.source.project_id: r for r in repo.list(owner, include_deleted=True)}
    gone = _purged_names(owner)
    for vid, (name, folder_id) in gone["video"].items():
        videos.setdefault(vid, SimpleNamespace(source=SimpleNamespace(filename=name), folder_id=folder_id, deleted=True))
    spent_in = {row["folder_id"] for row in rows}
    folders = [p for p in repo.list_projects(owner, include_deleted=True)
               if repo.get_project(p.project_id) is not None or p.project_id in spent_in]
    folders += [SimpleNamespace(project_id=pid, name=name, ceiling_usd=None)
                for pid, (name, _) in gone["project"].items() if pid in spent_in]
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


def _purged_names(owner: str) -> dict[str, dict[str, tuple[str, str | None]]]:
    """What the purge removed (F8), by kind: id -> (name, project)."""
    out: dict[str, dict] = {"video": {}, "project": {}, "voice": {}}
    with database.tx() as c:
        for r in c.execute("SELECT kind, item_id, name, project_id FROM purged_items WHERE owner = ?", (owner,)):
            out.setdefault(r["kind"], {})[r["item_id"]] = (r["name"], r["project_id"])
    return out


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
    # F8: a video in the Bin, or purged, still counts, under its name.
    projects = [SimpleNamespace(source=SimpleNamespace(project_id=r.source.project_id, filename=r.source.filename),
                                folder_id=r.folder_id) for r in repo.list(owner, include_deleted=True)]
    projects += [SimpleNamespace(source=SimpleNamespace(project_id=vid, filename=name), folder_id=folder)
                 for vid, (name, folder) in _purged_names(owner)["video"].items()]
    live_ids = {r.source.project_id for r in repo.list(owner)}
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
        # D3: a video in the Bin (or purged) still counts its spend, not as one of the project's videos.
        "project_id": p.project_id, "name": p.name, "videos": sum(1 for r in projects if r.folder_id == p.project_id
                                                                  and r.source.project_id in live_ids),
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
    """Delete a video (F8): it goes to the Bin, hidden everywhere; the purge
    removes it, its media and its voices at the vendor after 30 days.
    Deleting the account still removes everything at once."""
    _owned(project_id, owner)
    repo.soft_delete(project_id, owner)


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
    failure is logged by name), their samples and their defaults.

    The account is always the signed-in person's own. A member working in
    someone else's workspace deletes only themselves, never the workspace
    owner's work (the rehearsal found an Editor's DELETE /account wiping the
    owner's account), and leaves every workspace they had joined."""
    me = acting.get()
    if me is not None and me.user != me.owner:
        owner = me.user
    from app.store import members as members_store
    for ws in members_store.workspaces_for(database, owner):
        if not ws.get("own"):
            members_store.remove(database, ws["workspace_id"], owner)
    for r in repo.list(owner, include_deleted=True):
        _delete_project(r.source.project_id)
    for v in _all_my_voices(owner):
        try:
            getattr(voice, "delete_voice", lambda vid: None)(v["voice_id"])
        except Exception as exc:  # noqa: BLE001
            logging.getLogger("ave").warning("account %s deleted, but voice %s (%s) is still at ElevenLabs: %s",
                                             owner, v.get("name"), v["voice_id"], exc)
    # Launch item 5: the sample and onboarding records go too, so an account
    # made again with the same id starts fresh (and gets the sample again).
    for key in ("my_voices", "prefs", "designs", "sample", "onboarding", "terms"):
        repo.delete_meta(f"{key}:{owner}")
    _funnel_started.discard(owner)
    if owner.startswith("acct:"):
        from app.store import accounts as accounts_store
        accounts_store.delete(database, owner[len("acct:"):])
    with database.tx() as c:          # D4: their pins
        c.execute("DELETE FROM pins WHERE owner = ?", (owner,))
        templates_store.purge_owner_in(c, owner)   # D1: their templates
    repo.delete(_user_store(owner))   # the designs' spend, kept under the owner's own id
    shutil.rmtree(artifacts.root / _user_store(owner), ignore_errors=True)
    if flags.enabled("golive.g6", owner):               # G6: the deletion request, kept as a record
        with database.tx() as c:
            c.execute("INSERT INTO data_requests (owner, kind, status, created_at, done_at) VALUES (?, 'deletion', 'done', ?, ?)",
                      (owner, _now(), _now()))
            analytics.track_in(c, "data.deletion_requested", owner, {})
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
    now = briefs.current(database, project.project_id)
    return {
        "project_id": project.project_id,
        "name": project.name,
        "brief": project.brief,
        "brief_version": project.brief_version,
        # A1: who saved the current version and when, and how many videos were made with an older one.
        "brief_edited_by": now.created_by if now else None,
        "brief_edited_at": now.created_at if now else None,
        "stale_count": len(briefs.stale_videos(database, project.project_id)),
        "settings": {k: v for k, v in _defaults_for(project.owner, project).items() if k in SETTING_KEYS},
        "ceiling_usd": project.ceiling_usd,
        "spent_usd": round(ledger.spent_usd_by_folder(project.project_id), 4),
        "created_at": project.created_at,
        # D4: set while archived (hidden from Home, read-only).
        "archived_at": project.archived_at,
        # G1: the sample project made for a new owner.
        "sample": _is_sample(project),
    }


def _is_sample(project: Project) -> bool:
    raw = repo.get_meta(f"sample:{project.owner}")
    return bool(raw) and json.loads(raw).get("project_id") == project.project_id


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
            "rules": [{"kind": r.kind, "data": r.data} for r in rules.list_rules(database, project.project_id)],
            "rules_version": rules.rules_version(database, project.project_id),
            "voices": _project_voices(project.project_id), "videos": sisters, "files": _project_files(project.project_id),
            # B2: a language version reads what it is a version of, its words that never translate, its glossary.
            "language": _language_view(record)}


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
    # D1: start from a template (a starter's id or one of the owner's own).
    template_id: str | None = None


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
def list_folders(archived: bool = False, owner: str = Depends(current_owner)) -> dict:
    """The caller's projects (folders), with how much each holds and has spent.
    D4: archived projects are left out, or are the list with `archived=true`."""
    found = repo.list_projects(owner)
    if flags.enabled("projects.reuse", owner):
        found = [p for p in found if bool(p.archived_at) == archived]
    seen = _reviewer_filter()
    if seen is not None:
        found = [p for p in found if p.project_id in seen[1]]
    return {"projects": [_project_summary(p) for p in found]}


@app.post("/projects", status_code=201)
def create_folder(req: ProjectCreate, owner: str = Depends(current_owner)) -> dict:
    if req.template_id:
        return _folder_from_template(req, owner)
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
    before = repo.get_project(project_id).brief_version
    project = repo.update_project(
        project_id, name=name, brief=req.brief.strip() if req.brief is not None else None, by=owner,
        settings=_clean_defaults(req.settings) if req.settings is not None else None,
        ceiling_usd=req.ceiling_usd, clear_ceiling="ceiling_usd" in req.model_fields_set and req.ceiling_usd is None,
    )
    if project.brief_version != before:
        _auto_check(project_id, owner)   # A2: the free checks again after a brief change
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


class RuleRequest(BaseModel):
    kind: str | None = None     # pronounce | banned | required_line | style (on create)
    data: dict


def _rule_or_422(work):
    try:
        return work()
    except rules.RuleError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/projects/{project_id}/rules")
def list_project_rules(project_id: str, kind: str | None = None, owner: str = Depends(current_owner)) -> dict:
    """F3: the project's rules, oldest first, with the rules version."""
    _owned_project(project_id, owner)
    return {"rules": [r.to_dict() for r in rules.list_rules(database, project_id, kind)],
            "rules_version": rules.rules_version(database, project_id)}


@app.post("/projects/{project_id}/rules", status_code=201)
def add_project_rule(project_id: str, req: RuleRequest, source: str | None = None,
                     owner: str = Depends(current_owner)) -> dict:
    """`source=transcript`: a word learned from the editor's transcript (A3), counted for G7."""
    _owned_project(project_id, owner)
    made = _rule_or_422(lambda: rules.add(database, project_id, req.kind or "", req.data, owner)).to_dict()
    if source == "transcript":
        analytics.track("words.learned_from_transcript", owner, {"project_id": project_id, "kind": req.kind})
    return made


@app.patch("/projects/{project_id}/rules/{rule_id}")
def change_project_rule(project_id: str, rule_id: int, req: RuleRequest, owner: str = Depends(current_owner)) -> dict:
    _owned_project(project_id, owner)
    rule = _rule_or_422(lambda: rules.update(database, project_id, rule_id, req.data, owner))
    if rule is None:
        raise HTTPException(status_code=404, detail="rule not found")
    return rule.to_dict()


# A3: a short clip of how a project word is said, kept with the project.
MAX_WORD_CLIP_BYTES = 5 << 20
MAX_WORD_CLIP_SECONDS = 10.0


def _words_store(project_id: str) -> str:
    """Where a project's word clips live: under the project's own folder, so the purge (F8) takes them with it."""
    return f"projects/{project_id}/words"


def _pronounce_rule_or_404(project_id: str, rule_id: int) -> rules.Rule:
    rule = rules.get(database, project_id, rule_id)
    if rule is None or rule.kind != "pronounce":
        raise HTTPException(status_code=404, detail="word not found")
    return rule


@app.post("/projects/{project_id}/rules/{rule_id}/audio")
async def add_word_audio(project_id: str, rule_id: int, file: UploadFile = File(...),
                         owner: str = Depends(current_owner)) -> dict:
    """A3: an example of how a project word is said (up to 10 s), stored as an
    artifact and named on the rule. Optional; a new clip replaces the old one."""
    _consistency_on(owner)
    _owned_project(project_id, owner)
    rule = _pronounce_rule_or_404(project_id, rule_id)
    filename = Path(file.filename or "word.wav").name
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / filename
        await _spool(file, staged, "audio")
        if staged.stat().st_size > MAX_WORD_CLIP_BYTES:
            raise HTTPException(status_code=422, detail="That clip is too big. A few seconds of audio is all a word needs.")

        def store() -> tuple:           # off the event loop (rehearsal item 3)
            try:
                wav, seconds = ffmpeg.extract_audio(staged, Path(tmp) / "word.wav", sample_rate=44100)
            except Exception:  # noqa: BLE001 - a file ffmpeg cannot read is the user's to replace
                raise HTTPException(status_code=422, detail="That file has no audio I can read. A WAV, MP3, M4A or WebM works.") from None
            if seconds > MAX_WORD_CLIP_SECONDS:
                raise HTTPException(status_code=422, detail=f"That clip is {seconds:.0f} s. Keep it under {MAX_WORD_CLIP_SECONDS:.0f} s: just the word, said right.")
            return seconds, artifacts.put_file(_words_store(project_id), wav, kind="audio", container="wav", duration=seconds)
        seconds, clip = await run_in_threadpool(store)
    analytics.track("words.clip_added", owner, {"project_id": project_id, "seconds": round(seconds, 1)})
    return _rule_or_422(lambda: rules.update(database, project_id, rule_id, {**rule.data, "audio": clip.sha256}, owner)).to_dict()


@app.get("/projects/{project_id}/rules/{rule_id}/audio")
def get_word_audio(project_id: str, rule_id: int, owner: str = Depends(media_owner)) -> FileResponse:
    _owned_project(project_id, owner)
    rule = _pronounce_rule_or_404(project_id, rule_id)
    sha = rule.data.get("audio")
    path = artifacts.find(_words_store(project_id), sha) if sha else None
    if path is None:
        raise HTTPException(status_code=404, detail="no clip for this word")
    return FileResponse(path, media_type="audio/wav")


@app.delete("/projects/{project_id}/rules/{rule_id}/audio")
def delete_word_audio(project_id: str, rule_id: int, owner: str = Depends(current_owner)) -> dict:
    """A3: the word keeps its spelling and respelling; only the clip goes (the stored file stays until the purge)."""
    _consistency_on(owner)
    _owned_project(project_id, owner)
    rule = _pronounce_rule_or_404(project_id, rule_id)
    data = {k: v for k, v in rule.data.items() if k != "audio"}
    return _rule_or_422(lambda: rules.update(database, project_id, rule_id, data, owner)).to_dict()


@app.delete("/projects/{project_id}/rules/{rule_id}", status_code=204)
def delete_project_rule(project_id: str, rule_id: int, owner: str = Depends(current_owner)) -> Response:
    _owned_project(project_id, owner)
    if not rules.remove(database, project_id, rule_id, owner):
        raise HTTPException(status_code=404, detail="rule not found")
    return Response(status_code=204)


# ── A1: bring videos up to date with the brief ───────────────────────────────
#
# With `projects.batch` on (F4) the run is one batch turn: a child per stale
# video, three at a time, under the parent's cap (`_brief_update_batch`).
# Off, it is the sequential loop below, one Activity job ("brief_update") per
# video. Either way the free word-overlap check runs first in each video (a
# video the change does not touch costs nothing).

def _consistency_on(owner: str) -> None:
    """Phase A ships behind `projects.consistency`; off, its routes are not there."""
    if not flags.enabled("projects.consistency", owner):
        raise HTTPException(status_code=404, detail="Not found")


def _check_on(owner: str) -> None:
    """A2 (the project check) also needs `projects.check` (launch item 10: off for the public)."""
    _consistency_on(owner)
    if not flags.enabled("projects.check", owner):
        raise HTTPException(status_code=404, detail="Not found")


BRIEF_RUN_KEY = "brief_update:{}"
# How long one video's turn may run before the loop stops waiting on it.
BRIEF_TURN_WAIT_S = 1800.0
_brief_runs_lock = threading.Lock()


def _brief_run(project_id: str) -> dict | None:
    """The project's latest run, with each video's job read fresh. A run left
    running by a restart (its jobs failed by the sweep) reads as finished."""
    raw = repo.get_meta(BRIEF_RUN_KEY.format(project_id))
    if not raw:
        return None
    run = json.loads(raw)
    for v in run["videos"]:
        job = activity.get(v["job_id"]) if v.get("job_id") else None
        if job is not None:
            v["status"] = job.status
            v["step"] = job.step_label
            v["outcome"] = job.detail.get("outcome", v.get("outcome"))
            v["why"] = job.error_text if job.status == "failed" else job.detail.get("why", v.get("why"))
    if run["status"] == "running" and all(v["status"] in ("done", "failed", "cancelled") for v in run["videos"] if v.get("job_id")):
        run["status"] = "finished"
    return run


def _save_brief_run(project_id: str, run: dict) -> None:
    repo.set_meta(BRIEF_RUN_KEY.format(project_id), json.dumps(run))


def _diff_words(runs: list[dict]) -> str:
    """The change as a sentence for the goal: what went and what came in."""
    gone = [r["text"].strip() for r in runs if r["op"] == "removed" and r["text"].strip()]
    came = [r["text"].strip() for r in runs if r["op"] == "added" and r["text"].strip()]
    bits = ([f"removed “{' … '.join(gone)}”"] if gone else []) + ([f"added “{' … '.join(came)}”"] if came else [])
    return "; ".join(bits) or "no words changed"


def _video_texts(video_id: str, record: ProjectRecord) -> list[str]:
    """What a video says: its lines as shot, what it shipped and what waits as a proposal."""
    texts = [st.text for st in statements_of(record.transcript)] or [" ".join(w.text for w in record.transcript.words)]
    texts += [e.plan.new_text for e in repo.list_edits(video_id) if not e.reverted]
    plan = repo.latest_plan(video_id)
    texts += [i.new_text for i in (plan.items if plan else ()) if i.status not in ("dismissed",)]
    return texts


def _bring_one_up_to_date(project_id: str, video_id: str, job_id: str, made: int, to: int, owner: str,
                          batch_cap: float | None = None) -> None:
    """One video: the free word-overlap check first; a video the change does
    not touch is marked current without spending, saying why. Otherwise an
    ordinary turn with the goal "Apply brief changes vN to vM" and the diff.
    `batch_cap`: one child of a batch (F4), its turn under that cap."""
    activity.start(job_id, "Checking what the change touches")
    record = repo.get(video_id)
    if record is None:
        activity.fail(job_id, "gone", "This video was deleted.")
        return
    runs = briefs.diff(database, project_id, made, to) or []
    hit = briefs.touches(runs, _video_texts(video_id, record))
    changed = sorted(briefs.changed_words(runs))
    if not hit:
        why = (f"None of the words the brief changed ({', '.join(changed[:6])}) are in this video, so nothing was spent."
               if changed else "The brief change has no words this video could use, so nothing was spent.")
        with database.tx() as c:
            briefs.made_with_in(c, video_id, to)
            activity_log.record(c, "brief.video_current", VOLTAGE, video_id=video_id, project_id=project_id,
                                target=video_id, payload={"from": made, "to": to, "why": why, "spent_usd": 0})
        activity.finish(job_id, step_label="Up to date, nothing to change", detail={"outcome": "current", "why": why, "spent_usd": 0})
        return
    if not _agent_on():
        activity.fail(job_id, "no_agent", "Voltage needs Claude to change this video (set AVE_AGENT=1 and an Anthropic key).")
        return
    goal = (f"Apply brief changes v{made} to v{to}. The brief {_diff_words(runs)}. This video mentions "
            f"{', '.join(hit)}. Change only the lines the change touches and leave the rest as they are; "
            "if nothing here needs to change, say so.") if made else (
            f"Apply brief changes v0 to v{to}: this video was made before the project's brief, which {_diff_words(runs)}. "
            f"This video mentions {', '.join(hit)}. Change only the lines the brief touches; if nothing needs to change, say so.")
    activity.update(job_id, step_label="Voltage is on it", detail={"touches": hit})
    ran = _turn_for_job(video_id, record, job_id, goal, owner, batch_cap)
    if ran is None:
        return
    out, spent = ran
    plan = repo.latest_plan(video_id)
    ready = sum(1 for i in (plan.items if plan else ()) if i.kind == "planned" and i.status == "ready")
    now = repo.get(video_id)
    if now is not None and now.made_with_brief == to:
        why, outcome = "Voltage changed the lines the brief touches and added them.", "updated"
    elif out.get("question"):
        why, outcome = "Voltage has a question in this video. Answer it there.", "waiting"
    elif ready:
        why, outcome = f"{ready} {'line is' if ready == 1 else 'lines are'} ready to hear. Add them in the video.", "proposed"
    else:
        why, outcome = "Voltage read the change and found nothing to change here.", "current"
        briefs.made_with(database, video_id, to)
    activity.finish(job_id, step_label={"updated": "Updated", "waiting": "Waiting on you", "proposed": "Ready to review",
                                        "current": "Up to date, nothing to change"}[outcome],
                    cost_usd=spent or None, detail={"outcome": outcome, "why": why, "spent_usd": spent, "ready": ready,
                                                    "question": _question_of(out)})


def _bring_up_to_date_loop(project_id: str, owner: str) -> None:
    """Every stale video, one after another (F4 runs them as one batch later)."""
    run = json.loads(repo.get_meta(BRIEF_RUN_KEY.format(project_id)) or "{}")
    try:
        for v in run.get("videos", []):
            try:
                _bring_one_up_to_date(project_id, v["video_id"], v["job_id"], int(v["from"]), int(run["to"]), owner)
            except Exception as exc:  # noqa: BLE001 - one video failing never stops the rest
                log.exception("bringing %s up to date failed", v["video_id"])
                activity.fail(v["job_id"], "unknown", str(exc)[:200] or type(exc).__name__)
    finally:
        with _brief_runs_lock:
            final = _brief_run(project_id) or run
            final.update(status="finished", finished_at=_now())
            _save_brief_run(project_id, final)
            with database.tx() as c:
                activity_log.record(c, "brief.update_finished", user_actor(owner), project_id=project_id, target=final["run_id"],
                                    payload={"to": final["to"], "outcomes": {v["video_id"]: v.get("outcome") for v in final["videos"]}})


@app.get("/projects/{project_id}/brief-update")
def get_brief_update(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """A1: the latest "Bring up to date" run (null before the first), each
    video with its job's state and why it ended as it did."""
    _consistency_on(owner)
    _owned_project(project_id, owner)
    return {"run": _brief_run(project_id)}


@app.post("/projects/{project_id}/brief-update", status_code=202)
def start_brief_update(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """A1: bring every video made with an older brief up to date, one video at
    a time. A video the change does not touch is marked current for free."""
    _consistency_on(owner)
    project = _owned_project(project_id, owner)
    with _brief_runs_lock:
        now = _brief_run(project_id)
        if now is not None and now["status"] == "running":
            raise HTTPException(status_code=409, detail="Already bringing the videos up to date.")
        if now is not None and now["status"] == "gate" and now.get("batch_id"):
            # Pressed again at the gate: the old gate is dropped for a fresh plan.
            with contextlib.suppress(batch_mod.BatchError):
                batch_engine.cancel(now["batch_id"])
        stale = briefs.stale_videos(database, project_id)
        if not stale or project.brief_version is None:
            raise HTTPException(status_code=409, detail="Every video is made with the current brief.")
        n = 1 + int((now or {}).get("run_id", "u0")[1:] or 0)
        run = {"run_id": f"u{n}", "to": project.brief_version, "status": "running", "started_at": _now(), "finished_at": None,
               "videos": []}
        # Decision 0: the normal batch gate (videos, lines, cost) first; Go runs it.
        if _gate_brief_updates():
            return {"run": _brief_update_batch(project, owner, run, stale)}
        for vid in stale:
            record = repo.get(vid)
            made = int(record.made_with_brief or 0)
            job = activity.create(vid, "brief_update", step_label="Queued",
                                  detail={"project_id": project_id, "run_id": run["run_id"], "from": made, "to": project.brief_version})
            run["videos"].append({"video_id": vid, "filename": record.source.filename, "from": made, "job_id": job.job_id,
                                  "status": "queued", "step": "Queued", "outcome": None, "why": None})
        _save_brief_run(project_id, run)
        with database.tx() as c:
            activity_log.record(c, "brief.update_started", user_actor(owner), project_id=project_id, target=run["run_id"],
                                payload={"to": run["to"], "videos": stale})
    threading.Thread(target=_bring_up_to_date_loop, args=(project_id, owner), daemon=True,
                     name=f"brief-update-{project_id}").start()
    return {"run": _brief_run(project_id)}


def _gate_brief_updates() -> bool:
    """Decision 0 (2026-10-22): Bring up to date opens the batch gate first,
    with or without `projects.batch`. The old path (no gate, one video after
    another) is kept behind this seam for the tests written for it."""
    return True


def _brief_update_batch(project: Project, owner: str, run: dict, stale: list[str]) -> dict:
    """F4: Bring up to date as one batch turn. Decision 0: the press opens the
    normal gate (videos, lines, cost, cap) and the gate's Go starts it
    (`_brief_run_started`); the free check still runs first in each video.
    The run record points at the batch's children. Called with
    `_brief_runs_lock` held."""
    project_id, to = project.project_id, project.brief_version
    thinking = _thinking_usd(owner)
    children = []
    for vid in stale:
        record = repo.get(vid)
        made = int(record.made_with_brief or 0)
        runs = briefs.diff(database, project_id, made, to) or []
        changed = briefs.changed_words(runs)
        lines = [t for t in _statement_texts(record) if changed & briefs.content_words(t)]
        hit = bool(briefs.touches(runs, _video_texts(vid, record)))
        children.append(_batch_child(vid, f"Apply brief changes v{made} to v{to}", owner, lines=lines, thinking=thinking,
                                     turn=hit, extra={"from": made}))
    opened = _open_batch(project, owner, "brief", f"Apply brief changes to v{to}", children,
                         extra={"to": to, "run_id": run["run_id"]})
    run["batch_id"] = opened["batch_id"]
    run["status"] = "gate"
    for child in opened["children"]:
        run["videos"].append({"video_id": child["video_id"], "filename": child["filename"], "from": child["extra"]["from"],
                              "job_id": None, "status": "planned", "step": "Planned", "outcome": None, "why": None})
    _save_brief_run(project_id, run)
    return dict(_brief_run(project_id), gate=_batch_view(opened["batch_id"]))


def _brief_run_started(started: dict, owner: str) -> None:
    """Decision 0: the gate's Go on a Bring up to date batch; the run follows its children's jobs."""
    project_id = started["project_id"]
    with _brief_runs_lock:
        run = _brief_run(project_id)
        if run is None or run.get("batch_id") != started["batch_id"]:
            return
        jobs_by_video = {c["video_id"]: c.get("job_id") for c in started["children"]}
        for v in run["videos"]:
            v["job_id"] = jobs_by_video.get(v["video_id"])
            v["status"], v["step"] = "queued", "Queued"
        run["status"] = "running"
        _save_brief_run(project_id, run)
        with database.tx() as c:
            activity_log.record(c, "brief.update_started", user_actor(owner), project_id=project_id, target=run["run_id"],
                                payload={"to": run["to"], "videos": [v["video_id"] for v in run["videos"]],
                                         "batch_id": run["batch_id"]})


def _brief_run_cancelled(batch_id: str, project_id: str) -> None:
    with _brief_runs_lock:
        run = _brief_run(project_id)
        if run is not None and run.get("batch_id") == batch_id and run["status"] == "gate":
            run.update(status="finished", finished_at=_now())
            _save_brief_run(project_id, run)


# ── A2: the project check ────────────────────────────────────────────────────
#
# Across every live video in a project, from transcripts and shipped edits
# only (no new audio): facts that disagree, one role in different voices, a
# glossary term said otherwise, a banned word said or a required line
# missing, loudness more than 2 LU apart (app/agent/project_check.py, free),
# plus one cheap Claude text pass for offer names that disagree. One
# Activity job (kind "check") per run, keyed by the project's id. Free after
# a brief change (rules only); `project_check_warnings` is what B3's batch
# export reads before it starts (a warning, never a block).

CHECK_FIX_KEY = "check_fix:{}"
_checks_lock = threading.Lock()
# Tests swap in a fake text pass here; None means the real one when a key is set.
_check_reader = None
_check_reader_built: tuple | None = None


def _check_reader_for():
    """The Claude text pass, or None when there is no Claude key (rules only)."""
    global _check_reader_built
    if _check_reader is not None:
        return _check_reader
    if not settings.anthropic_api_key:
        return None
    key = (settings.anthropic_api_key, settings.anthropic_workspace_id, settings.check_model)
    if _check_reader_built is None or _check_reader_built[0] != key:
        from app.adapters.claude_check import ClaudeChecker
        _check_reader_built = (key, ClaudeChecker(settings.anthropic_api_key, settings.anthropic_workspace_id, model=settings.check_model))
    return _check_reader_built[1]


_DEFAULT_SPEAKER = re.compile(r"^Speaker [A-Za-z0-9_]+$")


def _role_name(name: str | None) -> str | None:
    """A speaker's role name, or None for the default "Speaker A" (not a role anyone named)."""
    return None if not name or _DEFAULT_SPEAKER.match(name.strip()) else name.strip()


def _check_texts(project: Project) -> list[pcheck.VideoText]:
    """What each live video in the project says now: its lines as shot that no
    shipped edit replaced, then its shipped edits (with whose role, which voice
    and the take's own words), and its latest render's measured loudness."""
    out = []
    # Oldest first, the order the videos were made: issues read in that order.
    for record in reversed(repo.list(project.owner, folder=project.project_id)):
        vid = record.source.project_id
        edits = [e for e in repo.list_edits(vid) if not e.reverted]
        covered = [e.plan.selection for e in edits if e.plan.mix in ("replace", "remove")]
        names = {s.label: s.name for s in repo.speakers(vid)}
        by_take = _speakers_by_take(vid)
        passages = []
        for st in statements_of(record.transcript):
            mid = (st.start + st.end) / 2
            if any(sel.start - 1e-3 <= mid <= sel.end + 1e-3 for sel in covered):
                continue
            passages.append(pcheck.Passage(st.text, st.start, "transcript", _role_name(names.get(st.speaker) if st.speaker else None)))
        for e in edits:
            if e.plan.mix == "remove" or not e.plan.new_text.strip():
                continue
            label = by_take.get(e.edit_id, by_take.get(e.candidate_id))
            candidate = repo.get_candidate(vid, e.candidate_id)
            passages.append(pcheck.Passage(e.plan.new_text, e.plan.selection.start, "edit",
                                           _role_name(names.get(label, label) if label else None), _voice_of(e.plan),
                                           tuple(w.text for w in candidate.words) if candidate else ()))
        loud = (repo.settings(vid).get("mix_report") or {}).get("loudness_lufs")
        out.append(pcheck.VideoText(vid, record.source.filename, tuple(sorted(passages, key=lambda p: p.t)),
                                    float(loud) if isinstance(loud, (int, float)) else None))
    return out


def _check_voice_names(project: Project):
    """A voice id's name: the project's and the owner's voices first, the
    vendor's catalogue only when asked (only a role in two voices asks)."""
    names = {v["voice_id"]: v["name"] for v in [*_project_voices(project.project_id), *_my_voices(project.owner)]
             if v.get("voice_id") and v.get("name")}
    return lambda voice_id: names.get(voice_id) or _voice_name(voice_id)


def _check_estimate(project: Project, texts: list[pcheck.VideoText] | None = None) -> dict:
    """What the text pass would cost now, from the transcripts' size and the
    model's price; and whether it can run at all (a Claude key)."""
    est = pcheck.estimate(texts if texts is not None else _check_texts(project), settings.check_model)
    can = _check_reader_for() is not None
    return {**est, "available": can,
            "why": None if can else "No Claude key is set, so only the rule checks can run. They are free."}


def _check_spend_refusal(project: Project, usd: float) -> str | None:
    """The text pass is refused when it would take the project or the month past its ceiling,
    while paid work is paused, or when the owner's credits are used up (launch item 3)."""
    try:
        _ensure_paid_open()
        _ensure_credits(project.owner)
    except SpendCeilingReached as exc:
        return f"{exc} Run the rule checks only; they are free."
    if project.ceiling_usd is not None and ledger.spent_usd_by_folder(project.project_id) + usd > float(project.ceiling_usd) + 1e-9:
        return (f"{project.name} has reached its {money(float(project.ceiling_usd))} project ceiling. "
                "Raise it, or run the rule checks only; they are free.")
    if settings.user_budget_usd is not None:
        mine = ledger.spent_usd_by_owner(project.owner, iso(month_start()))
        if mine + usd > settings.user_budget_usd + 1e-9:
            return (f"You have reached your {money(settings.user_budget_usd)} ceiling for {month_name()}. "
                    "Run the rule checks only; they are free.")
    return None


def _project_meter(project_id: str, what: str, spent: list[float]):
    """A Claude call charged to the project as a whole (no single video), as `what`."""
    def meter(model: str, input_tokens: int, output_tokens: int, cache_read: int = 0, cache_write: int = 0) -> None:
        usd = claude_usd(model, input_tokens, output_tokens, cache_read, cache_write)
        spent.append(usd)
        ledger.record_project_level(project_id, "anthropic", what, input_tokens + output_tokens + cache_read + cache_write, "tokens", usd)
    return meter


def _issues_word(n: int) -> str:
    return "No issues found" if n == 0 else f"{n} {'issue' if n == 1 else 'issues'} found"


def _start_check(project: Project, mode: str, trigger: str, by: str) -> tuple[int, str]:
    check_id = checks_store.start(database, project.project_id, mode, trigger, by)
    job = activity.create(project.project_id, "check", step_label="Queued",
                          detail={"project_id": project.project_id, "check_id": check_id, "mode": mode, "trigger": trigger})
    checks_store.set_job(database, check_id, job.job_id)
    with database.tx() as c:
        activity_log.record(c, "check.started", user_actor(by), project_id=project.project_id, target=str(check_id),
                            payload={"mode": mode, "trigger": trigger})
    return check_id, job.job_id


def _run_check(project_id: str, check_id: int, job_id: str, mode: str, owner: str) -> None:
    """One run: the free checks, then (mode "full") the text pass; the
    issues are stored with the run and the job ends saying how many."""
    activity.start(job_id, "Reading the videos")
    try:
        project = repo.get_project(project_id)
        if project is None:
            raise RuntimeError("This project was deleted.")
        texts = _check_texts(project)
        rules_now = [r.to_dict() for r in rules.list_rules(database, project_id)]
        result = pcheck.deterministic(texts, rules_now, _check_voice_names(project))
        spent: list[float] = []
        if mode == "full":
            reader = _check_reader_for()
            if reader is None:
                result.notes.append("The text pass did not run: no Claude key is set.")
            elif len(texts) < 2:
                result.notes.append("The text pass compares videos; it did not run for one video, and nothing was spent.")
            else:
                activity.update(job_id, step_label="Reading what the videos say", progress=0.5)
                raw = reader.read(pcheck.request_text(texts), meter=_project_meter(project_id, "project check", spent))
                result.issues += pcheck.from_model(raw, texts)
        cost = round(sum(spent), 6)
        checks_store.finish(database, check_id, result.issues, cost, result.notes)
        gone = checks_store.ignored(database, project_id)
        live = [i for i in result.issues if i["fingerprint"] not in gone]
        with database.tx() as c:
            activity_log.record(c, "check.finished", user_actor(owner), project_id=project_id, target=str(check_id),
                                payload={"mode": mode, "issues": len(live), "ignored": len(result.issues) - len(live), "cost_usd": cost})
        activity.finish(job_id, step_label=_issues_word(len(live)), cost_usd=cost or None,
                        detail={"issues": len(live), "ignored": len(result.issues) - len(live)})
    except Exception as exc:  # noqa: BLE001 - a failed check says why; it never takes the server down
        log.exception("project check %s failed", check_id)
        text = str(exc)[:200] or type(exc).__name__
        checks_store.fail(database, check_id, text)
        activity.fail(job_id, "check_failed", f"The check stopped: {text}")


def _auto_check(project_id: str, owner: str) -> None:
    """A2: after a brief change, the free checks run again (rules only, never
    the text pass). Quietly skipped with the flag off, with no videos, or
    while a check runs; never fails the save it follows."""
    try:
        if not (flags.enabled("projects.consistency", owner) and flags.enabled("projects.check", owner)):
            return
        project = repo.get_project(project_id)
        if project is None or not repo.list(project.owner, folder=project_id):
            return
        with _checks_lock:
            now = checks_store.latest(database, project_id)
            if now is not None and now["status"] == "running":
                return
            check_id, job_id = _start_check(project, "rules", "brief", owner)
        _run_check(project_id, check_id, job_id, "rules", owner)
    except Exception:  # noqa: BLE001
        log.exception("the check after a brief change failed")


def project_check_warnings(project_id: str) -> list[dict]:
    """For B3's batch export: the free checks run now (nothing stored,
    nothing spent), as warnings, ignored issues left out. A warning, never a
    block: the caller shows them and lets the export go on."""
    project = repo.get_project(project_id)
    if project is None:
        return []
    texts = _check_texts(project)
    result = pcheck.deterministic(texts, [r.to_dict() for r in rules.list_rules(database, project_id)],
                                  _check_voice_names(project))
    gone = checks_store.ignored(database, project_id)
    return [i for i in result.issues if i["fingerprint"] not in gone]


def _fix_run(project_id: str) -> dict | None:
    raw = repo.get_meta(CHECK_FIX_KEY.format(project_id))
    if not raw:
        return None
    run = json.loads(raw)
    for v in run["videos"]:
        job = activity.get(v["job_id"]) if v.get("job_id") else None
        if job is not None:
            v["status"] = job.status
            v["step"] = job.step_label
            v["outcome"] = job.detail.get("outcome", v.get("outcome"))
            v["why"] = job.error_text if job.status == "failed" else job.detail.get("why", v.get("why"))
    if run["status"] == "running" and all(v["status"] in ("done", "failed", "cancelled") for v in run["videos"]):
        run["status"] = "finished"
    return run


def _check_page(project: Project) -> dict:
    """The project page's Issues panel: the newest run with its job, its
    issues (each saying whether it is ignored), the price of a full check now,
    and the latest Fix in all."""
    check = checks_store.latest(database, project.project_id)
    if check is not None and check["job_id"]:
        job = activity.get(check["job_id"])
        check["job"] = job.to_dict() if job else None
    issues = checks_store.issues(database, check["check_id"]) if check else []
    if check is not None and check["status"] == "running":
        # While a run works, the last finished run's issues stay on screen.
        done = checks_store.latest(database, project.project_id, finished=True)
        issues = checks_store.issues(database, done["check_id"]) if done else []
        check["previous_finished_at"] = done["finished_at"] if done else None
    return {"check": check, "issues": issues, "estimate": _check_estimate(project), "fix_run": _fix_run(project.project_id),
            "videos": len(repo.list(project.owner, folder=project.project_id))}


class CheckRequest(BaseModel):
    mode: Literal["full", "rules"] = "full"


@app.get("/projects/{project_id}/check")
def get_project_check(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """A2: the latest project check (null before the first) and its issues."""
    _check_on(owner)
    return _check_page(_owned_project(project_id, owner))


@app.post("/projects/{project_id}/check", status_code=202)
def start_project_check(project_id: str, req: CheckRequest, owner: str = Depends(current_owner)) -> dict:
    """A2: check the project. `full` adds the Claude text pass (its cost is
    shown before; refused past a ceiling or with no key); `rules` is free."""
    _check_on(owner)
    project = _owned_project(project_id, owner)
    if req.mode == "full":
        if _check_reader_for() is None:
            raise HTTPException(status_code=409, detail="No Claude key is set, so only the rule checks can run. Choose Rules only.")
        refusal = _check_spend_refusal(project, _check_estimate(project)["usd"])
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)
    with _checks_lock:
        now = checks_store.latest(database, project_id)
        if now is not None and now["status"] == "running":
            raise HTTPException(status_code=409, detail="A check is already running.")
        check_id, job_id = _start_check(project, req.mode, "user", owner)
    threading.Thread(target=_run_check, args=(project_id, check_id, job_id, req.mode, owner), daemon=True,
                     name=f"check-{project_id}").start()
    return _check_page(project)


def _issue_or_404(project_id: str, issue_id: int) -> dict:
    found = checks_store.issue(database, project_id, issue_id)
    if found is None:
        raise HTTPException(status_code=404, detail="issue not found")
    return found


@app.post("/projects/{project_id}/check/issues/{issue_id}/ignore")
def ignore_check_issue(project_id: str, issue_id: int, owner: str = Depends(current_owner)) -> dict:
    """A2: ignore an issue until the text it was found in changes."""
    _check_on(owner)
    project = _owned_project(project_id, owner)
    found = _issue_or_404(project_id, issue_id)
    checks_store.ignore(database, project_id, found["fingerprint"], owner)
    with database.tx() as c:
        activity_log.record(c, "check.issue_ignored", user_actor(owner), project_id=project_id, target=str(issue_id),
                            payload={"kind": found["kind"], "fingerprint": found["fingerprint"]})
    return _check_page(project)


def _fix_goal(issue: dict, video_id: str) -> str:
    here = [p for p in issue["places"] if p["video_id"] == video_id]
    where = "; ".join(f"at {pcheck.clock(p['t'])}: “{p['text']}”" for p in here if p["t"] is not None and p["text"])
    return (f"Fix this from the project check: {issue['message']}"
            + (f" In this video it is {where}." if where else "")
            + " Change only what the issue is about and keep everything else as it is; if this video is right as it is, say so.")


class FixRequest(BaseModel):
    video_id: str


@app.post("/projects/{project_id}/check/issues/{issue_id}/fix", status_code=202)
def fix_check_issue(project_id: str, issue_id: int, req: FixRequest, owner: str = Depends(current_owner)) -> dict:
    """A2: Fix in this video: a normal turn in that video with the issue as its goal."""
    _check_on(owner)
    _owned_project(project_id, owner)
    found = _issue_or_404(project_id, issue_id)
    if req.video_id not in {p["video_id"] for p in found["places"]}:
        raise HTTPException(status_code=422, detail="That video is not part of this issue.")
    record = _owned(req.video_id, owner)
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    started = _start_turn(req.video_id, record, _fix_goal(found, req.video_id), owner)
    with database.tx() as c:
        activity_log.record(c, "check.fix_started", user_actor(owner), video_id=req.video_id, project_id=project_id,
                            target=str(issue_id), payload={"kind": found["kind"]})
    t = next((p["t"] for p in found["places"] if p["video_id"] == req.video_id and p["t"] is not None), None)
    return {"video_id": req.video_id, "job_id": started["job_id"], "t": t}


# "Fix in all": with `projects.batch` on (F4), one batch turn (`_fix_all_batch`);
# off, the same sequential loop A1's Bring up to date uses, one Activity job
# (kind "check") per video.

def _fix_one(video_id: str, job_id: str, goal: str, owner: str, batch_cap: float | None = None,
             done_label: str = "Fixed") -> None:
    """One video's turn with `goal` (A2's Fix in all; F4's batch children with `batch_cap`)."""
    activity.start(job_id, "Voltage is on it")
    record = repo.get(video_id)
    if record is None:
        activity.fail(job_id, "gone", "This video was deleted.")
        return
    if not _agent_on():
        activity.fail(job_id, "no_agent", "Voltage needs Claude to change this video (set AVE_AGENT=1 and an Anthropic key).")
        return
    shipped = len([e for e in repo.list_edits(video_id) if not e.reverted])
    ran = _turn_for_job(video_id, record, job_id, goal, owner, batch_cap)
    if ran is None:
        return
    out, spent = ran
    outcome, why, ready = _turn_outcome(video_id, out, shipped)
    activity.finish(job_id, step_label={"updated": done_label, "waiting": "Waiting on you", "proposed": "Ready to review",
                                        "current": "Nothing to change"}[outcome],
                    cost_usd=spent or None, detail={"outcome": outcome, "why": why, "spent_usd": spent, "ready": ready,
                                                    "question": _question_of(out)})


def _turn_outcome(video_id: str, out: dict, shipped_before: int) -> tuple[str, str, int]:
    """How a video's turn ended, for a run row: updated (it added lines),
    waiting (a question), proposed (lines ready to hear) or current."""
    plan = repo.latest_plan(video_id)
    ready = sum(1 for i in (plan.items if plan else ()) if i.kind == "planned" and i.status == "ready")
    if len([e for e in repo.list_edits(video_id) if not e.reverted]) > shipped_before:
        return "updated", "Voltage fixed it and added the change.", ready
    if out.get("question"):
        return "waiting", "Voltage has a question in this video. Answer it there.", ready
    if ready:
        return "proposed", f"{ready} {'line is' if ready == 1 else 'lines are'} ready to hear. Add them in the video.", ready
    return "current", "Voltage found nothing to change here.", ready


def _question_of(out: dict) -> dict | None:
    """A turn's closing question as a run row shows it: the words and the options."""
    q = out.get("question")
    if not q:
        return None
    return {"text": q.get("text"), "options": [o.get("label") if isinstance(o, dict) else o for o in q.get("options") or []]}


def _await_turn(turn_job_id: str, wait_s: float = None) -> Job | None:
    deadline = time.time() + (BRIEF_TURN_WAIT_S if wait_s is None else wait_s)
    turn_job = jobs.get(turn_job_id)
    while turn_job is not None and not turn_job.done and time.time() < deadline:
        time.sleep(0.05)
        turn_job = jobs.get(turn_job_id)
    return turn_job


def _turn_for_job(video_id: str, record: ProjectRecord, job_id: str, goal: str, owner: str,
                  batch_cap: float | None = None) -> tuple[dict, float] | None:
    """Run one ordinary turn for a run's job (A1, A2, F4) and wait for it:
    (its result, what it spent), or None with the job failed saying why."""
    try:
        started = _start_turn(video_id, record, goal, owner, cap_usd=batch_cap, batch=batch_cap is not None)
    except HTTPException as exc:
        activity.fail(job_id, "turn_refused", str(exc.detail))
        return None
    activity.update(job_id, detail={"turn_ids": [started["job_id"]]})
    turn_job = _await_turn(started["job_id"])
    if turn_job is None or not turn_job.done:
        activity.fail(job_id, "timeout", "Voltage's turn on this video took too long; it is still in the video's chat.")
        return None
    out = turn_job.result or {}
    spent = round(float(out.get("turn_usd") or out.get("spent_usd") or 0.0), 4)
    if turn_job.status == "failed" or out.get("stopped") == "error":
        activity.fail(job_id, "turn_failed", (out.get("error") or turn_job.error or "Voltage's turn failed.")[:200], cost_usd=spent or None)
        return None
    if out.get("ceiling"):
        # The turn met a ceiling before it could spend: the video stops here, saying which.
        activity.fail(job_id, "ceiling", (out.get("reply") or "A spending ceiling was reached.")[:300], cost_usd=spent or None)
        return None
    return out, spent


def _fix_all_loop(project_id: str, owner: str) -> None:
    run = json.loads(repo.get_meta(CHECK_FIX_KEY.format(project_id)) or "{}")
    try:
        for v in run.get("videos", []):
            try:
                _fix_one(v["video_id"], v["job_id"], v["goal"], owner)
            except Exception as exc:  # noqa: BLE001 - one video failing never stops the rest
                log.exception("fixing %s failed", v["video_id"])
                activity.fail(v["job_id"], "unknown", str(exc)[:200] or type(exc).__name__)
    finally:
        with _checks_lock:
            final = _fix_run(project_id) or run
            final.update(status="finished", finished_at=_now())
            repo.set_meta(CHECK_FIX_KEY.format(project_id), json.dumps(final))
            with database.tx() as c:
                activity_log.record(c, "check.fix_all_finished", user_actor(owner), project_id=project_id, target=final["run_id"],
                                    payload={"issue_id": final["issue_id"], "outcomes": {v["video_id"]: v.get("outcome") for v in final["videos"]}})


@app.post("/projects/{project_id}/check/issues/{issue_id}/fix-all", status_code=202)
def fix_check_issue_everywhere(project_id: str, issue_id: int, owner: str = Depends(current_owner)) -> dict:
    """A2: Fix in all: every video the issue names, one after another, each an ordinary turn."""
    _check_on(owner)
    project = _owned_project(project_id, owner)
    found = _issue_or_404(project_id, issue_id)
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    with _checks_lock:
        now = _fix_run(project_id)
        if now is not None and now["status"] == "running":
            raise HTTPException(status_code=409, detail="Already fixing an issue across the videos.")
        n = 1 + int((now or {}).get("run_id", "x0")[1:] or 0)
        run = {"run_id": f"x{n}", "issue_id": issue_id, "message": found["message"], "status": "running", "started_at": _now(),
               "finished_at": None, "videos": []}
        if _batch_on(owner):
            _fix_all_batch(project, owner, run, found)
            return _check_page(project)
        for vid in dict.fromkeys(p["video_id"] for p in found["places"]):
            record = repo.get(vid)
            if record is None or record.folder_id != project_id:
                continue
            job = activity.create(vid, "check", step_label="Queued", detail={"project_id": project_id, "issue_id": issue_id, "fix": True})
            run["videos"].append({"video_id": vid, "filename": record.source.filename, "job_id": job.job_id, "goal": _fix_goal(found, vid),
                                  "status": "queued", "step": "Queued", "outcome": None, "why": None})
        if not run["videos"]:
            raise HTTPException(status_code=409, detail="None of the videos this issue names are in the project now.")
        repo.set_meta(CHECK_FIX_KEY.format(project_id), json.dumps(run))
        with database.tx() as c:
            activity_log.record(c, "check.fix_all_started", user_actor(owner), project_id=project_id, target=run["run_id"],
                                payload={"issue_id": issue_id, "videos": [v["video_id"] for v in run["videos"]]})
    threading.Thread(target=_fix_all_loop, args=(project_id, owner), daemon=True, name=f"check-fix-{project_id}").start()
    return _check_page(project)


def _fix_all_batch(project: Project, owner: str, run: dict, found: dict) -> None:
    """F4 (`projects.batch` on): Fix in all as one batch turn, the press its
    gate's yes. Called with `_checks_lock` held."""
    project_id = project.project_id
    thinking = _thinking_usd(owner)
    children = []
    for vid in dict.fromkeys(p["video_id"] for p in found["places"]):
        record = repo.get(vid)
        if record is None or record.folder_id != project_id:
            continue
        children.append(_batch_child(vid, _fix_goal(found, vid), owner, thinking=thinking,
                                     lines=[p["text"] for p in found["places"] if p["video_id"] == vid and p.get("text")]))
    if not children:
        raise HTTPException(status_code=409, detail="None of the videos this issue names are in the project now.")
    opened = _open_batch(project, owner, "fix", found["message"], children,
                         extra={"issue_id": run["issue_id"], "run_id": run["run_id"]})
    started = _go_batch(opened, owner)
    run["batch_id"] = started["batch_id"]
    for child in started["children"]:
        run["videos"].append({"video_id": child["video_id"], "filename": child["filename"], "job_id": child["job_id"],
                              "goal": child["goal"], "status": "queued", "step": "Queued", "outcome": None, "why": None})
    repo.set_meta(CHECK_FIX_KEY.format(project_id), json.dumps(run))
    with database.tx() as c:
        activity_log.record(c, "check.fix_all_started", user_actor(owner), project_id=project_id, target=run["run_id"],
                            payload={"issue_id": run["issue_id"], "videos": [v["video_id"] for v in run["videos"]],
                                     "batch_id": run["batch_id"]})


# ── F4: the batch turn engine ────────────────────────────────────────────────
#
# One goal across N videos of a project: one plan (a free, deterministic
# estimate per video), one gate (the totals and the parent's cap), then one
# ordinary turn per video, three at a time (app/jobs/batch.py). Behind
# `projects.batch`; A1's Bring up to date and A2's Fix in all run through it
# when the flag is on and keep their own loops when it is off.

def _batch_on(owner: str) -> bool:
    return flags.enabled("projects.batch", owner)


def _batch_flag(owner: str) -> None:
    if not _batch_on(owner):
        raise HTTPException(status_code=404, detail="Not found")


def _voicing_usd(text: str) -> float:
    """What voicing one line of these words costs (every take is billed), as the agent's own estimate reckons it."""
    takes = max(1, int(getattr(voice, "takes_per_line", 1)))
    chars = voice.cost_of(EditPlan(Selection(0.0, 1.0), text, getattr(voice, "default_voice", "speaker-1"))) * takes
    return chars * budget.usd_per_1k / 1000


def _thinking_usd(owner: str) -> float | None:
    """The median of what Voltage's own thinking cost per turn, from this
    owner's last turns; None with no history (no number that was not measured)."""
    with database.tx() as c:
        rows = c.execute(
            "SELECT turn_id, SUM(usd) AS usd FROM usage WHERE vendor = 'anthropic' AND turn_id IS NOT NULL "
            "AND project_id IN (SELECT id FROM videos WHERE owner = ?) GROUP BY project_id, turn_id "
            "ORDER BY MAX(at) DESC LIMIT 20", (owner,)).fetchall()
    spent = [float(r["usd"]) for r in rows if r["usd"]]
    return statistics.median(spent) if spent else None


def _statement_texts(record: ProjectRecord) -> list[str]:
    return [st.text for st in statements_of(record.transcript)] or [" ".join(w.text for w in record.transcript.words)]


def _batch_child(video_id: str, goal: str, owner: str, *, lines: list[str] | None = None, thinking: float | None,
                 turn: bool = True, extra: dict | None = None) -> batch_mod.Child:
    """One video's part of the plan. `lines`: the lines the goal names here
    (None: worked out from the goal's words against the video's lines, and
    left unknown when none share a word); `turn=False`: nothing to run (A1's
    free check found nothing), so nothing is estimated."""
    record = repo.get(video_id)
    cap = round(float(_settings(video_id, owner)["turn_usd"]), 2)
    if lines is None:
        words = briefs.content_words(goal)
        lines = [t for t in _statement_texts(record) if words & briefs.content_words(t)] or None
    if not turn:
        est, n = 0.0, 0
    else:
        n = None if lines is None else len(lines)
        est = None if lines is None or thinking is None else thinking + sum(_voicing_usd(t) for t in lines)
    # B2: a language version is named with its language (it shares the master's file name).
    name = record.source.filename + (f" · {langs.label(record.language)}" if record.language else "")
    return batch_mod.Child(video_id=video_id, filename=name, goal=goal, cap_usd=cap,
                           stage=getattr(record, "stage", None) or "draft", lines=n, est_usd=est, extra=dict(extra or {}))


def _batch_start_refusal(project: Project, owner: str, cap: float) -> str | None:
    """Decision 3: a batch does not start above the project's ceiling (or the
    month's) until the owner raises it; the sentence names the ceiling.
    Launch item 3: nor while paid work is paused or the credits are used up."""
    try:
        _ensure_paid_open()
        _ensure_credits(owner)
    except SpendCeilingReached as exc:
        return str(exc)
    if project.ceiling_usd is not None:
        ours = ledger.spent_usd_by_folder(project.project_id)
        if ours + cap > float(project.ceiling_usd) + 1e-9:
            return (f"This batch may spend up to {money(cap)}, which would take {project.name} past its "
                    f"{money(float(project.ceiling_usd))} project ceiling ({money(ours)} spent). "
                    "Raise the ceiling on the project page, or pick fewer videos.")
    if settings.user_budget_usd is not None:
        mine = ledger.spent_usd_by_owner(owner, iso(month_start()))
        if mine + cap > settings.user_budget_usd + 1e-9:
            return (f"This batch may spend up to {money(cap)}, which would take you past your "
                    f"{money(settings.user_budget_usd)} ceiling for {month_name()} ({money(mine)} spent). Pick fewer videos.")
    return None


def _batch_refusal(child: dict, held: float) -> str | None:
    """Why a child may not reserve its cap now: the video's, the project's or
    the month's ceiling would be crossed, counting what running children hold."""
    record = repo.get(child["video_id"])
    if record is None:
        return "This video was deleted."
    cap = float(child["cap_usd"])
    spent = ledger.spent_usd(record.source.project_id)
    if spent + cap > ledger.ceiling_usd + 1e-9:
        return (f"Stopped before starting: this video's turn could take it past its {money(ledger.ceiling_usd)} "
                f"video ceiling ({money(spent)} spent).")
    project = _folder_of(record)
    if project is not None and project.ceiling_usd is not None:
        ours = ledger.spent_usd_by_folder(project.project_id)
        if ours + held + cap > float(project.ceiling_usd) + 1e-9:
            return (f"Stopped before starting: this video's turn could take {project.name} past its "
                    f"{money(float(project.ceiling_usd))} project ceiling ({money(ours)} spent).")
    if settings.user_budget_usd is not None:
        mine = ledger.spent_usd_by_owner(record.owner, iso(month_start()))
        if mine + held + cap > settings.user_budget_usd + 1e-9:
            return (f"Stopped before starting: this video's turn could take you past your "
                    f"{money(settings.user_budget_usd)} ceiling for {month_name()} ({money(mine)} spent).")
    return None


def _run_batch_child(record: dict, child: dict) -> None:
    """One video of a batch, by where the batch came from: A1's brief change
    (the free check first), A2's issue, or the user's own goal."""
    owner, job_id = record["owner"], child["job_id"]
    if record["source"] == "brief":
        _bring_one_up_to_date(record["project_id"], child["video_id"], job_id, int(child["extra"].get("from") or 0),
                              int(record["extra"]["to"]), owner, batch_cap=float(child["cap_usd"]))
    else:
        _fix_one(child["video_id"], job_id, child["goal"], owner, batch_cap=float(child["cap_usd"]),
                 done_label={"fix": "Fixed", "language": "Translated"}.get(record["source"], "Changed"))


def _batch_closed(record: dict) -> None:
    """The batch ended: A1's and A2's run records end with it, and the log says so."""
    owner, project_id = record["owner"], record["project_id"]
    if record["source"] == "brief":
        with _brief_runs_lock:
            final = _brief_run(project_id)
            if final is not None and final.get("batch_id") == record["batch_id"]:
                final.update(status="finished", finished_at=_now())
                _save_brief_run(project_id, final)
                with database.tx() as c:
                    activity_log.record(c, "brief.update_finished", user_actor(owner), project_id=project_id, target=final["run_id"],
                                        payload={"to": final["to"], "batch_id": record["batch_id"],
                                                 "outcomes": {v["video_id"]: v.get("outcome") for v in final["videos"]}})
    elif record["source"] == "fix" and record["extra"].get("run_id"):
        with _checks_lock:
            final = _fix_run(project_id)
            if final is not None and final.get("batch_id") == record["batch_id"]:
                final.update(status="finished", finished_at=_now())
                repo.set_meta(CHECK_FIX_KEY.format(project_id), json.dumps(final))
                with database.tx() as c:
                    activity_log.record(c, "check.fix_all_finished", user_actor(owner), project_id=project_id, target=final["run_id"],
                                        payload={"issue_id": final["issue_id"], "batch_id": record["batch_id"],
                                                 "outcomes": {v["video_id"]: v.get("outcome") for v in final["videos"]}})
    summary = record.get("summary") or {}
    with database.tx() as c:
        activity_log.record(c, "batch.cancelled" if record.get("cancelled") else "batch.finished", user_actor(owner),
                            project_id=project_id, target=record["batch_id"],
                            payload={"source": record["source"], **{k: summary.get(k) for k in ("finished", "waiting", "failed", "cancelled", "spent_usd")}})


batch_engine = batch_mod.BatchEngine(activity, repo.get_meta, repo.set_meta, _run_batch_child, _batch_refusal,
                                     lambda video_id: _stop_video(video_id), on_close=_batch_closed)


def _open_batch(project: Project, owner: str, source: str, goal: str, children: list, extra: dict | None = None) -> dict:
    """Plan once and open the gate, refused above the project's or month's ceiling."""
    cap = round(sum(c.cap_usd for c in children), 2)
    refusal = _batch_start_refusal(project, owner, cap)
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    turns = sum(1 for c in children if c.lines != 0)
    try:
        record = batch_engine.open_gate(project.project_id, owner, source, goal, children,
                                        est_s=batch_mod.batch_seconds(batch_mod.child_seconds(activity), turns), extra=extra)
    except batch_mod.BatchError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    with database.tx() as c:
        activity_log.record(c, "batch.planned", user_actor(owner), project_id=project.project_id, target=record["batch_id"],
                            payload={"source": source, "videos": [ch.video_id for ch in children], "totals": record["totals"]})
    return record


def _go_batch(record: dict, owner: str) -> dict:
    project = repo.get_project(record["project_id"])
    if project is not None:
        refusal = _batch_start_refusal(project, owner, float(record["totals"]["cap_usd"]))
        if refusal:
            raise HTTPException(status_code=409, detail=refusal)
    try:
        started = batch_engine.go(record["batch_id"])
    except batch_mod.BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with database.tx() as c:
        activity_log.record(c, "batch.started", user_actor(owner), project_id=record["project_id"], target=record["batch_id"],
                            payload={"source": record["source"], "cap_usd": record["totals"]["cap_usd"]})
    return started


ROW_LABELS = {"planned": "Planned", "queued": "Queued", "working": "Working", "ready": "Ready to review",
              "nothing": "Nothing to change", "failed": "Failed", "waiting": "Waiting on you", "cancelled": "Cancelled",
              "added": "Added"}


def _batch_row(child: dict) -> dict:
    """One video's row as the board shows it, read live: a finished child
    reads its video as it is now (an answer turn running, a question still
    open, proposals still waiting, lines added)."""
    job = child.get("job")
    row = {"video_id": child["video_id"], "filename": child["filename"], "stage": child.get("stage") or "draft",
           "stage_label": stages.LABELS.get(child.get("stage") or "draft", "Draft"), "lines": child.get("lines"),
           "est_usd": None if child.get("est_usd") is None else round(child["est_usd"], 4), "cap_usd": child["cap_usd"],
           "job_id": child.get("job_id"), "why": None, "question": None, "ready": 0,
           "spent_usd": round(float((job or {}).get("detail", {}).get("spent_usd") or (job or {}).get("cost_usd") or 0.0)
                              + sum(float(a.get("spent_usd") or 0.0) for a in child.get("answers") or []), 4),
           "added": child.get("added"), "answers": child.get("answers") or []}
    if job is None:
        state = "planned"
    elif job["status"] == "queued":
        state = "queued"
    elif job["status"] == "running":
        state, row["why"] = "working", job["step_label"]
    elif job["status"] == "failed":
        state, row["why"] = "failed", job["error_text"]
    elif job["status"] == "cancelled":
        state, row["why"] = "cancelled", job["step_label"]
    else:
        record = repo.get(child["video_id"])
        plan = repo.latest_plan(child["video_id"]) if record is not None else None
        ready = sum(1 for i in (plan.items if plan else ()) if i.kind == "planned" and i.status == "ready")
        open_q = plan.question if plan is not None and plan.status == "clarifying" and plan.question \
            and not plan.question.get("resolved") else None
        busy = any(j.kind == "turn" and j.project_id == child["video_id"] and not j.done for j in jobs.all())
        row["ready"] = ready
        if record is None:
            state, row["why"] = "failed", "This video was deleted."
        elif busy and child.get("answers"):
            state, row["why"] = "working", "Voltage is on your answer"
        elif open_q:
            state = "waiting"
            row["question"] = {"text": open_q.get("text"),
                               "options": [o.get("label") if isinstance(o, dict) else o for o in open_q.get("options") or []]}
        elif ready:
            state = "ready"
            row["why"] = f"{ready} {'line is' if ready == 1 else 'lines are'} ready to hear."
        elif child.get("added"):
            state = "added"
            n = len(child["added"].get("edit_ids") or [])
            row["why"] = f"{n} {'line' if n == 1 else 'lines'} added."
        else:
            state, row["why"] = "nothing", job["detail"].get("why") or "Voltage found nothing to change here."
            if job["detail"].get("outcome") == "updated":
                state = "added"
    row["state"], row["label"] = state, ROW_LABELS[state]
    return row


def _batch_view(batch_id: str) -> dict:
    record = batch_engine.get(batch_id)
    if record is None:
        raise HTTPException(status_code=404, detail="batch not found")
    rows = [_batch_row(c) for c in record["children"]]
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["state"]] = counts.get(r["state"], 0) + 1
    return {"batch_id": record["batch_id"], "project_id": record["project_id"], "source": record["source"],
            "goal": record["goal"], "phase": record["phase"], "status": record["status"], "step": record["step"],
            "created_at": record["created_at"], "started_at": record.get("started_at"), "finished_at": record.get("finished_at"),
            "totals": record["totals"], "summary": record.get("summary"), "rows": rows, "counts": counts,
            "spent_usd": round(sum(r["spent_usd"] for r in rows), 4),
            "can_add": any(r["state"] == "ready" for r in rows) and record["phase"] != "gate",
            **_approved_note([c["video_id"] for c in record["children"]], record["project_id"])}


def _approved_note(video_ids: list[str], project_id: str) -> dict:
    """Decision 0: the gate (and the board) says how many Approved videos
    adding would take back to Draft. Empty without `projects.review`."""
    project = repo.get_project(project_id)
    if project is None or not _review_on(project.owner):
        return {"approved_count": 0, "approved_note": None}
    n = sum(1 for v in video_ids if stages.current(database, v) == "approved")
    note = None if n == 0 else ("1 approved video will return to Draft." if n == 1
                                else f"{n} approved videos will return to Draft.")
    return {"approved_count": n, "approved_note": note}


def _owned_batch(project_id: str, batch_id: str, owner: str) -> dict:
    """A batch of the caller's project. Bring up to date (A1) uses the batch
    gate with only `projects.consistency` on (decision 0); every other batch needs `projects.batch`."""
    _owned_project(project_id, owner)
    record = batch_engine.get(batch_id)
    if record is None or record["project_id"] != project_id:
        raise HTTPException(status_code=404, detail="batch not found")
    if not _batch_on(owner) and not (record["source"] == "brief" and flags.enabled("projects.consistency", owner)):
        raise HTTPException(status_code=404, detail="Not found")
    return record


class BatchRequest(BaseModel):
    # "ask": the user's own goal; "fix": an issue from the project check (A2).
    source: Literal["ask", "fix"] = "ask"
    goal: str | None = None
    issue_id: int | None = None
    # None: every live video in the project (for a fix, every video the issue names).
    video_ids: list[str] | None = None


@app.post("/projects/{project_id}/batches", status_code=201)
def plan_batch(project_id: str, req: BatchRequest, owner: str = Depends(current_owner)) -> dict:
    """F4/B1: plan one goal across the project's videos and open the one gate:
    the videos, the lines the goal names, about what it costs (from measured
    prices and this owner's own turns), about how long (from finished batch
    turns; left out with none) and the parent's cap, the sum of each video's
    turn cap. Nothing runs or spends until Go."""
    _batch_flag(owner)
    project = _owned_project(project_id, owner)
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    live = {r.source.project_id: r for r in reversed(repo.list(owner, folder=project_id))}   # oldest first
    thinking = _thinking_usd(owner)
    if req.source == "fix":
        if req.issue_id is None:
            raise HTTPException(status_code=422, detail="Name the issue to fix.")
        found = _issue_or_404(project_id, req.issue_id)
        named = [v for v in dict.fromkeys(p["video_id"] for p in found["places"]) if v in live]
        picked = [v for v in named if req.video_ids is None or v in req.video_ids]
        children = [_batch_child(v, _fix_goal(found, v), owner, thinking=thinking,
                                 lines=[p["text"] for p in found["places"] if p["video_id"] == v and p.get("text")])
                    for v in picked]
        goal, extra = found["message"], {"issue_id": req.issue_id}
    else:
        goal = (req.goal or "").strip()
        if not goal:
            raise HTTPException(status_code=422, detail="Say what you want done in the videos.")
        picked = [v for v in live if req.video_ids is None or v in req.video_ids]
        children = [_batch_child(v, goal, owner, thinking=thinking) for v in picked]
        extra = {}
    if not children:
        raise HTTPException(status_code=422, detail="Pick at least one video.")
    return _batch_view(_open_batch(project, owner, req.source, goal, children, extra)["batch_id"])


@app.get("/projects/{project_id}/batches")
def list_batches(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """F4: the project's batches, newest first (the latest in full)."""
    _batch_flag(owner)
    _owned_project(project_id, owner)
    ids = batch_engine.of_project(project_id)
    return {"batches": [_batch_view(b) for b in ids[:10]]}


@app.get("/projects/{project_id}/batches/{batch_id}")
def get_batch(project_id: str, batch_id: str, owner: str = Depends(current_owner)) -> dict:
    _owned_batch(project_id, batch_id, owner)
    return _batch_view(batch_id)


@app.post("/projects/{project_id}/batches/{batch_id}/go", status_code=202)
def go_batch(project_id: str, batch_id: str, owner: str = Depends(current_owner)) -> dict:
    """F4: the gate's yes. Every video is queued; three run at a time."""
    record = _owned_batch(project_id, batch_id, owner)
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    started = _go_batch(record, owner)
    if record["source"] == "brief":
        _brief_run_started(started, owner)
    return _batch_view(batch_id)


@app.post("/projects/{project_id}/batches/{batch_id}/cancel")
def cancel_batch(project_id: str, batch_id: str, owner: str = Depends(current_owner)) -> dict:
    """F4: at the gate, drop it; running, the queued videos are cancelled and
    the running ones finish the step they are on (each video's Stop)."""
    record = _owned_batch(project_id, batch_id, owner)
    try:
        batch_engine.cancel(batch_id)
    except batch_mod.BatchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if record["source"] == "brief":
        _brief_run_cancelled(batch_id, project_id)
    return _batch_view(batch_id)


class BatchAnswer(BaseModel):
    text: str


def _answer_settles(batch_id: str, video_id: str, index: int, turn_job_id: str) -> None:
    turn_job = _await_turn(turn_job_id)
    out = (turn_job.result or {}) if turn_job is not None else {}
    spent = round(float(out.get("turn_usd") or out.get("spent_usd") or 0.0), 4)

    def note(record: dict) -> None:
        for child in record["children"]:
            if child["video_id"] == video_id and index < len(child["answers"]):
                child["answers"][index].update(spent_usd=spent, status=getattr(turn_job, "status", "failed"))
    batch_engine.update(batch_id, note)


@app.post("/projects/{project_id}/batches/{batch_id}/videos/{video_id}/answer", status_code=202)
def answer_batch_video(project_id: str, batch_id: str, video_id: str, req: BatchAnswer,
                       owner: str = Depends(current_owner)) -> dict:
    """F4: answer a paused video's question from the batch board: an
    ordinary turn in that video with the answer, under what is left of its
    share of the batch's cap."""
    record = _owned_batch(project_id, batch_id, owner)
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="Say your answer.")
    child = next((c for c in record["children"] if c["video_id"] == video_id), None)
    if child is None:
        raise HTTPException(status_code=404, detail="That video is not in this batch.")
    row = _batch_row(child)
    if row["state"] != "waiting":
        raise HTTPException(status_code=409, detail="This video is not waiting on an answer.")
    left = round(float(child["cap_usd"]) - row["spent_usd"], 2)
    if left < 0.01:
        raise HTTPException(status_code=409, detail=(f"This video has used its {money(float(child['cap_usd']))} share of the batch. "
                                                     "Open it to carry on there."))
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    video = _owned(video_id, owner)
    started = _start_turn(video_id, video, text, owner, cap_usd=left, batch=True)
    index = len(child["answers"])

    def note(rec: dict) -> None:
        for c in rec["children"]:
            if c["video_id"] == video_id:
                c["answers"].append({"text": text[:200], "turn_job_id": started["job_id"], "at": _now(), "spent_usd": 0.0})
    batch_engine.update(batch_id, note)
    with database.tx() as c:
        activity_log.record(c, "batch.answered", user_actor(owner), video_id=video_id, project_id=project_id, target=batch_id,
                            payload={"answer": text[:200]})
    threading.Thread(target=_answer_settles, args=(batch_id, video_id, index, started["job_id"]), daemon=True,
                     name=f"batch-answer-{video_id}").start()
    return _batch_view(batch_id)


def _passing_items(video_id: str) -> tuple[Plan | None, list[str]]:
    """B1: a video's proposals that passed: ready, their take passed its
    check and breaks no word rule."""
    plan = repo.latest_plan(video_id)
    ids = []
    for item in (plan.items if plan else ()):
        if item.kind != "planned" or item.status != "ready" or not item.candidate_id:
            continue
        candidate = repo.get_candidate(video_id, item.candidate_id)
        if candidate is None or not candidate.continuity.passed or (item.word_rule or {}).get("breaks"):
            continue
        ids.append(item.item_id)
    return plan, ids


class AddAllRequest(BaseModel):
    # C1: yes to adding to videos that are Approved (they go back to Draft).
    confirm_stage: bool = False


@app.post("/projects/{project_id}/batches/{batch_id}/add-all")
def add_all_batch(project_id: str, batch_id: str, req: AddAllRequest | None = None,
                  owner: str = Depends(current_owner)) -> dict:
    """B1: Add all that passed. Every video of the batch with proposals that
    passed is shipped as its own Add all (its own render), and what each
    added is kept so it can be undone in one step per video. C1: an Approved
    video among them needs `confirm_stage` first."""
    record = _owned_batch(project_id, batch_id, owner)
    if record["phase"] == "gate":
        raise HTTPException(status_code=409, detail="Nothing has run yet. Go first.")
    _stage_gate([c["video_id"] for c in record["children"] if _passing_items(c["video_id"])[1]], owner,
                bool(req and req.confirm_stage))
    added: dict[str, dict] = {}
    for child in record["children"]:
        video = repo.get(child["video_id"])
        if video is None or video.owner != owner:
            continue
        plan, ids = _passing_items(child["video_id"])
        if plan is None or not ids:
            continue
        result = _ship(child["video_id"], video, plan.plan_id, ids)
        edit_ids = [a["edit_id"] for a in result["approved"]]
        if edit_ids:
            added[child["video_id"]] = {"edit_ids": [*((child.get("added") or {}).get("edit_ids") or []), *edit_ids],
                                        "at": _now(), "undone_at": None}
    if not added:
        raise HTTPException(status_code=409, detail="No proposal in this batch passed its checks. Open a video to hear its lines.")

    def note(rec: dict) -> None:
        for c in rec["children"]:
            if c["video_id"] in added:
                c["added"] = added[c["video_id"]]
    batch_engine.update(batch_id, note)
    with database.tx() as c:
        activity_log.record(c, "batch.added_all", user_actor(owner), project_id=project_id, target=batch_id,
                            payload={"videos": {v: len(a["edit_ids"]) for v, a in added.items()}})
    return _batch_view(batch_id)


@app.post("/projects/{project_id}/batches/{batch_id}/videos/{video_id}/undo-add")
def undo_batch_add(project_id: str, batch_id: str, video_id: str, owner: str = Depends(current_owner)) -> dict:
    """B1: the one undo per video for what Add all that passed added there:
    each line goes back to a proposal, as Take it out does."""
    record = _owned_batch(project_id, batch_id, owner)
    child = next((c for c in record["children"] if c["video_id"] == video_id), None)
    if child is None or not child.get("added") or child["added"].get("undone_at"):
        raise HTTPException(status_code=409, detail="Nothing the batch added here is left to undo.")
    _owned(video_id, owner)
    for edit_id in child["added"]["edit_ids"]:
        _revert(video_id, edit_id)

    def note(rec: dict) -> None:
        for c in rec["children"]:
            if c["video_id"] == video_id:
                c["added"] = {**c["added"], "undone_at": _now()}
    batch_engine.update(batch_id, note)
    with database.tx() as c:
        activity_log.record(c, "batch.add_undone", user_actor(owner), video_id=video_id, project_id=project_id, target=batch_id,
                            payload={"edit_ids": child["added"]["edit_ids"]})
    return _batch_view(batch_id)


# ── B2: language sets ────────────────────────────────────────────────────────
#
# A master video and its language versions: each version is a variant of the
# master (the same clip, no plan copied) linked by `videos.master_id`, with
# its `language`. "Make language versions" makes the variants, then ONE batch
# turn (F4, source "language") whose child per version translates and voices
# every line in place, fitting each line's time. In step: a version is out of
# sync when the master's edit marker (app/store/languages.py, from F7's
# edit.shipped / edit.undone) is past the one it last synced to; "Sync this
# change" runs one turn on it for only the master's changed lines. Behind
# `projects.batch`.

VOICE_HANDLING = ("same", "designed")


def _language_code(record: ProjectRecord) -> str:
    """A video's language: a version's own, else the master's, guessed from its script."""
    if record.language:
        return record.language
    return langs.guess(" ".join(w.text for w in record.transcript.words))


def _out_of_sync(record: ProjectRecord) -> bool:
    if not record.master_id:
        return False
    master = repo.get(record.master_id)
    return master is not None and langs.marker(database, record.master_id) > int(record.synced_edit or 0)


def _language_fields(record: ProjectRecord) -> dict:
    """What a card and the editor header show: a version's language and
    whether it is in step; a master's versions as chips."""
    out: dict = {"master_id": record.master_id, "language": record.language,
                 "language_label": langs.label(record.language), "out_of_sync": _out_of_sync(record)}
    if record.master_id:
        master = repo.get(record.master_id)
        out["master_filename"] = master.source.filename if master else None
        out["languages"] = []
    else:
        out["master_filename"] = None
        out["languages"] = [{"video_id": c.source.project_id, "language": c.language, "label": langs.label(c.language),
                             "out_of_sync": _out_of_sync(c)} for c in repo.language_children(record.source.project_id)]
    return out


def _master_lines(master_id: str) -> list[dict]:
    """What the master says now, line by line in time order."""
    master = repo.get(master_id)
    if master is None:
        return []
    return [{"start": round(p.start, 2), "end": round(p.end, 2), "text": p.text}
            for p in sorted(_caption_passages(master_id, master), key=lambda p: p.start) if p.text.strip()]


def _language_view(record: ProjectRecord) -> dict | None:
    """The language block of a version's opening view (and its take check)."""
    if not record.master_id or not record.language:
        return None
    master = repo.get(record.master_id)
    return {"code": record.language, "label": langs.label(record.language),
            "master_id": record.master_id, "master_filename": master.source.filename if master else None,
            "master_lines": _master_lines(record.master_id)}


def _clock_span(start: float, end: float) -> str:
    return f"{start:.1f}–{end:.1f} s"


def _keep_words(project_id: str | None) -> list[str]:
    from app.agent.word_rules import brand_terms
    found = [{"kind": r.kind, "data": r.data} for r in rules.list_rules(database, project_id)] if project_id else []
    return brand_terms(found)


def _translate_goal(master: ProjectRecord, code: str, voice_handling: str, lines: list[dict], keep: list[str]) -> str:
    name = langs.LANGUAGES[code]
    how = ("Speak each line in the same speaker's own voice (their cloned voice when they have one, else the voice "
           f"the line is in now) with model v2, the multilingual model, so it is their voice speaking {name}."
           if voice_handling == "same" else
           f"Design one voice for {name} that suits the speaker (design_voice, then save_voice) and speak every line in it.")
    listed = "\n".join(f"- {_clock_span(ln['start'], ln['end'])}: “{ln['text']}”" for ln in lines) or "- (no spoken lines)"
    return (f"Make this the {name} version of {master.source.filename}: translate every line into {name} and voice "
            "each one in place of the line it replaces, fitting that line's time. When a line runs long, let the fit "
            f"ladder work first, then write it shorter in {name}. "
            + (f"Never translate: {', '.join(keep)}; say them exactly as written. " if keep else "")
            + how + f"\nThe lines, as the master says them now:\n{listed}")


def _sync_lines(master_id: str, since: int) -> list[dict]:
    """The master's lines that changed after marker `since`: each with what it says now."""
    master = repo.get(master_id)
    if master is None:
        return []
    edits = {e.edit_id: e for e in repo.list_edits(master_id)}
    out = []
    for change in langs.changes_since(database, master_id, since):
        edit = edits.get(change["edit_id"])
        if edit is None:
            continue
        sel = edit.plan.selection
        shot = " ".join(w.text for w in master.transcript.words if w.end > sel.start and w.start < sel.end)
        if change["verb"] == "edit.undone":
            now, what = shot, "back"
        elif edit.plan.mix == "remove":
            now, what = "", "removed"
        else:
            now, what = edit.plan.new_text, "changed"
        out.append({"edit_id": edit.edit_id, "start": round(sel.start, 2), "end": round(sel.end, 2),
                    "what": what, "text": now, "was": shot})
    return out


def _sync_goal(child: ProjectRecord, master: ProjectRecord, lines: list[dict], keep: list[str]) -> str:
    name = langs.label(child.language) or "this language"
    said = []
    for ln in lines:
        where = _clock_span(ln["start"], ln["end"])
        if ln["what"] == "removed":
            said.append(f"- {where}: the master took this line out; take it out here too.")
        elif ln["what"] == "back":
            said.append(f"- {where}: the master put this line back as shot: “{ln['text']}”. Say that in {name}.")
        else:
            said.append(f"- {where}: the master now says “{ln['text']}”. Say that in {name}.")
    return (f"Sync with the master, {master.source.filename}: it changed {len(lines)} "
            f"{'line' if len(lines) == 1 else 'lines'} since this version last synced. Change only these lines here, "
            f"in {name}, each fitting its time, and leave every other line as it is. "
            + (f"Never translate: {', '.join(keep)}. " if keep else "") + "\n" + "\n".join(said))


def _language_master(video_id: str, owner: str) -> ProjectRecord:
    _batch_flag(owner)
    record = _owned(video_id, owner)
    if record.master_id:
        raise HTTPException(status_code=409, detail="This is a language version. Make language versions from its master.")
    return record


def _language_gate(record: ProjectRecord, owner: str, codes: list[str]) -> dict:
    """The one gate's numbers for these languages, before anything is made:
    every line once per language, Voltage's measured thinking per turn and
    the voice price (None when nothing is measured), the cap = each version's
    turn cap added up."""
    lines = _master_lines(record.source.project_id)
    thinking = _thinking_usd(owner)
    per = None if thinking is None else thinking + sum(_voicing_usd(ln["text"]) for ln in lines)
    cap = round(float(_settings(record.source.project_id, owner)["turn_usd"]), 2)
    return {"videos": len(codes), "lines": len(lines) * len(codes),
            "est_usd": None if per is None else batch_mod._round_up_cent(per * len(codes)),
            "cap_usd": round(cap * len(codes), 2), "per_video_cap_usd": cap}


@app.get("/videos/{video_id}/languages")
def get_languages(video_id: str, owner: str = Depends(current_owner)) -> dict:
    """B2: a video's language set: the master's own language, its versions
    (each in step or not) and the languages it can still be made in."""
    _batch_flag(owner)
    record = _owned(video_id, owner)
    master = repo.get(record.master_id) if record.master_id else record
    if master is None:
        raise HTTPException(status_code=404, detail="The master video was deleted.")
    original = _language_code(master)
    children = repo.language_children(master.source.project_id)
    made = {c.language for c in children}
    return {"master_id": master.source.project_id, "master_filename": master.source.filename,
            "original": original, "original_label": langs.label(original),
            "in_project": bool(master.folder_id),
            "children": [{"video_id": c.source.project_id, "language": c.language, "label": langs.label(c.language),
                          "out_of_sync": _out_of_sync(c), "synced_edit": c.synced_edit} for c in children],
            "options": [{"code": code, "label": label, "made": code in made}
                        for code, label in langs.LANGUAGES.items() if code != original],
            "lines": len(_master_lines(master.source.project_id))}


class LanguagesRequest(BaseModel):
    languages: list[str]
    voice: Literal["same", "designed"] = "same"
    # True: only the gate's numbers, nothing made or spent.
    dry_run: bool = False


@app.post("/videos/{video_id}/languages", status_code=201)
def make_languages(video_id: str, req: LanguagesRequest, owner: str = Depends(current_owner)) -> dict:
    """B2: Make language versions. One variant per language linked to this
    master, then one batch turn over them (F4) that translates and voices
    every line, fitting each line's time. `dry_run` gives the numbers first;
    the press after them is the batch's gate."""
    record = _language_master(video_id, owner)
    if not record.folder_id:
        raise HTTPException(status_code=409, detail="Language versions are made inside a project. Move this video into a project first.")
    project = _owned_project(record.folder_id, owner)
    codes = list(dict.fromkeys(c.strip().lower() for c in req.languages if c.strip()))
    if not codes:
        raise HTTPException(status_code=422, detail="Pick at least one language.")
    original = _language_code(record)
    bad = [c for c in codes if c not in langs.LANGUAGES or c == original]
    if bad:
        raise HTTPException(status_code=422, detail=f"{bad[0]} is not a language this video can be made in.")
    made = {c.language for c in repo.language_children(video_id)}
    again = [langs.LANGUAGES[c] for c in codes if c in made]
    if again:
        raise HTTPException(status_code=409, detail=f"The {again[0]} version is made already. Open it from the project.")
    gate = _language_gate(record, owner, codes)
    refusal = _batch_start_refusal(project, owner, gate["cap_usd"])
    if refusal:
        raise HTTPException(status_code=409, detail=refusal)
    if req.dry_run:
        return {"gate": gate, "batch_id": None, "children": []}
    if record.consent is None:
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to translate a video (set AVE_AGENT=1 and an Anthropic key).")
    at = langs.marker(database, video_id)
    lines = _master_lines(video_id)
    keep = _keep_words(record.folder_id)
    thinking = _thinking_usd(owner)
    children, made_ids = [], []
    for code in codes:
        child_id = _make_variant(video_id, record, owner, copy_plan=False)
        repo.link_language(child_id, video_id, code, at)
        repo.set_settings(child_id, language=code, language_voice=req.voice)
        made_ids.append(child_id)
        children.append(_batch_child(child_id, _translate_goal(record, code, req.voice, lines, keep), owner,
                                     thinking=thinking, lines=[ln["text"] for ln in lines], extra={"language": code}))
    with database.tx() as c:
        activity_log.record(c, "language.versions_made", user_actor(owner), video_id=video_id, target=video_id,
                            payload={"languages": codes, "voice": req.voice, "videos": made_ids})
    opened = _open_batch(project, owner, "language", f"Make {', '.join(langs.LANGUAGES[c] for c in codes)} versions of "
                         f"{record.source.filename}", children, extra={"master_id": video_id, "voice": req.voice})
    started = _go_batch(opened, owner)
    return {"gate": gate, "batch_id": started["batch_id"],
            "children": [{"video_id": v, "language": c, "label": langs.LANGUAGES[c]} for v, c in zip(made_ids, codes)]}


def _sync_settles(child_id: str, turn_job_id: str, to: int, owner: str) -> None:
    """The sync turn ended: in step at the marker it synced to, unless it failed."""
    turn_job = _await_turn(turn_job_id)
    out = (turn_job.result or {}) if turn_job is not None else {}
    if turn_job is None or turn_job.status != "succeeded" or out.get("stopped") == "error" or out.get("ceiling"):
        return
    now = repo.get(child_id)
    if now is None:
        return
    repo.set_synced_edit(child_id, max(int(now.synced_edit or 0), to))
    with database.tx() as c:
        activity_log.record(c, "language.synced", user_actor(owner), video_id=child_id, target=child_id,
                            payload={"master_id": now.master_id, "synced_edit": to})


class ConfirmStage(BaseModel):
    # Decision 0: the yes to taking an Approved video back to Draft.
    confirm_stage: bool = False


@app.post("/videos/{video_id}/sync", status_code=202)
def sync_language(video_id: str, req: ConfirmStage | None = None, owner: str = Depends(current_owner)) -> dict:
    """B2: Sync this change. One turn on the language version for only the
    master's lines changed since it last synced (the press is the yes for
    its paid steps); in step again once that turn finishes."""
    _batch_flag(owner)
    record = _owned(video_id, owner)
    if not record.master_id:
        raise HTTPException(status_code=409, detail="This video is not a language version.")
    _stage_gate([video_id], owner, bool(req and req.confirm_stage), change=True)
    master = repo.get(record.master_id)
    if master is None:
        raise HTTPException(status_code=409, detail="The master video was deleted, so there is nothing to sync with.")
    to = langs.marker(database, record.master_id)
    lines = _sync_lines(record.master_id, int(record.synced_edit or 0))
    if to <= int(record.synced_edit or 0) or not lines:
        if to > int(record.synced_edit or 0):
            repo.set_synced_edit(video_id, to)       # changes that cancel out: in step already
        raise HTTPException(status_code=409, detail="This version is in step with its master.")
    if not _agent_on():
        raise HTTPException(status_code=409, detail="Voltage needs Claude to change a video (set AVE_AGENT=1 and an Anthropic key).")
    goal = _sync_goal(record, master, lines, _keep_words(record.folder_id))
    started = _start_turn(video_id, record, goal, owner, approve=True)
    with database.tx() as c:
        activity_log.record(c, "language.sync_started", user_actor(owner), video_id=video_id, target=video_id,
                            payload={"master_id": record.master_id, "lines": [ln["edit_id"] for ln in lines], "to": to})
    threading.Thread(target=_sync_settles, args=(video_id, started["job_id"], to, owner), daemon=True,
                     name=f"language-sync-{video_id}").start()
    return {"job_id": started["job_id"], "lines": lines, "to": to}


@app.delete("/projects/{project_id}", status_code=204)
def delete_folder(project_id: str, videos: Literal["delete", "keep"], owner: str = Depends(current_owner)) -> Response:
    """Delete a project (F8): it goes to the Bin with its videos (`delete`),
    or its videos become standalone (`keep`). The purge removes it after 30
    days, with its files and any voice shared only here at the vendor."""
    _owned_project(project_id, owner)
    repo.soft_delete_project(project_id, owner, keep_videos=videos == "keep")
    return Response(status_code=204)


# ── D3: the Bin ──────────────────────────────────────────────────────────────
# What was deleted (F8) waits here 30 days: who deleted it, when, the days it
# has left, and Restore. The purge (app.purge) takes what is due.

def _reuse_flag(owner: str) -> None:
    if not flags.enabled("projects.reuse", owner):
        raise HTTPException(status_code=404, detail="Not found")


@app.get("/bin")
def list_bin(owner: str = Depends(current_owner)) -> dict:
    """Everything of the caller's in the Bin, most recently deleted first."""
    _reuse_flag(owner)
    found = bin_store.items(database, owner)
    for item in found:
        item["deleted_by_you"] = item["deleted_by"] == owner
    return {"items": found, "days": bin_store.BIN_DAYS}


@app.post("/bin/{kind}/{item_id}/restore")
def restore_from_bin(kind: Literal["video", "project", "voice"], item_id: str, owner: str = Depends(current_owner)) -> dict:
    """Put one item back. A video goes back to its project, or is standalone
    when that project is in the Bin or gone; a project brings back the videos
    deleted with it; a voice is pickable again."""
    _reuse_flag(owner)
    try:
        if kind == "video":
            done = bin_store.restore_video(database, owner, item_id, owner)
        elif kind == "project":
            done = bin_store.restore_project(database, owner, item_id, owner)
        else:
            done = bin_store.restore_voice(database, owner, item_id, owner)
    except bin_store.NotInBin:
        raise HTTPException(status_code=404, detail="That is not in the Bin any more.") from None
    return {"kind": kind, "id": item_id, **done}


# ── D1: project templates ────────────────────────────────────────────────────
#
# Save as template keeps what a project shares (the brief's current text,
# its words and rules, export presets, defaults for new videos, ceiling) as
# a template; New project starts from one. Voices are referenced, never
# copied at the vendor: a voice already in the owner's voices is kept by
# reference (a project made later shares it while it is still theirs); a
# voice that belongs to the project asks the move's question first: copy it
# into the template, or keep it in my voices. Three starters (Festive ad,
# Product explainer, Interview cleanup) are read-only. Behind
# `projects.reuse` (404 when off).

class TemplateSave(BaseModel):
    name: str
    # The project's own voices: copy into the template, or keep in my voices.
    voice: Literal["copy", "keep"] | None = None


class TemplateRename(BaseModel):
    name: str


def _template_or_404(template_id: str, owner: str) -> templates_store.Template:
    found = templates_store.get(database, owner, template_id)
    if found is None:
        raise HTTPException(status_code=404, detail="That template is gone.")
    return found


@app.get("/templates")
def list_templates(owner: str = Depends(current_owner)) -> dict:
    """The starters, then the caller's own templates, newest first."""
    _reuse_flag(owner)
    return {"templates": [t.to_dict() for t in templates_store.list_for(database, owner)]}


@app.post("/projects/{project_id}/template", status_code=201)
def save_template(project_id: str, req: TemplateSave, owner: str = Depends(current_owner)):
    """Save the project as a template. A voice that belongs to the project
    (not in the owner's voices) needs `voice`: without it the answer is 409
    naming the voices, as when a video moves out."""
    _reuse_flag(owner)
    project = _owned_project(project_id, owner)
    try:
        name = templates_store.clean_name(req.name)
    except templates_store.TemplateError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    shared = _project_voices(project_id)
    mine = {v["voice_id"] for v in _my_voices(owner)}
    own = [v for v in shared if v["voice_id"] not in mine]
    if own and req.voice is None:
        names = ", ".join(v["name"] for v in own)
        return JSONResponse(status_code=409, content={
            "detail": f"{names} {'belongs' if len(own) == 1 else 'belong'} to {project.name}. "
                      "Copy the voice into the template, or keep it in your voices.",
            "voices": [{"voice_id": v["voice_id"], "name": v["name"]} for v in own]})
    if own and req.voice == "keep":
        _keep_in_my_voices(owner, own, project_id)
        mine |= {v["voice_id"] for v in own}
    with database.tx() as c:
        data = templates_store.snapshot_in(c, project_id, owner)
    data["voices"] = [{**{k: v for k, v in entry.items() if k not in ("used_in",)},
                       "ref": "mine" if entry["voice_id"] in mine else "copy"} for entry in shared]
    return templates_store.save(database, owner, name, data, source_project_id=project_id).to_dict()


@app.patch("/templates/{template_id}")
def rename_template(template_id: str, req: TemplateRename, owner: str = Depends(current_owner)) -> dict:
    _reuse_flag(owner)
    _template_or_404(template_id, owner)
    try:
        return templates_store.rename(database, owner, template_id, req.name).to_dict()  # type: ignore[union-attr]
    except templates_store.TemplateError as exc:
        raise HTTPException(status_code=403 if templates_store.starter(template_id) else 422, detail=str(exc))


@app.delete("/templates/{template_id}", status_code=204)
def delete_template(template_id: str, owner: str = Depends(current_owner)) -> Response:
    """Delete one of the caller's templates; projects made from it keep everything."""
    _reuse_flag(owner)
    _template_or_404(template_id, owner)
    try:
        templates_store.remove(database, owner, template_id)
    except templates_store.TemplateError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    return Response(status_code=204)


def _folder_from_template(req: ProjectCreate, owner: str) -> dict:
    """A new project from a template: its brief (version 1), words and rules,
    presets, defaults and ceiling, and its voices shared in (a referenced
    voice only while it is still in the owner's voices). No videos."""
    _reuse_flag(owner)
    template = _template_or_404(req.template_id or "", owner)
    data = template.data
    settings_ = data.get("settings") if isinstance(data.get("settings"), dict) else {}
    ceiling = data.get("ceiling_usd")
    project = repo.create_project(owner, _project_name_or_422(req.name), (req.brief.strip() or data.get("brief") or "").strip(),
                                  settings=settings_, ceiling_usd=float(ceiling) if isinstance(ceiling, (int, float)) and ceiling > 0 else None)
    mine = {v["voice_id"] for v in _my_voices(owner)}
    voices_ = [{k: v for k, v in entry.items() if k != "ref"} | {"at": _now()}
               for entry in data.get("voices") or [] if entry.get("voice_id") and (entry.get("ref") != "mine" or entry["voice_id"] in mine)]
    if voices_:
        _set_project_voices(project.project_id, voices_)
        for entry in voices_:
            getattr(voice, "register_clone", lambda vid: None)(entry["voice_id"])
    with database.tx() as c:
        templates_store.apply_in(c, project.project_id, data, owner)
        activity_log.record(c, "project.from_template", user_actor(owner), project_id=project.project_id,
                            target=template.template_id, payload={"template": template.name, "starter": template.starter,
                                                                  **templates_store.summary(data)})
    return _folder_dict(repo.get_project(project.project_id))


# ── D2: learned style ────────────────────────────────────────────────────────
#
# Every decision the user makes on a line Voltage proposed is logged
# (app/store/learned.py): added, rejected (discarded, with a reason when
# given), or edited before adding (the words first voiced against the words
# added). After every 10th decision in a project, one cheap Claude pass
# (app/adapters/claude_style.py, the project check's model, metered to the
# project as "Learned style") may suggest ONE line for the brief or a style
# rule. It changes nothing until accepted; "What Voltage has learned" lists
# what was, each removable. No Claude key, or the project at its ceiling:
# the pass is skipped silently. The pass needs `projects.reuse`. Each pass
# is an Activity job (kind "learn", keyed by the project's id).

# Tests swap in a fake reader here; None means the real one when a key is set.
_learn_reader = None
_learn_reader_built: tuple | None = None
# Tests run the pass inline; the server runs it on the work pool after the response.
LEARN_IN_BACKGROUND = True


def _learn_reader_for():
    global _learn_reader_built
    if _learn_reader is not None:
        return _learn_reader
    if not settings.anthropic_api_key:
        return None
    key = (settings.anthropic_api_key, settings.anthropic_workspace_id, settings.check_model)
    if _learn_reader_built is None or _learn_reader_built[0] != key:
        from app.adapters.claude_style import ClaudeStyleReader
        _learn_reader_built = (key, ClaudeStyleReader(settings.anthropic_api_key, settings.anthropic_workspace_id, model=settings.check_model))
    return _learn_reader_built[1]


def _first_shown_text(item: PlanItem) -> str:
    """The words the item's first ready take said: what Voltage proposed
    before any rewording. An item from before D2 has no record: its words now."""
    for h in item.history:
        if h.get("outcome") == "ready" and h.get("text") is not None:
            return str(h["text"])
    return item.new_text


def _log_decision(video_id: str, plan_id: str, item: PlanItem, decision: str, *, final: str | None = None,
                  reason: str | None = None) -> int | None:
    """Log one decision on a proposal and start the pattern pass when it is
    the project's 10th, 20th... Never fails the action it describes."""
    try:
        record = repo.get(video_id)
        if record is None:
            return None
        proposed = _first_shown_text(item)
        with database.tx() as c:
            decision_id, n = learned_store.record_in(
                c, video_id=video_id, decision=decision, proposed_text=proposed, final_text=final,
                plan_id=plan_id, item_id=item.item_id, reason=reason, by=record.owner)
        if record.folder_id and learned_store.due(n) and flags.enabled("projects.reuse", record.owner):
            _start_learn_pass(record.folder_id, record.owner, n)
        return decision_id
    except Exception:  # noqa: BLE001 - the log is a by-product; the add or discard stands
        log.exception("could not log a decision on %s/%s", video_id, item.item_id)
        return None


def _decided_add(video_id: str, plan_id: str, item: PlanItem) -> None:
    """An add by the user: "edited" when the words differ from the first take's."""
    if current_turn.get() or item.reason == "Removed by hand":
        return
    proposed = _first_shown_text(item)
    if " ".join(proposed.split()) != " ".join(item.new_text.split()):
        _log_decision(video_id, plan_id, item, "edited", final=item.new_text)
    else:
        _log_decision(video_id, plan_id, item, "added", final=item.new_text)


def _start_learn_pass(project_id: str, owner: str, at_count: int) -> str | None:
    """Working rule 2: the pass is an Activity job (kind "learn", keyed by
    the project's id like the project check). Nothing is created when the
    pass would be skipped (no key, archived, over a ceiling): the user never
    sees a job that did not run. Returns the job id."""
    ready = _learn_ready(project_id)
    if ready is None:
        return None
    job = activity.create(project_id, "learn", step_label="Queued",
                          detail={"project_id": project_id, "at_count": at_count})

    def run() -> None:
        _learn_pass(project_id, owner, at_count, job.job_id)
    if LEARN_IN_BACKGROUND:
        work_pool.submit(run)
    else:
        run()
    return job.job_id


def _learn_ready(project_id: str):
    """(reader, project, request text) when the pass can run now, else None:
    skipped silently without a key, on an archived project, or when the call
    would cross the project or monthly ceiling."""
    reader = _learn_reader_for()
    project = repo.get_project(project_id)
    if reader is None or project is None or project.archived_at:
        return None
    rule_lines = [f"{r.kind}: {' / '.join(str(v) for v in r.data.values())}" for r in rules.list_rules(database, project_id)]
    text = learned_store.request_text({"name": project.name, "brief": project.brief},
                                      learned_store.decisions(database, project_id, 30), rule_lines)
    from app.adapters.claude_style import STYLE_MAX_TOKENS
    estimate = claude_usd(settings.check_model, len(text) // 3 + 400, STYLE_MAX_TOKENS)
    if _check_spend_refusal(project, estimate):
        return None
    return reader, project, text


def _learn_pass(project_id: str, owner: str, at_count: int, job_id: str) -> dict | None:
    """One pass inside its job: the brief, rules and the last 30 decisions to
    Claude; at most one suggestion back, stored as waiting. The job ends
    saying whether there was one; a failure fails the job, never the add or
    discard that started it."""
    activity.start(job_id, "Reading your decisions")
    spent: list[float] = []
    try:
        ready = _learn_ready(project_id)
        if ready is None:              # archived or the ceiling reached while it waited
            activity.finish(job_id, step_label="Skipped", detail={"suggested": False, "skipped": True})
            return None
        reader, _, text = ready
        out = reader.suggest(text, meter=_project_meter(project_id, "Learned style", spent))
        cost = round(sum(spent), 6) or None
        found = None
        if out and out.get("kind") in learned_store.KINDS:
            found = learned_store.suggest(database, project_id, out["kind"], plain(out.get("text") or ""),
                                          plain(out.get("why") or ""), at_count)
        activity.finish(job_id, step_label="Suggested one line" if found else "No pattern yet", cost_usd=cost,
                        detail={"suggested": bool(found)})
        return found
    except Exception as exc:  # noqa: BLE001 - a pass that fails suggests nothing and says why
        log.exception("learned-style pass for %s", project_id)
        activity.fail(job_id, "learn_failed", f"Looking for a pattern stopped: {str(exc)[:200] or type(exc).__name__}",
                      cost_usd=round(sum(spent), 6) or None)
        return None


def _learned_page(project_id: str) -> dict:
    return {"pending": learned_store.pending(database, project_id), "learned": learned_store.learned(database, project_id),
            "decisions": learned_store.count(database, project_id), "every": learned_store.EVERY,
            "reasons": list(learned_store.REASONS)}


@app.get("/projects/{project_id}/learned")
def get_learned(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """The waiting suggestion, what Voltage has learned, and how many decisions so far."""
    _reuse_flag(owner)
    _owned_project(project_id, owner)
    return _learned_page(project_id)


def _learned_change(project_id: str, item_id: int, owner: str, change) -> dict:
    _reuse_flag(owner)
    _owned_project(project_id, owner)
    try:
        change(database, project_id, item_id, owner)
    except learned_store.LearnedError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {**_learned_page(project_id), "project": _folder_dict(repo.get_project(project_id))}


@app.post("/projects/{project_id}/learned/{item_id}/accept")
def accept_learned(project_id: str, item_id: int, owner: str = Depends(current_owner)) -> dict:
    """Apply the suggestion: a new brief version with the line, or a style rule."""
    out = _learned_change(project_id, item_id, owner, learned_store.accept)
    _auto_check(project_id, owner)   # A2: the free checks again after a brief or rule change
    return out


@app.post("/projects/{project_id}/learned/{item_id}/dismiss")
def dismiss_learned(project_id: str, item_id: int, owner: str = Depends(current_owner)) -> dict:
    return _learned_change(project_id, item_id, owner, learned_store.dismiss)


@app.delete("/projects/{project_id}/learned/{item_id}")
def remove_learned(project_id: str, item_id: int, owner: str = Depends(current_owner)) -> dict:
    """Take a learned item back out of the brief or the rules."""
    return _learned_change(project_id, item_id, owner, learned_store.remove)


class DecisionReason(BaseModel):
    reason: str


@app.post("/videos/{video_id}/decisions/{decision_id}/reason")
def give_decision_reason(video_id: str, decision_id: int, req: DecisionReason, owner: str = Depends(current_owner)) -> dict:
    """Why a proposal was thrown out, said after Discard."""
    _owned(video_id, owner)
    try:
        found = learned_store.reason(database, decision_id, video_id, req.reason)
    except learned_store.LearnedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if found is None:
        raise HTTPException(status_code=404, detail="That decision is not on this video.")
    return found


# ── D4: pins, archive, search ────────────────────────────────────────────────

def _last_edited(video_id: str, created_at: str) -> str:
    """When the video last changed: its newest event or chat message, else its upload."""
    with database.tx() as c:
        row = c.execute("SELECT MAX(at) FROM (SELECT MAX(at) AS at FROM project_events WHERE video_id = ? "
                        "UNION ALL SELECT MAX(at) FROM messages WHERE project_id = ?)", (video_id, video_id)).fetchone()
    return max(created_at or "", row[0] or "")


def _not_archived(project_id: str, owner: str) -> None:
    """423 with the sentence when the project is archived (D4, flag on)."""
    if flags.enabled("projects.reuse", owner) and home_store.archived_project_of(database, project_id=project_id):
        raise HTTPException(status_code=423, detail=home_store.ARCHIVED)


# Writes that stay open on an archived project: archiving itself, saving it
# as a template (D1: it only reads the project), deleting (to the Bin), and a
# render or single export of what is already there.
_ARCHIVE_SELF = re.compile(r"^/projects/[^/]+/(archive|template)$")
_BARE_ITEM = re.compile(r"^/(videos|projects)/[^/]+$")
_RENDER_ONLY = re.compile(r"^/videos/[^/]+/(renders|export)$")
_ARCHIVE_TARGET = re.compile(r"^/(videos|projects)/([A-Za-z0-9_-]+)(/|$)")


def _open_when_archived(method: str, path: str) -> bool:
    return bool(_ARCHIVE_SELF.match(path) or (method == "DELETE" and _BARE_ITEM.match(path))
                or (method == "POST" and _RENDER_ONLY.match(path)))


@app.middleware("http")
async def _archived_is_read_only(request: Request, call_next):
    """D4: an archived project, and every video in it, is read-only until
    unarchived: any change under /projects/<id> or /videos/<id> (a turn, an
    edit, a brief, a move, a batch) answers 423 with one sentence. Reads,
    and the writes `_open_when_archived` names, go through."""
    method, path = request.method, request.url.path
    hit = _ARCHIVE_TARGET.match(path) if method in ("POST", "PUT", "PATCH", "DELETE") else None
    if hit and not _open_when_archived(method, path):
        kind, item = hit.group(1), hit.group(2)
        found = await asyncio.to_thread(home_store.archived_project_of, database,
                                        **({"video_id": item} if kind == "videos" else {"project_id": item}))
        if found and flags.enabled("projects.reuse", found["owner"]):
            try:
                caller = current_owner(request)
            except HTTPException:
                caller = None
            if caller == found["owner"]:
                return JSONResponse(status_code=423, content={"detail": home_store.ARCHIVED})
    return await call_next(request)


@app.post("/projects/{project_id}/archive")
def archive_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Archive a project: hidden from Home, still searchable, read-only."""
    _reuse_flag(owner)
    _owned_project(project_id, owner)
    changed = home_store.set_archived(database, project_id, owner, True)
    return {**_folder_dict(repo.get_project(project_id)), "changed": changed}


@app.delete("/projects/{project_id}/archive")
def unarchive_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    _reuse_flag(owner)
    _owned_project(project_id, owner)
    changed = home_store.set_archived(database, project_id, owner, False)
    return {**_folder_dict(repo.get_project(project_id)), "changed": changed}


@app.get("/pins")
def list_pins(owner: str = Depends(current_owner)) -> dict:
    """What the caller pinned to the top of Home's sidebar, oldest first."""
    _reuse_flag(owner)
    return {"pins": home_store.pins(database, owner)}


@app.put("/pins/{kind}/{item_id}")
def add_pin(kind: Literal["project", "video"], item_id: str, owner: str = Depends(current_owner)) -> dict:
    _reuse_flag(owner)
    try:
        added = home_store.pin(database, owner, kind, item_id)
    except home_store.NotFound:
        raise HTTPException(status_code=404, detail="Nothing of yours to pin there.") from None
    return {"pinned": True, "changed": added}


@app.delete("/pins/{kind}/{item_id}")
def remove_pin(kind: Literal["project", "video"], item_id: str, owner: str = Depends(current_owner)) -> dict:
    _reuse_flag(owner)
    try:
        return {"pinned": False, "changed": home_store.unpin(database, owner, kind, item_id)}
    except home_store.NotFound:
        raise HTTPException(status_code=404, detail="Nothing of yours to unpin there.") from None


@app.get("/search")
def search_home(q: str = "", owner: str = Depends(current_owner)) -> dict:
    """Project names, video names, what is said (with the time) and briefs,
    grouped by project; archived projects included, deleted ones never."""
    _reuse_flag(owner)
    return home_store.search(database, owner, q)


@app.get("/projects/{project_id}/events")
def list_project_events(project_id: str, limit: int = 50, before: int | None = None,
                        owner: str = Depends(current_owner)) -> dict:
    """F7: what happened in the project and its videos, newest first; pass
    `next` back as `before` for the page after."""
    _owned_project(project_id, owner)
    page = activity_log.for_project(database, project_id, limit, before)
    # C1: the feed says "You" for the caller's own events.
    for e in page["events"]:
        e["you"] = e["actor_kind"] == "user" and e["actor_name"] == owner
    return page


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
    try:
        sniff.document(data[:sniff.HEAD_BYTES], name)
    except sniff.SniffError as exc:
        raise HTTPException(status_code=415, detail=str(exc)) from None
    return await run_in_threadpool(_keep_folder_file, project_id, name, data)


def _keep_folder_file(project_id: str, name: str, data: bytes) -> dict:
    """The write and the text extraction (a PDF is slow), off the event loop (rehearsal item 3)."""
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
def get_folder_file(project_id: str, sha256: str, owner: str = Depends(media_owner)) -> FileResponse:
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
    _auto_check(project_id, owner)   # A2: a new brief version, so the free checks run again
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


def _keep_in_my_voices(owner: str, going: list[dict], from_project: str) -> None:
    """A project's voices kept in the owner's own voices, for any project
    (a name already taken gets the project's name after it). Shared by a
    video's move out and Save as template (D1)."""
    mine = _my_voices(owner)
    have = {m["voice_id"] for m in mine}
    taken = {m["name"].lower() for m in mine}
    for v in going:
        if v["voice_id"] in have:
            continue
        name = v["name"] if v["name"].lower() not in taken else f"{v['name']} ({repo.get_project(from_project).name})"
        mine.append({"voice_id": v["voice_id"], "name": name, "seconds": 0.0, "at": _now(), "kind": v.get("kind") or "designed",
                     "consent_granted_at": v.get("consent_granted_at"), "consent_approximate": bool(v.get("consent_approximate")),
                     "sample_sha": v.get("sample_sha"), "description": v.get("description"),
                     "source": {"project_id": from_project}})
        taken.add(name.lower())
    _set_my_voices(owner, mine)


@app.patch("/videos/{project_id}")
def move_video(project_id: str, req: MoveVideoRequest, owner: str = Depends(current_owner)):
    """Move a video into a project, or out (`project_id` null). Its turns,
    takes and edits stay with it. Leaving a project whose voices its kept
    edits or ready proposals use needs `voice`: copy or keep; without it the
    answer is 409 naming the voices."""
    record = _owned(project_id, owner)
    target = _owned_project(req.project_id, owner) if req.project_id else None
    if target is not None:
        _not_archived(target.project_id, owner)
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
            _keep_in_my_voices(owner, going, leaving)
    repo.set_folder(project_id, target_id, actor=user_actor(owner))
    return _project_dict(repo.get(project_id))


@app.post("/videos/{project_id}/variants")
@app.post("/projects/{project_id}/variants", deprecated=True)
def create_variant(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """A variant (UX-3): the same clip as a new project, with the latest
    plan copied as a draft — every line planned again, nothing voiced — so
    another offer or another wording starts from the plan, not an upload."""
    record = _owned(project_id, owner)
    return _project_dict(repo.get(_make_variant(project_id, record, owner)))


def _make_variant(project_id: str, record: ProjectRecord, owner: str, copy_plan: bool = True) -> str:
    """The variant itself (create_variant; B2's language versions with
    `copy_plan=False`: a translation starts from the lines, not the plan)."""
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
    plan = repo.latest_plan(project_id) if copy_plan else None
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
    return new_id


class ConsentRequest(BaseModel):
    liveness_id: str | None = None      # G6: the passed read-aloud attempt


@app.post("/videos/{project_id}/consent")
@app.post("/projects/{project_id}/consent", deprecated=True)
def grant_consent(project_id: str, req: ConsentRequest | None = None, owner: str = Depends(current_owner)) -> dict:
    """Confirm rights for a project uploaded without them.

    Lets a refused generation be recovered without re-uploading. G6: with
    `golive.g6` on, the speaker first reads a sentence aloud (liveness); the
    consent names that passed attempt.
    """
    _owned(project_id, owner)
    if flags.enabled("golive.g6", owner):
        from app.safety_api import passed_attempt
        if not passed_attempt(project_id, req.liveness_id if req else None):
            raise HTTPException(status_code=422, detail="Read the sentence aloud first, so we know the speaker is here and agrees.")
    recorded = repo.grant_consent(project_id, Consent(granted_at=_now()))
    return {"video_id": project_id, "consent_granted_at": recorded.granted_at if recorded else None}


@app.get("/videos/{project_id}/artifacts/{sha256}")
@app.get("/projects/{project_id}/artifacts/{sha256}", deprecated=True)
def get_artifact(project_id: str, sha256: str, owner: str = Depends(media_owner)) -> FileResponse:
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
    if speaker and flags.enabled("golive.g6", record.owner):
        name = next((s["name"] for s in _speakers(project_id) if s["label"] == speaker and s["name"]), None)
        figure = public_figures.match(name or "") if name else None
        if figure and not any(s["label"] == speaker and s["voice_id"] for s in _speakers(project_id)):
            analytics.track("clone.public_figure_refused", record.owner, {"video_id": project_id})
            return VoiceChoice(requested, (f"Stock voice: {figures_mod.REFUSAL}",))
    if not flags.enabled("voices.cloning", record.owner):
        picked = next((s["voice_id"] for s in _speakers(project_id) if s["label"] == speaker and s["voice_id"]), None)
        if picked:
            return VoiceChoice(picked)
        return VoiceChoice(requested, ("Stock voice: voice cloning is not open yet.",))
    return clones.resolve(project_id, record.source, record.transcript, speaker, requested)


def _refuse_public_figure(owner: str, name: str | None) -> None:
    """G6: a voice named after a known public figure is not cloned or kept."""
    if name and flags.enabled("golive.g6", owner) and public_figures.match(name):
        analytics.track("clone.public_figure_refused", owner, {})
        raise HTTPException(status_code=422, detail=figures_mod.REFUSAL)


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
    # A3: the project's respellings go to the vendor; the plan keeps the words as written.
    # 9b: a language version's transcript is the master's English; it goes to the vendor as context only when set.
    master_context = not (record.master_id and record.language) or settings.lang_master_context
    with pronounce.respelling(_respellings(project_id)), vendor_context(master_context):
        candidate = generate(plan)
    # Retained so approval commits this exact candidate rather than re-running
    # generation, which real vendors would not reproduce byte-for-byte.
    repo.save_candidate(project_id, candidate)
    _take_voiced(record, candidate)
    return candidate


def _take_voiced(record: ProjectRecord, candidate: EditCandidate) -> None:
    """G7: one take voiced, with its vendor; SIM-o and UTMOS go along only when
    they were measured from the media (never the mock engine's stand-ins)."""
    report = candidate.continuity
    props: dict = {"video_id": record.source.project_id, "vendor": voice_label, "candidate_id": candidate.candidate_id}
    if report.voice_match is not None and "voice_match" in (report.measured or ()):
        props["sim_o"] = round(float(report.voice_match), 4)
    if report.naturalness is not None and "naturalness" in (report.measured or ()):
        props["utmos"] = round(float(report.naturalness), 3)
    analytics.track("take_voiced", record.owner, props)


def _project_rules(video_id: str) -> list[dict]:
    """The rules of the project a video is in ([] when standalone), as the turn reads them."""
    record = repo.get(video_id)
    if record is None or not record.folder_id:
        return []
    return [{"kind": r.kind, "data": r.data} for r in rules.list_rules(database, record.folder_id)]


def _respellings(video_id: str) -> tuple[tuple[str, str], ...]:
    """A3: (term, respelling) pairs for the text sent to the voice vendor."""
    return pronounce.pairs_from(_project_rules(video_id))


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
    with pronounce.respelling(_respellings(project_id)):
        held = holds is not None and holds(record.source, plan, record.transcript)
    if not held:
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
    _stage_gate([project_id], owner, req.confirm_stage)
    plan = repo.latest_plan(project_id)
    proposed = next((i for i in plan.items if i.candidate_id == candidate.candidate_id), None) if plan else None
    edit_id = _approve_candidate(project_id, candidate, overridden)
    if proposed is not None and proposed.status != "approved":
        _decided_add(project_id, plan.plan_id, proposed)   # D2
    return {
        "edit_id": edit_id,
        "candidate_id": candidate.candidate_id,
        "overridden": overridden,
        "continuity": _continuity_dict(candidate.continuity),
        "speaker": _speakers_by_take(project_id).get(candidate.candidate_id),
        "voice_profile_id": _voice_of(candidate.plan),
    }


def _actor_now(project_id: str) -> Actor:
    """Who is acting on a video right now, for the activity log (F7): Voltage
    inside a turn, else the video's owner."""
    if current_turn.get():
        return VOLTAGE
    record = repo.get(project_id)
    return user_actor(record.owner if record else LOCAL_OWNER)


def _brief_shipped_with(project_id: str) -> int | None:
    """A1: the brief version an edit shipping now was made with: the one the
    running turn read, or the project's current version for a hand Add it.
    None for a standalone video, or a project with no brief yet."""
    record = repo.get(project_id)
    project = repo.get_project(record.folder_id) if record and record.folder_id else None
    if project is None or project.brief_version is None:
        return None
    turn_id = current_turn.get()
    last = repo.settings(project_id).get("last_turn") or {}
    read = last.get("brief_version") if turn_id and last.get("id") == turn_id else None
    return int(read) if isinstance(read, int) else project.brief_version


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
    ), actor=_actor_now(project_id), made_with_brief=_brief_shipped_with(project_id))
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
    actor = VOLTAGE if by == "Voltage" else _actor_now(project_id)
    if edit is None or not repo.revert_edit(project_id, edit_id, actor=actor):
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
    if req and req.purpose == "export" and not req.with_proposals:
        out = _provenance_export(repo.get(project_id), out)        # G6: the mark and the manifest
        _exported(owner, project_id, float(out.get("render", {}).get("duration") or 0.0))
    return {**out, "request_id": req.request_id if req else None}


def _exported(owner: str, video_id: str, seconds: float, preset: str | None = None) -> None:
    """G7: a video exported (its minutes feed cost per exported minute) and, once, the funnel's first export."""
    analytics.track("video_exported", owner, {"video_id": video_id, "seconds": round(seconds, 2), "preset": preset})
    analytics.track("first_export", owner, {"video_id": video_id})


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
            if settings.mock_vendors:                  # the rehearsal: a render takes as long as a real one
                from app.adapters.mock_claude import wait
                wait("AVE_MOCK_RENDER_SECONDS", "5-20")
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
        if not proposals:
            _tell_reviewers(project_id, version)              # C2: "a new version is ready" to reviewers who gave an email
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
    # C1: yes to "This video is Approved. Adding this moves it back to Draft."
    confirm_stage: bool = False


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
        "word_rule": item.word_rule,
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
    _stage_gate([project_id], owner, req.confirm_stage)
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
        # A3: a take that breaks a word rule is never Voltage's pick; the user may still add it by hand.
        if current_turn.get() and (item.word_rule or {}).get("breaks"):
            skipped.append({"item_id": item.item_id, "reason": "breaks a word rule: " + " ".join(item.word_rule["breaks"])})
            continue
        edit_id = _approve_candidate(project_id, candidate, overridden)
        _decided_add(project_id, plan_id, item)   # D2: the user's add (Voltage's own ship is not a decision)
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


class DismissRequest(BaseModel):
    # D2: why it was thrown out, when the user says (optional).
    reason: str | None = None


@app.post("/videos/{project_id}/plans/{plan_id}/items/{item_id}/dismiss")
@app.post("/projects/{project_id}/plans/{plan_id}/items/{item_id}/dismiss", deprecated=True)
def dismiss_item(project_id: str, plan_id: str, item_id: str, req: DismissRequest | None = None,
                 owner: str = Depends(current_owner)) -> dict:
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
    decision_id = _log_decision(project_id, plan_id, item, "rejected", reason=req.reason if req else None)
    return {**_plan_dict(repo.get_plan(project_id, plan_id)), "decision_id": decision_id}


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
    # Decision 0: the yes to taking an Approved video back to Draft.
    confirm_stage: bool = False


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
    _stage_gate([project_id], owner, req.confirm_stage, change=True)
    # 2026-10-19: a move is the arrangement's now: the line is pinned there and the others flow.
    moved = _pin_line(project_id, record, Selection(req.start, req.end), req.to)
    _left_approved(project_id, owner)
    return moved


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
    # Decision 0: the yes to taking an Approved video back to Draft.
    confirm_stage: bool = False


@app.put("/videos/{project_id}/arrangement")
def put_arrangement(project_id: str, req: ArrangementRequest, owner: str = Depends(current_owner)) -> dict:
    """The whole arrangement, as one action (one undo)."""
    record = _owned(project_id, owner)
    _stage_gate([project_id], owner, req.confirm_stage, change=True)
    _migrate_moves(project_id, record)
    before = _placements(record, _arrangement(project_id))
    new = arrange.Arrangement(order=tuple(req.order), pins=dict(req.pins), min_gap=req.min_gap, end=req.end)
    _save_arrangement(project_id, record, new, _arrangement_said(record, before, _placements(record, new)))
    _left_approved(project_id, owner)
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
    # Decision 0: the yes to taking an Approved video back to Draft (a kept line).
    confirm_stage: bool = False


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
    # Decision 0: the yes to taking an Approved video back to Draft (a kept line).
    confirm_stage: bool = False


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
    _stage_gate([project_id], owner, req.confirm_stage, change=True)
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
    _owned(project_id, owner)
    _stage_gate([project_id], owner, req.confirm_stage, change=True)
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
    return bool(settings.agent and settings.has_anthropic)


_agent_instance: agent_loop.Agent | None = None


def _agent() -> agent_loop.Agent:
    """The agent over one Anthropic client, made on first use (tests swap it)."""
    global _agent_instance
    if _agent_instance is None and settings.mock_vendors:
        from app.adapters.selection import anthropic_client
        _agent_instance = agent_loop.Agent(anthropic_client(settings, chaos), model=settings.agent_model, effort=settings.agent_effort)
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
        stage=_stage_for_turn,
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
        speakers=repo.speakers, voice_for=_voice_for, cloning_open=lambda o: flags.enabled("voices.cloning", o), remove_words=_remove_words, shift_words=_shift_by_pin, move_take=_moved,
        project=_project_view, suggest=_suggest_brief, help_search=lambda query: search_help_articles(query, limit=3),
        spend=lambda pid: _spend_summary(repo.get(pid).owner if repo.get(pid) else LOCAL_OWNER, video_id=pid),
        measured=lambda: getattr(voice, "last_measure", None), held_take=_held_take, jobs=line_jobs,
        hear_take=_hear_take,
    )


def _hear_take(video_id: str, candidate) -> list[str] | None:
    """9a: Whisper on the take (behind projects.consistency), charged by the minute."""
    from app.agent.take_hearing import hear_take
    record = repo.get(video_id)
    return hear_take(video_id, candidate, transcriber=transcriber, label=transcriber_label, ledger=ledger,
                     enabled=lambda: flags.enabled("projects.consistency", record.owner if record else LOCAL_OWNER))


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
                carry: dict | None = None, cap_usd: float | None = None, batch: bool = False) -> dict:
    """Queue one turn. `carry` continues the turn a cap question ended: the
    same turn id and start, its cap raised (`cap_usd`), the paid step approved.
    `batch` (F4): one video of a batch turn, past the batch's one gate: its paid
    steps are approved, its cap is `cap_usd` (its share of the batch's) and its
    lines wait as proposals for the batch board."""
    if any(j.kind == "turn" and j.project_id == project_id and not j.done for j in jobs.all()):
        raise HTTPException(status_code=409, detail="Voltage is still on the last thing you said.")
    if carry is None:
        analytics.track("first_turn", owner, {"video_id": project_id, "batch": batch})
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
    if record.consent is None and (autonomy == "draft" or approve or carry or batch):
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
    cap_usd = float((carry or {}).get("cap_usd") or cap_usd or prefs["turn_usd"])
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
        turn = AgentTurn(project_id=project_id, record=record, plan_id=plan.plan_id, autonomy=autonomy, said=text,
                         spend_approved=approve or bool(carry) or autonomy == "draft" or batch, budget=budget_, started_at=since,
                         report=report, commit_approved=approve, ask_before=prefs["ask_before"],
                         stop_requested=lambda: turn_id in _stops, batch=batch)
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
    return {"cancelled": _stop_video(project_id)}


def _stop_video(project_id: str) -> int:
    """The Stop path: queued jobs cancelled, and the running turn ends after
    the step it is on (F4's batch cancel uses it for each running video)."""
    cancelled = 0
    for job in activity.list(project_id, active=True, limit=200):
        if job.status == "queued":
            activity.cancel(job.job_id, "Stopped")
            cancelled += 1
    view = _turn_view(project_id)
    if view and view.get("status") == "running" and view.get("turn_id"):
        _stops.add(view["turn_id"])
        _set_turn(project_id, status="stopping", step="Stopping after this step")
    return cancelled


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


# ── F6: share tokens ─────────────────────────────────────────────────────────
#
# Signed, revocable, expiring links (app/store/shares.py). The owner makes and
# turns off links on a project; anyone holding a live link reads what it
# shares at /share/<token> with no account: a video's latest render, every
# video's in a project, or an export's files (B3). A dead link answers with
# a sentence (410 expired or turned off, 404 not valid), never a bare error.
# Making links ships with the first item that uses them (B3 under
# `projects.batch`, C2 under `projects.review`); opening one needs no flag.

share_key = shares_store.secret(settings.data_dir, settings.share_secret)
# G6: the fake C2PA signer's key, derived from the share key (a test signature, not a certificate).
c2pa_signer = provenance_mod.FakeSigner(hashlib.sha256((share_key if isinstance(share_key, bytes) else str(share_key).encode()) + b"c2pa").digest())
# What each scope shows: scope -> (share) -> {"title", "files": [{file_id, name, kind, size, duration, path}]}.
# B3 registers "export"; C2 may widen "video" with versions and comments.
SHARE_CONTENTS: dict = {}


def _shares_on(owner: str) -> None:
    if not (flags.enabled("projects.batch", owner) or flags.enabled("projects.review", owner)):
        raise HTTPException(status_code=404, detail="Not found")


def _share_url(token: str) -> str:
    return f"{settings.public_url}/#s/{token}"


def _share_dict(share: shares_store.Share) -> dict:
    return {**share.to_dict(), "state": share.state(), "url": _share_url(shares_store.token_for(share_key, share))}


def _render_file(video_id: str) -> dict | None:
    """A video's latest finished final render as a shared file, or None."""
    record = repo.get(video_id)
    done = repo.settings(video_id).get("render") if record else None
    if not done or not done.get("sha256"):
        return None
    path = artifacts.find(video_id, done["sha256"])
    if path is None:
        return None
    return {"file_id": f"{video_id}-{done['sha256'][:12]}", "name": done.get("filename") or f"{video_id}.mp4",
            "kind": "video", "size": path.stat().st_size, "duration": done.get("duration"), "video_id": video_id,
            "path": path}


def _video_share(share: shares_store.Share) -> dict:
    record = repo.get(share.target)
    if record is None:
        raise shares_store.ShareRefused("gone")
    found = _render_file(share.target)
    return {"title": record.source.filename, "files": [found] if found else []}


def _project_share(share: shares_store.Share) -> dict:
    project = repo.get_project(share.target)
    if project is None:
        raise shares_store.ShareRefused("gone")
    chosen = set(share.data.get("videos") or [])          # C2: a review link for some of the project's videos
    files = [f for f in (_render_file(r.source.project_id) for r in reversed(repo.list(project.owner, folder=project.project_id))
                         if not chosen or r.source.project_id in chosen) if f]
    return {"title": project.name, "files": files}


SHARE_CONTENTS.update({"video": _video_share, "project": _project_share})


def _shared(token: str) -> tuple[shares_store.Share, dict]:
    """The live share and what it shows, or the refusal as an HTTP error with its sentence."""
    try:
        share = shares_store.resolve(database, share_key, token)
        if share.project_id and repo.get_project(share.project_id) is None:
            raise shares_store.ShareRefused("gone")
        contents = SHARE_CONTENTS[share.scope](share)
        if share.role == "reviewer":
            contents = _review_contents(share, contents)     # C2: versions, comments, the reviewer's answer
        return share, contents
    except shares_store.ShareRefused as refused:
        status = 410 if refused.code in ("expired", "revoked") else 404
        raise HTTPException(status_code=status, detail=refused.message, headers={"X-Share-Refused": refused.code})


class ShareRequest(BaseModel):
    scope: Literal["project", "video", "export"]
    target: str | None = None
    role: Literal["viewer", "reviewer"] = "viewer"
    days: float = shares_store.DEFAULT_DAYS
    name: str | None = None
    # C2 (a reviewer link): the reviewer's email (a new version is emailed to
    # it), whether the page offers Download (off unless asked), and for a
    # project link the videos it asks about (all when empty).
    email: str | None = None
    allow_download: bool = False
    videos: list[str] | None = None


def _check_share_target(project: Project, scope: str, target: str) -> None:
    if scope == "project" and target != project.project_id:
        raise HTTPException(status_code=422, detail="A project link shares this project.")
    if scope == "video":
        record = repo.get(target)
        if record is None or record.owner != project.owner or record.folder_id != project.project_id:
            raise HTTPException(status_code=404, detail="That video is not in this project.")
    if scope not in SHARE_CONTENTS:
        raise HTTPException(status_code=422, detail="There is nothing of that kind to share yet.")
    if scope == "export" and export_engine.get(target, project.project_id) is None:
        raise HTTPException(status_code=404, detail="That export is not in this project.")


@app.post("/projects/{project_id}/shares", status_code=201)
def create_share(project_id: str, req: ShareRequest, owner: str = Depends(current_owner)) -> dict:
    """F6: a link to this project, one of its videos or one of its exports; 30 days unless asked."""
    _shares_on(owner)
    project = _owned_project(project_id, owner)
    target = req.target or project_id
    _check_share_target(project, req.scope, target)
    if req.role != "reviewer":
        reviewing: list[str] = []
        data = None
    else:
        _review_flag(owner)
        if req.scope == "export":
            raise HTTPException(status_code=422, detail="A review link asks about a video or a project's videos.")
        everything = review_videos(project, req.scope, target)
        if req.scope == "project" and req.videos:
            unknown = [v for v in req.videos if v not in everything]
            if unknown:
                raise HTTPException(status_code=404, detail="Some of those videos are not in this project.")
        reviewing = [v for v in everything if not req.videos or req.scope != "project" or v in req.videos]
        if not reviewing:
            raise HTTPException(status_code=422, detail="Pick at least one video to send for review.")
        data = _review_data(req, reviewing, project_scope=req.scope == "project" and bool(req.videos))
    try:
        with database.tx() as c:
            share, token = shares_store.create_in(c, share_key, owner=owner, project_id=project_id, scope=req.scope,
                                                  target=target, role=req.role, days=req.days, name=req.name, by=owner,
                                                  data=data)
            review_link_sent(c, reviewing, owner, req.name)
    except shares_store.ShareError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if req.role == "reviewer":
        _invite_reviewer(share, token, project.name)
    return _share_dict(share)


def review_videos(project: Project, scope: str, target: str) -> list[str]:
    """C1: the videos a review link asks about: the video, or every video in the project."""
    if scope == "video":
        return [target]
    if scope == "project":
        return [r.source.project_id for r in repo.list(project.owner, folder=project.project_id)]
    return []


def review_link_sent(c, video_ids: list[str], owner: str, name: str | None = None) -> list:
    """C1: sending a review link puts those videos In review, in the caller's
    transaction (the link's own). C2's Send for review calls this with
    `review_videos(...)` read before the transaction opens."""
    why = f"Review link sent to {name}." if name else "Review link sent."
    return stages.review_sent_in(c, video_ids, user_actor(owner), why)


@app.get("/projects/{project_id}/shares")
def list_shares(project_id: str, scope: str | None = None, target: str | None = None, owner: str = Depends(current_owner)) -> dict:
    _shares_on(owner)
    _owned_project(project_id, owner)
    return {"shares": [_share_dict(s) for s in shares_store.list_for(database, owner, project_id, scope, target)]}


@app.delete("/projects/{project_id}/shares/{share_id}")
def revoke_share(project_id: str, share_id: str, owner: str = Depends(current_owner)) -> dict:
    """Turn a link off for good: whoever opens it is told it was turned off."""
    _shares_on(owner)
    _owned_project(project_id, owner)
    share = shares_store.get(database, share_id)
    if share is None or share.owner != owner or share.project_id != project_id:
        raise HTTPException(status_code=404, detail="That link is not in this project.")
    return _share_dict(shares_store.revoke(database, share_id, owner))  # type: ignore[arg-type]


def _public_file(f: dict) -> dict:
    return {k: f.get(k) for k in ("file_id", "name", "kind", "size", "duration", "label", "video_id")}


@app.get("/share/{token}")
def open_share(token: str) -> dict:
    """No account: what a live link shares, each file with its name and size
    (a review link adds `review`: each video's versions, comments and answer)."""
    share, contents = _shared(token)
    analytics.track("review.page_opened" if share.role == "reviewer" else "share.opened", share.owner,
                    {"share_id": share.share_id, "scope": share.scope, "project_id": share.project_id})
    return {"scope": share.scope, "role": share.role, "name": share.name, "expires_at": share.expires_at,
            "title": contents["title"], "files": [_public_file(f) for f in contents["files"]],
            **{k: v for k, v in contents.items() if k not in ("title", "files") and not k.startswith("_")}}


@app.get("/share/{token}/files/{file_id}")
def shared_file(token: str, file_id: str, download: bool = False) -> FileResponse:
    """One shared file, played in place (range requests) or downloaded."""
    share, contents = _shared(token)
    found = next((f for f in contents.get("_all_files") or contents["files"] if f["file_id"] == file_id), None)
    if found is None or not Path(found["path"]).exists():
        raise HTTPException(status_code=404, detail="That file is not in this link.")
    if download and share.role == "reviewer" and not share.data.get("allow_download"):
        raise HTTPException(status_code=403, detail="Downloading is turned off for this link.")
    path = Path(found["path"])
    return FileResponse(path, media_type=_MEDIA_TYPES.get(path.suffix.lstrip("."), "application/octet-stream"),
                        filename=found["name"], content_disposition_type="attachment" if download else "inline")


# ── C2: client review link ───────────────────────────────────────────────────
#
# A review link is an F6 share with role reviewer (a video, or a project with
# the videos picked): no account; the page plays each video's latest final
# render, lists its versions (the final renders kept) with what changed
# between each and the one before, takes comments pinned to a time in a
# version, and an answer (Approve, Ask for changes) that moves the stage
# (stages.reviewer_approved / reviewer_asked_changes, under the reviewer's
# name). What the page sees is only the renders and their line text: no
# voice ids, no costs, no project data (`_review_contents`). Download is off
# unless the link allows it (the page shows a watermark with the reviewer's
# name over the player then; a watermark burned into the file is for later).
# The owner reads comments in the editor (markers and a list), replies,
# resolves, or hands one to Voltage. Email goes through app/notify: the owner
# gets a digest at most every 10 minutes; a reviewer who gave an email hears
# when a new version is ready.

email_sender = email_mod.sender_for(settings.email_provider, database)
REVIEW_COMMENTS_PER_LINK = 500
TEAM_NAME = "The editor"


def _final_versions(video_id: str) -> list[dict]:
    """The video's kept final renders, one per version, oldest version first."""
    best: dict[int, dict] = {}
    for r in (repo.settings(video_id).get("renders") or {}).values():
        version = r.get("version")
        if r.get("mode") != "final" or not version or not (r.get("render") or {}).get("sha256"):
            continue
        if version in best and best[version]["at"] >= r["at"]:
            continue
        best[version] = {"version": int(version), "at": r["at"], "sha256": r["render"]["sha256"],
                         "duration": r["render"].get("duration"), "edit_ids": (r.get("includes") or {}).get("edit_ids") or [],
                         "filename": (r.get("record") or {}).get("filename")}
    return [best[v] for v in sorted(best)]


def _current_version(video_id: str) -> int | None:
    """The version of the latest final render (what a reviewer plays first)."""
    kept = [f for f in _final_versions(video_id) if artifacts.find(video_id, f["sha256"]) is not None]
    return max(kept, key=lambda f: f["at"])["version"] if kept else None


def _said_over(record: ProjectRecord, start: float, end: float) -> str:
    return " ".join(w.text for w in record.transcript.words if w.start >= start - 0.05 and w.end <= end + 0.05).strip()


def _what_changed(record: ProjectRecord, edits: dict, before: set[str], after: set[str]) -> list[str]:
    """The lines that differ between two versions' edit sets, as plain sentences."""
    added = sorted((edits[i] for i in after - before if i in edits), key=lambda e: e.plan.selection.start)
    gone = sorted((edits[i] for i in before - after if i in edits), key=lambda e: e.plan.selection.start)
    added_ids, gone_ids = {e.edit_id for e in added}, {e.edit_id for e in gone}
    lines: list[str] = []
    for e in added:
        at, text = _clock(e.plan.selection.start), e.plan.new_text.strip()
        if e.plan.mix == "remove":
            if e.partner and e.partner in added_ids:
                continue                                  # a moved line: its placed half says it
            said = _said_over(record, e.plan.selection.start, e.plan.selection.end)
            lines.append(f'Took out the line at {at}: "{said}"' if said else f"Took out the line at {at}.")
        elif e.partner and e.partner in added_ids:
            lines.append(f'Moved "{text}" to {at}.')
        elif e.plan.mix == "replace":
            lines.append(f'{at} now says "{text}"')
        else:
            lines.append(f'Added a line at {at}: "{text}"')
    starts = [e.plan.selection.start for e in added]
    for e in gone:
        if any(abs(s - e.plan.selection.start) < 0.5 for s in starts):
            continue                                      # a newer take of the same line, said above
        if e.plan.mix == "remove" and e.partner and e.partner in gone_ids:
            continue
        at = _clock(e.plan.selection.start)
        if e.plan.mix in ("replace", "remove"):
            lines.append(f"{at} is back as shot.")
        else:
            lines.append(f'Took out the added line at {at}: "{e.plan.new_text.strip()}"')
    return lines[:30]


def _review_versions(video_id: str, record: ProjectRecord) -> list[dict]:
    """Each kept final render as a version a reviewer can pick, newest first,
    with what changed since the version before it (`_file`: the private file)."""
    edits = {e.edit_id: e for e in repo.list_edits(video_id)}
    out, prev = [], None
    for f in _final_versions(video_id):
        path = artifacts.find(video_id, f["sha256"])
        if path is None:
            continue
        file_id = f"{video_id}-{f['sha256'][:12]}"
        out.append({
            "version": f["version"], "file_id": file_id, "duration": f["duration"], "created_at": f["at"],
            "against": f"v{prev['version']}" if prev else "as shot",
            "changes": _what_changed(record, edits, set(prev["edit_ids"]) if prev else set(), set(f["edit_ids"])),
            "_file": {"file_id": file_id, "name": f["filename"] or f"{video_id}.mp4", "kind": "video",
                      "size": path.stat().st_size, "duration": f["duration"], "video_id": video_id, "path": path},
        })
        prev = f
    return out[::-1]


def _review_ids(share: shares_store.Share) -> list[str]:
    """The videos a review link asks about."""
    if share.scope == "video":
        return [share.target]
    if share.scope == "project":
        chosen = share.data.get("videos") or []
        live = [r.source.project_id for r in reversed(repo.list(share.owner, folder=share.target))]
        return [v for v in live if not chosen or v in chosen]
    return []


def _public_comment(c: comments_store.Comment) -> dict:
    """A comment as the review page shows it: who, when, what; the team's replies unnamed."""
    return {"comment_id": c.comment_id, "author": c.author_name if c.author_kind == "reviewer" else TEAM_NAME,
            "at_s": c.at_s, "version": c.version, "text": c.text, "status": c.status, "created_at": c.created_at,
            "replies": [{"author": r["author_name"] if r["author_kind"] == "reviewer" else TEAM_NAME, "text": r["text"], "at": r["at"]}
                        for r in c.replies]}


def _review_answer(share_id: str, video_id: str) -> dict | None:
    """The reviewer's latest answer on this link for this video."""
    with database.tx() as c:
        row = c.execute("SELECT * FROM project_events WHERE target = ? AND video_id = ? AND verb IN ('review.approved', 'review.changes_asked') "
                        "ORDER BY id DESC LIMIT 1", (share_id, video_id)).fetchone()
    if row is None:
        return None
    payload = json.loads(row["payload"] or "{}")
    return {"answer": "approved" if row["verb"] == "review.approved" else "changes_asked", "by": row["actor_name"],
            "version": payload.get("version"), "note": payload.get("note"), "at": row["at"]}


def _review_contents(share: shares_store.Share, contents: dict) -> dict:
    """What a review link adds to its share: per video, its versions, the
    comments made through this link and the reviewer's answer. `_all_files`
    (private) lets every version's file play."""
    videos, every = [], list(contents["files"])
    for video_id in _review_ids(share):
        record = repo.get(video_id)
        if record is None:
            continue
        versions = _review_versions(video_id, record)
        every += [v["_file"] for v in versions]
        current = max(versions, key=lambda v: v["created_at"])["version"] if versions else None
        videos.append({
            "video_id": video_id, "title": record.source.filename, "duration": record.source.duration,
            "current_version": current,
            "versions": [{k: v[k] for k in ("version", "file_id", "duration", "created_at", "against", "changes")} for v in versions],
            "comments": [_public_comment(c) for c in comments_store.for_share(database, share.share_id, video_id)],
            "answer": _review_answer(share.share_id, video_id),
            "read_only": _review_closed(share, video_id),
        })
    return {**contents, "_all_files": every,
            "review": {"reviewer": share.name, "allow_download": bool(share.data.get("allow_download")), "videos": videos}}


def _review_data(req, reviewing: list[str], project_scope: bool) -> dict:
    """A review link's data: download allowed or not, the reviewer's email,
    the version each video was on when sent (a newer one is emailed), and a
    project link's chosen videos."""
    address = (req.email or "").strip() or None
    if address and not email_mod.valid_address(address):
        raise HTTPException(status_code=422, detail="That email address does not look right.")
    data: dict = {"allow_download": bool(req.allow_download), "email": address,
                  "from_versions": {v: _current_version(v) for v in reviewing}}
    if project_scope:
        data["videos"] = reviewing
    return data


def _invite_reviewer(share: shares_store.Share, token: str, title: str) -> None:
    address = share.data.get("email")
    if not address:
        return
    try:
        email_sender.send(email_mod.Email(
            to=address, kind="review_invite", owner=share.owner,
            subject=f"Please review {title}",
            body="\n".join([f"Hi {share.name}," if share.name else "Hi,", "",
                            f"You have been asked to review {title}. Watch it, leave comments at the moment they are about, "
                            "then approve it or ask for changes. No account needed.", "",
                            f"Open the review: {_share_url(token)}", "",
                            f"The link works until {share.expires_at[:10]}."])))
    except Exception:  # noqa: BLE001 - the link is made; the email is a courtesy
        log.exception("review invite for %s", share.share_id)


def _tell_reviewers(video_id: str, version: int) -> None:
    """A new final version: email each live review link's reviewer (who gave
    an email) once per version newer than the one they were sent."""
    try:
        record = repo.get(video_id)
        if record is None:
            return
        for share in shares_store.list_for(database, record.owner):
            if share.role != "reviewer" or share.state() != "live" or not share.data.get("email"):
                continue
            if video_id not in _review_ids(share):
                continue
            key = f"review_told:{share.share_id}:{video_id}"
            told = max(int(repo.get_meta(key) or 0), int((share.data.get("from_versions") or {}).get(video_id) or 0))
            if version <= told:
                continue
            repo.set_meta(key, str(version))
            email_sender.send(email_mod.Email(
                to=share.data["email"], kind="version_ready", owner=share.owner,
                subject=f"v{version} of {record.source.filename} is ready to review",
                body="\n".join([f"Hi {share.name}," if share.name else "Hi,", "",
                                f"A new version (v{version}) of {record.source.filename} is ready. "
                                "The review page shows what changed since the last one.", "",
                                f"Open the review: {_share_url(shares_store.token_for(share_key, share))}"])))
    except Exception:  # noqa: BLE001 - news, never the render
        log.exception("new version email for %s", video_id)


def flush_review_digests(now: datetime | None = None) -> list:
    """Send every owner's digest that is due (C2; the scheduler calls this each minute)."""
    def link_for(item: dict) -> str | None:
        if item.get("project_id"):
            return f"{settings.public_url}/#p/{item['project_id']}"
        return f"{settings.public_url}/#v/{item['video_id']}" if item.get("video_id") else None
    return digest_mod.flush(
        database, email_sender, now or digest_mod.utcnow(),
        lambda owner: email_mod.address_for(database, owner, settings.notify_owner_email if owner == LOCAL_OWNER else None),
        link_for)


review_digests = digest_mod.DigestScheduler(flush_review_digests, every=60)


_lifespan_before_c2 = app.router.lifespan_context


@contextlib.asynccontextmanager
async def _lifespan_with_digests(a):
    """The running server sends due digests once a minute (a TestClient used without `with` never starts it),
    unless the worker sends them (AVE_WORKER_DIGESTS=1; rehearsal item 1: never both)."""
    if os.environ.get("AVE_WORKER_DIGESTS", "").strip().lower() not in {"1", "true", "yes", "on"}:
        review_digests.start()
    async with _lifespan_before_c2(a) as state:
        yield state


app.router.lifespan_context = _lifespan_with_digests


# D3: the purge runs once a day only when the server is started with
# AVE_PURGE_DAILY=1 (off by default; `python -m app.purge` by hand otherwise).
def _purge_due():
    from app.purge import purge, _vendor_delete
    return purge(database, artifacts.root, BIN_PURGE_DAYS,
                 delete_voice=_vendor_delete(settings, database, settings.data_dir),
                 consent_years=settings.consent_retention_years)      # G6: 7 years by default



BIN_PURGE_DAYS = bin_store.BIN_DAYS
daily_purge = PurgeScheduler(_purge_due)
_lifespan_before_d3 = app.router.lifespan_context


@contextlib.asynccontextmanager
async def _lifespan_with_purge(a):
    if settings.purge_daily:
        daily_purge.start()
    async with _lifespan_before_d3(a) as state:
        yield state


app.router.lifespan_context = _lifespan_with_purge


# Rehearsal item 1 (launch blocker 8): one API process per database (app/lease.py).
_lifespan_before_lease = app.router.lifespan_context


@contextlib.asynccontextmanager
async def _lifespan_with_lease(a):
    from app import lease as lease_mod
    import anyio.to_thread
    # Rehearsal item 3: how many plain (sync) routes run at once (AVE_HTTP_THREADS; anyio's default is 40).
    anyio.to_thread.current_default_thread_limiter().total_tokens = settings.http_threads
    held = lease_mod.acquire(database)          # raises LeaseHeld: the server does not start
    held.start()
    try:
        async with _lifespan_before_lease(a) as state:
            yield state
    finally:
        held.release()


app.router.lifespan_context = _lifespan_with_lease


# The reviewer's side (no account; the link is the key).

def _review_closed(share: shares_store.Share, video_id: str) -> str | None:
    """D4: the sentence a reviewer sees when the video's project is archived
    (comments and answers are refused; watching still works), else None."""
    if flags.enabled("projects.reuse", share.owner) and home_store.archived_project_of(database, video_id=video_id):
        return REVIEW_ARCHIVED
    return None


REVIEW_ARCHIVED = ("This project is archived, so comments and answers are closed for now. "
                   "You can still watch every version.")


def _reviewing(token: str, video_id: str) -> tuple[shares_store.Share, dict]:
    share, contents = _shared(token)
    if share.role != "reviewer":
        raise HTTPException(status_code=403, detail="This link is for watching only.")
    video = next((v for v in contents["review"]["videos"] if v["video_id"] == video_id), None)
    if video is None:
        raise HTTPException(status_code=404, detail="That video is not in this link.")
    if video.get("read_only"):
        raise HTTPException(status_code=423, detail=video["read_only"])
    return share, video


def _reviewer_name(share: shares_store.Share, given: str | None) -> str:
    return share.name or comments_store.clean_name(given) or "A reviewer"


class ReviewCommentRequest(BaseModel):
    video_id: str
    at_s: float
    text: str
    version: int | None = None
    name: str | None = None          # when the link names no one, the reviewer may


@app.post("/share/{token}/comments", status_code=201)
def review_comment(token: str, req: ReviewCommentRequest) -> dict:
    """A reviewer's comment, pinned to a time in a version."""
    share, video = _reviewing(token, req.video_id)
    if comments_store.count_for_share(database, share.share_id) >= REVIEW_COMMENTS_PER_LINK:
        raise HTTPException(status_code=429, detail="This link has taken as many comments as it can. Ask for a new link.")
    picked = next((v for v in video["versions"] if v["version"] == req.version), None)
    if req.version is not None and picked is None:
        raise HTTPException(status_code=422, detail="That version is not in this link.")
    length = (picked or {}).get("duration") or video["duration"] or 0
    if not (0 <= req.at_s <= float(length) + 0.5):
        raise HTTPException(status_code=422, detail="That time is not in the video.")
    name = _reviewer_name(share, req.name)
    g4 = flags.enabled("golive.g4", share.owner)
    try:
        with database.tx() as c:
            comment = comments_store.add_in(c, video_id=req.video_id, author_name=name, at_s=req.at_s, text=req.text,
                                            version=req.version, share_id=share.share_id)
            activity_log.record(c, "review.commented", Actor("reviewer", name), video_id=req.video_id, target=share.share_id,
                                payload={"comment_id": comment.comment_id, "at_s": comment.at_s, "version": req.version})
            payload = {"by": name, "video": video["title"], "at_s": comment.at_s, "version": req.version, "text": comment.text}
            if g4:      # G4: the bell, and email as the owner set it (C2's digest either way)
                inbox.add_in(c, share.owner, "review_comment", f"{name} commented on {video['title']} at {_clock(comment.at_s)}.",
                             body=comment.text, link=f"#v/{req.video_id}@{comment.at_s}", video_id=req.video_id,
                             project_id=comment.project_id, workspace_id=_workspace_of_video(c, req.video_id),
                             digest_payload=payload)
            else:
                digest_mod.queue_in(c, share.owner, "comment", project_id=comment.project_id, video_id=req.video_id,
                                    payload=payload)
    except comments_store.CommentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _public_comment(comment)


class ReviewAnswerRequest(BaseModel):
    video_id: str
    version: int | None = None
    note: str | None = None
    name: str | None = None


def _answer_review(token: str, req: ReviewAnswerRequest, approved: bool) -> dict:
    share, video = _reviewing(token, req.video_id)
    name = _reviewer_name(share, req.name)
    note = (req.note or "").strip()[: comments_store.MAX_TEXT] or None
    version = req.version or video["current_version"]
    folder = (repo.get(req.video_id) or None)
    g4 = flags.enabled("golive.g4", share.owner)
    with database.tx() as c:
        if approved:
            stages.reviewer_approved_in(c, req.video_id, name, version)
        else:
            stages.reviewer_asked_changes_in(c, req.video_id, name, f'{name} asked for changes: "{note}"' if note else "")
        verb = "review.approved" if approved else "review.changes_asked"
        activity_log.record(c, verb, Actor("reviewer", name), video_id=req.video_id, target=share.share_id,
                            payload={"version": version, "note": note})
        payload = {"by": name, "video": video["title"], "version": version, "note": note}
        if g4:          # G4: the bell, and email as the owner set it
            said = f"{name} approved {video['title']} v{version}." if approved else f"{name} asked for changes on {video['title']} v{version}."
            inbox.add_in(c, share.owner, "approval" if approved else "changes_requested", said, body=note or "",
                         link=f"#v/{req.video_id}", video_id=req.video_id, project_id=folder.folder_id if folder else None,
                         workspace_id=_workspace_of_video(c, req.video_id), digest_payload=payload)
        else:
            digest_mod.queue_in(c, share.owner, "approved" if approved else "changes_asked",
                                project_id=folder.folder_id if folder else None, video_id=req.video_id, payload=payload)
    return {"video_id": req.video_id, "answer": _review_answer(share.share_id, req.video_id)}


@app.post("/share/{token}/approve")
def review_approve(token: str, req: ReviewAnswerRequest) -> dict:
    """The reviewer approves: the video moves to Approved, logged under their name."""
    return _answer_review(token, req, approved=True)


@app.post("/share/{token}/changes")
def review_ask_changes(token: str, req: ReviewAnswerRequest) -> dict:
    """The reviewer asks for changes: the video moves to Changes asked."""
    return _answer_review(token, req, approved=False)


# The owner's side (behind `projects.review`).

def _owned_comment(video_id: str, comment_id: int) -> comments_store.Comment:
    found = comments_store.get(database, comment_id)
    if found is None or found.video_id != video_id:
        raise HTTPException(status_code=404, detail="That comment is not on this video.")
    return found


@app.get("/videos/{video_id}/comments")
def list_review_comments(video_id: str, owner: str = Depends(current_owner)) -> dict:
    """Every review comment on the video in time order, with the link it came through."""
    _review_flag(owner)
    _owned(video_id, owner)
    names = {s.share_id: s.name for s in shares_store.list_for(database, owner)}
    found = comments_store.for_video(database, video_id)
    return {"comments": [{**c.to_dict(), "link_name": names.get(c.share_id or "")} for c in found],
            "open": sum(1 for c in found if c.status == "open")}


class CommentReplyRequest(BaseModel):
    text: str


class MemberCommentRequest(BaseModel):
    at_s: float
    text: str
    version: int | None = None


@app.post("/videos/{video_id}/comments", status_code=201)
def add_member_comment(video_id: str, req: MemberCommentRequest, owner: str = Depends(current_owner)) -> dict:
    """G2: a comment from someone in the workspace (a Reviewer's way to
    comment), at a time in the video, like a review link's."""
    _review_flag(owner)
    record = _owned(video_id, owner)
    me = acting.get()
    who = me.user if me else owner
    name = (me.email if me else None) or email_mod.address_for(database, who) or ("The owner" if who == owner else "A member")
    if req.at_s > record.source.duration + 0.5:
        raise HTTPException(status_code=422, detail="That time is past the end of the video.")
    try:
        with database.tx() as c:
            comment = comments_store.add_in(c, video_id=video_id, author_name=name, at_s=req.at_s, text=req.text,
                                            version=req.version, author_kind="member")
            activity_log.record(c, "review.commented", user_actor(who), video_id=video_id, target=str(comment.comment_id))
    except comments_store.CommentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return comment.to_dict()


@app.post("/videos/{video_id}/comments/{comment_id}/replies")
def reply_review_comment(video_id: str, comment_id: int, req: CommentReplyRequest, owner: str = Depends(current_owner)) -> dict:
    """The owner's reply; the reviewer sees it under their comment."""
    _review_flag(owner)
    _owned(video_id, owner)
    _owned_comment(video_id, comment_id)
    try:
        with database.tx() as c:
            comment = comments_store.reply_in(c, comment_id, "user", owner, req.text)
            activity_log.record(c, "review.replied", user_actor(owner), video_id=video_id, target=str(comment_id))
    except comments_store.CommentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return comment.to_dict()


class CommentStatusRequest(BaseModel):
    resolved: bool = True


@app.post("/videos/{video_id}/comments/{comment_id}/resolve")
def resolve_review_comment(video_id: str, comment_id: int, req: CommentStatusRequest | None = None,
                           owner: str = Depends(current_owner)) -> dict:
    """Resolve a comment (or open it again with `resolved: false`)."""
    _review_flag(owner)
    _owned(video_id, owner)
    _owned_comment(video_id, comment_id)
    resolved = req.resolved if req else True
    with database.tx() as c:
        comment = comments_store.set_status_in(c, comment_id, resolved, owner)
        activity_log.record(c, "review.resolved" if resolved else "review.reopened", user_actor(owner),
                            video_id=video_id, target=str(comment_id))
    return comment.to_dict()


class ReviewLinkRequest(BaseModel):
    name: str | None = None
    email: str | None = None
    days: float = shares_store.DEFAULT_DAYS
    allow_download: bool = False


def _video_review_links(record: ProjectRecord, owner: str) -> list[shares_store.Share]:
    video_id = record.source.project_id
    return [s for s in shares_store.list_for(database, owner)
            if s.role == "reviewer" and video_id in (_review_ids(s) if s.scope != "video" else [s.target])]


@app.get("/videos/{video_id}/review-links")
def list_review_links(video_id: str, owner: str = Depends(current_owner)) -> dict:
    """The review links that ask about this video (its own and its project's), newest first."""
    _review_flag(owner)
    record = _owned(video_id, owner)
    return {"links": [_share_dict(s) for s in _video_review_links(record, owner)]}


@app.post("/videos/{video_id}/review-links", status_code=201)
def create_review_link(video_id: str, req: ReviewLinkRequest, owner: str = Depends(current_owner)) -> dict:
    """Send for review from the editor: a reviewer link to this video (in a project or not); it moves In review."""
    _review_flag(owner)
    record = _owned(video_id, owner)
    data = _review_data(req, [video_id], project_scope=False)
    try:
        with database.tx() as c:
            share, token = shares_store.create_in(c, share_key, owner=owner, project_id=record.folder_id, scope="video",
                                                  target=video_id, role="reviewer", days=req.days, name=req.name, by=owner,
                                                  data=data)
            review_link_sent(c, [video_id], owner, req.name)
    except shares_store.ShareError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    _invite_reviewer(share, token, record.source.filename)
    return _share_dict(share)


@app.delete("/videos/{video_id}/review-links/{share_id}")
def revoke_review_link(video_id: str, share_id: str, owner: str = Depends(current_owner)) -> dict:
    """Turn a review link off: whoever opens it is told so; their comments stay."""
    _review_flag(owner)
    record = _owned(video_id, owner)
    if share_id not in {s.share_id for s in _video_review_links(record, owner)}:
        raise HTTPException(status_code=404, detail="That link is not for this video.")
    return _share_dict(shares_store.revoke(database, share_id, owner))  # type: ignore[arg-type]


# ── B3: batch export ─────────────────────────────────────────────────────────
#
# Presets on the project (app/store/presets.py: platform frame, codec,
# loudness target, burned-in captions, file name pattern); the export itself
# is a parent Activity job with one child per video x preset
# (app/jobs/exports.py), each child the video's final render (the render
# cache: an unchanged video is not rendered again) delivered at the preset
# (app/render/deliver.py). A failed file is tried once more, then Failed
# with its reason; the rest carry on. A video whose every file was made moves
# to Exported (F5). The files are kept under the project
# (artifacts/projects/<id>/exports/<export id>/, the purge takes them with the
# project), downloaded one by one or as one zip built while it streams, and
# shared with an F6 link (scope export). Pre-flight runs A2's free checks as
# warnings, never a block. Behind `projects.batch`.

def _exports_dir(project_id: str, export_id: str) -> Path:
    return artifacts.root / "projects" / project_id / "exports" / export_id


def _caption_passages(video_id: str, record: ProjectRecord) -> list[captions_mod.Passage]:
    """What the video says now, in the source's time: the lines as shot no
    shipped edit replaced or removed, then every shipped edit's words."""
    edits = [e for e in repo.list_edits(video_id) if not e.reverted]
    covered = [e.plan.selection for e in edits if e.plan.mix in ("replace", "remove")]
    out = []
    for st in statements_of(record.transcript):
        mid = (st.start + st.end) / 2
        if not any(sel.start - 1e-3 <= mid <= sel.end + 1e-3 for sel in covered):
            out.append(captions_mod.Passage(st.text, st.start, st.end))
    for e in edits:
        if e.plan.mix == "remove" or not e.plan.new_text.strip():
            continue
        out.append(captions_mod.Passage(e.plan.new_text, e.plan.selection.start, e.plan.selection.end,
                                        added=e.plan.mix == "concatenate", duration=e.audio.duration if e.audio else None))
    return out


_export_names = threading.Lock()


def _deliver_one(record: dict, item: dict) -> dict:
    """One file of a batch export: the video's final render (reused when the
    edits have not changed), delivered at the preset, named by its pattern."""
    video_id, preset = item["video_id"], item["preset"]
    video = repo.get(video_id)
    if video is None:
        raise RuntimeError("This video was deleted.")
    project = repo.get_project(record["project_id"])
    out = _export(video, purpose="export")
    src = artifacts.find(video_id, out["render"]["sha256"])
    if src is None:
        raise RuntimeError("The render could not be found.")
    cues = captions_mod.cues(_caption_passages(video_id, video), out.get("pieces")) if preset["captions"] else None
    lang = _language_code(video)        # B2: a language version's language, else the master's own
    name = presets_store.file_name(preset["pattern"], project=project.name if project else "", video=video.source.filename,
                                   lang=lang, preset=preset["name"], version=out["version"])
    folder = _exports_dir(record["project_id"], record["export_id"])
    with _export_names:
        # Two presets with one pattern and name would collide: the second gets -2.
        taken = {i["file"]["name"] for i in (export_engine.get(record["export_id"]) or {"items": []})["items"]
                 if i.get("file") and i["index"] != item["index"]}
        stem, n = name[:-4], 2
        while name in taken:
            name, n = f"{stem}-{n}.mp4", n + 1
    with tempfile.TemporaryDirectory() as tmp:
        report = deliver_mod.deliver(src, Path(tmp) / "out.mp4", platform=preset["platform"], codec=preset["codec"],
                                     loudness_lufs=preset["loudness"], cues=cues)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(str(Path(tmp) / "out.mp4"), folder / name)
    _stamp_export(folder / name, video_id, record["owner"], video.source.media.sha256)    # G6: mark + manifest
    render_log.info("export file video=%s preset=%s name=%s framing=%s lufs=%s", video_id, preset["name"], name,
                    report["framing"], report["loudness_lufs"])
    _exported(record["owner"], video_id, float(report.get("duration") or 0.0), preset["name"])
    return {"name": name, "size": report["size"], "version": out["version"], "duration": report["duration"], "report": report}


def _export_video_done(record: dict, video_id: str) -> None:
    """Every file of the video made: it moves to Exported (F5), logged with who and why."""
    names = sorted({i["preset"]["name"] for i in record["items"] if i["video_id"] == video_id})
    stages.move(database, video_id, "exported", user_actor(record["owner"]), why=f"Exported as {', '.join(names)}")


def _export_closed(record: dict) -> None:
    summary = record.get("summary") or {}
    with database.tx() as c:
        activity_log.record(c, "export.finished", user_actor(record["owner"]), project_id=record["project_id"],
                            target=record["export_id"], payload={"ready": summary.get("ready"), "failed": summary.get("failed")})


export_engine = exports_mod.ExportEngine(activity, repo.get_meta, repo.set_meta, _deliver_one,
                                         on_video_done=_export_video_done, on_close=_export_closed)


def _file_state(item: dict) -> tuple[str, str, str | None]:
    """A file's row: state, its word, and why (a failure's reason)."""
    job = item.get("job") or {}
    status = job.get("status")
    if item.get("file"):
        return "ready", "Ready", None
    if status == "failed" or item.get("error"):
        return "failed", "Failed", item.get("error") or job.get("error_text") or "The render failed."
    if status == "running":
        return ("retrying", "Trying again", "The first try failed; trying once more.") if item.get("attempts", 0) > 1 else ("rendering", "Rendering", None)
    if status == "cancelled":
        return "failed", "Stopped", job.get("step_label")
    return "queued", "Queued", None


def _export_dict(record: dict, owner: str) -> dict:
    files = []
    for item in record["items"]:
        state, label, why = _file_state(item)
        files.append({k: item.get(k) for k in ("index", "video_id", "filename", "stage", "approved", "preset", "attempts", "job_id")}
                     | {"state": state, "label": label, "why": why, "file": item.get("file")})
    live = [s for s in shares_store.list_for(database, owner, record["project_id"], "export", record["export_id"]) if s.state() == "live"]
    ready = sum(1 for f in files if f["state"] == "ready")
    failed = sum(1 for f in files if f["state"] == "failed")
    return {"export_id": record["export_id"], "project_id": record["project_id"], "created_at": record["created_at"],
            "finished_at": record.get("finished_at"), "phase": record["phase"], "status": record.get("status"),
            "step": record.get("step"), "progress": record.get("progress", 0.0), "warnings": record.get("warnings", []),
            "files": files, "counts": {"total": len(files), "ready": ready, "failed": failed},
            "share": _share_dict(live[0]) if live else None}


def _export_or_404(project_id: str, export_id: str) -> dict:
    record = export_engine.get(export_id, project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="That export is not in this project.")
    return record


class PresetRequest(BaseModel):
    name: str | None = None
    platform: Literal["youtube", "reels", "feed"] | None = None
    codec: Literal["h264", "hevc"] | None = None
    loudness: float | None = None
    captions: bool | None = None
    pattern: str | None = None


def _preset_or_422(work):
    try:
        return work()
    except presets_store.PresetError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/projects/{project_id}/export-presets")
def list_export_presets(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """B3: the project's presets (the three defaults on first use) and what a preset may be."""
    _batch_flag(owner)
    _owned_project(project_id, owner)
    have = deliver_mod.codecs()
    return {"presets": [p.to_dict() for p in presets_store.list_presets(database, project_id, owner)],
            "platforms": [{"id": k, "label": v["label"], "width": v["size"][0], "height": v["size"][1]} for k, v in deliver_mod.PLATFORMS.items()],
            "codecs": [{"id": k, "label": v["label"], "available": k in have} for k, v in deliver_mod.CODECS.items()],
            "loudness": [{"lufs": k, "label": v["label"]} for k, v in deliver_mod.LOUDNESS.items()],
            "tokens": list(presets_store.TOKENS), "default_pattern": presets_store.DEFAULT_PATTERN,
            "captions": deliver_mod.caption_renderer() is not None}


@app.post("/projects/{project_id}/export-presets", status_code=201)
def add_export_preset(project_id: str, req: PresetRequest, owner: str = Depends(current_owner)) -> dict:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    preset = _preset_or_422(lambda: presets_store.add(database, project_id, req.model_dump(), owner, codecs=deliver_mod.codecs()))
    return preset.to_dict()


@app.patch("/projects/{project_id}/export-presets/{preset_id}")
def change_export_preset(project_id: str, preset_id: int, req: PresetRequest, owner: str = Depends(current_owner)) -> dict:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    preset = _preset_or_422(lambda: presets_store.update(database, project_id, preset_id, req.model_dump(), owner, codecs=deliver_mod.codecs()))
    if preset is None:
        raise HTTPException(status_code=404, detail="That preset is not in this project.")
    return preset.to_dict()


@app.delete("/projects/{project_id}/export-presets/{preset_id}", status_code=204)
def remove_export_preset(project_id: str, preset_id: int, owner: str = Depends(current_owner)) -> Response:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    if not presets_store.remove(database, project_id, preset_id, owner):
        raise HTTPException(status_code=404, detail="That preset is not in this project.")
    return Response(status_code=204)


@app.get("/projects/{project_id}/exports/preflight")
def export_preflight(project_id: str, owner: str = Depends(current_owner)) -> dict:
    """Before an export: every video with its stage (Approved ticked by
    default on the page) and the project check's free warnings. Never a block."""
    _batch_flag(owner)
    project = _owned_project(project_id, owner)
    videos = [{"video_id": r.source.project_id, "filename": r.source.filename, "duration": r.source.duration,
               "stage": stages.current(database, r.source.project_id) or "draft"}
              for r in reversed(repo.list(owner, folder=project_id))]
    for v in videos:
        v["stage_label"] = stages.LABELS.get(v["stage"], v["stage"])
        v["approved"] = v["stage"] == "approved"
    try:
        warnings = project_check_warnings(project.project_id)
    except Exception:  # noqa: BLE001 - a check that fails never stops an export
        log.exception("pre-flight check for %s", project_id)
        warnings = []
    warnings += _caption_warnings(repo.list(owner, folder=project_id), presets_store.list_presets(database, project_id, owner, seed=False))
    return {"videos": videos, "warnings": warnings}


def _caption_warnings(records: list, presets: list) -> list[dict]:
    """9c: captions not in Latin letters need ffmpeg with libass; without it they are left off, said before export."""
    if not any(p.captions for p in presets) or deliver_mod.has_libass():
        return []
    try:
        places = [{"video_id": r.source.project_id, "filename": r.source.filename, "t": None, "text": ""} for r in records
                  if not captions_mod.latin_only(p.text for p in _caption_passages(r.source.project_id, r))]
    except Exception:  # noqa: BLE001 - a warning that fails never stops an export
        log.exception("caption warning")
        return []
    if not places:
        return []
    names = ", ".join(p["filename"] for p in places)
    return [{"kind": "captions", "places": places, "fingerprint": "captions:no-libass",
             "message": f"Captions for {names} are not in Latin letters, and this server's ffmpeg has no libass to draw "
                        "them. Those files will be made without burned-in captions."}]


class ExportBatchRequest(BaseModel):
    video_ids: list[str]
    preset_ids: list[int]


@app.post("/projects/{project_id}/exports", status_code=201)
def start_batch_export(project_id: str, req: ExportBatchRequest, owner: str = Depends(current_owner)) -> dict:
    """One file per video x preset, under one parent job. Non-Approved videos
    may be picked (the page flags them); the pre-flight's warnings travel with it."""
    _batch_flag(owner)
    _owned_project(project_id, owner)
    videos = []
    for vid in dict.fromkeys(req.video_ids):
        record = repo.get(vid)
        if record is None or record.owner != owner or record.folder_id != project_id:
            raise HTTPException(status_code=404, detail="A video picked is not in this project.")
        videos.append(record)
    chosen = []
    for pid in dict.fromkeys(req.preset_ids):
        preset = presets_store.get(database, project_id, pid)
        if preset is None:
            raise HTTPException(status_code=404, detail="A preset picked is not in this project.")
        chosen.append(preset)
    if not videos or not chosen:
        raise HTTPException(status_code=422, detail="Pick at least one video and one preset.")
    try:
        warnings = project_check_warnings(project_id)
    except Exception:  # noqa: BLE001
        warnings = []
    warnings += _caption_warnings(videos, chosen)
    items = []
    for record in videos:
        stage = stages.current(database, record.source.project_id) or "draft"
        for preset in chosen:
            items.append({"video_id": record.source.project_id, "filename": record.source.filename, "stage": stage,
                          "approved": stage == "approved", "preset": preset.to_dict()})
    made = export_engine.start(project_id, owner, items, warnings)
    with database.tx() as c:
        activity_log.record(c, "export.started", user_actor(owner), project_id=project_id, target=made["export_id"],
                            payload={"videos": len(videos), "presets": [p.name for p in chosen], "files": len(items),
                                     "not_approved": sum(1 for v in items if not v["approved"]) // len(chosen),
                                     "warnings": len(warnings)})
    return _export_dict(made, owner)


@app.get("/projects/{project_id}/exports")
def list_batch_exports(project_id: str, limit: int = 5, owner: str = Depends(current_owner)) -> dict:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    out = []
    for eid in export_engine.of_project(project_id)[: max(1, min(limit, 20))]:
        record = export_engine.get(eid, project_id)
        if record is not None:
            out.append(_export_dict(record, owner))
    return {"exports": out}


@app.get("/projects/{project_id}/exports/{export_id}")
def get_batch_export(project_id: str, export_id: str, owner: str = Depends(current_owner)) -> dict:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    return _export_dict(_export_or_404(project_id, export_id), owner)


def _export_files(record: dict) -> list[dict]:
    """The export's made files, each with where it is on disk."""
    folder = _exports_dir(record["project_id"], record["export_id"])
    out = []
    for item in record["items"]:
        f = item.get("file")
        if f and (folder / f["name"]).exists():
            out.append({"file_id": str(item["index"]), "name": f["name"], "kind": "video", "size": f["size"],
                        "duration": f.get("duration"), "video_id": item["video_id"],
                        "label": f"{item['preset']['name']} · {item['filename']}", "path": folder / f["name"]})
    return out


@app.get("/projects/{project_id}/exports/{export_id}/files/{index}")
def batch_export_file(project_id: str, export_id: str, index: str, download: bool = False,
                      owner: str = Depends(media_owner)) -> FileResponse:
    _batch_flag(owner)
    _owned_project(project_id, owner)
    found = next((f for f in _export_files(_export_or_404(project_id, export_id)) if f["file_id"] == index), None)
    if found is None:
        raise HTTPException(status_code=404, detail="That file is not ready.")
    return FileResponse(found["path"], media_type="video/mp4", filename=found["name"],
                        content_disposition_type="attachment" if download else "inline")


class _ZipPipe(io.RawIOBase):
    """Where zipfile writes as the zip streams: the bytes since the last take."""

    def __init__(self) -> None:
        self._chunks: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, b) -> int:  # type: ignore[override]
        self._chunks.append(bytes(b))
        return len(b)

    def take(self) -> bytes:
        out = b"".join(self._chunks)
        self._chunks.clear()
        return out


def _zip_stream(files: list[dict]):
    """A zip of the files, built while it streams (stored, not squeezed: MP4 is compressed already)."""
    pipe = _ZipPipe()
    with zipfile.ZipFile(pipe, "w", zipfile.ZIP_STORED, allowZip64=True) as zf:
        for f in files:
            with zf.open(f["name"], "w", force_zip64=True) as dst, open(f["path"], "rb") as src:
                while chunk := src.read(1 << 20):
                    dst.write(chunk)
                    yield pipe.take()
            yield pipe.take()
    yield pipe.take()


def _zip_response(files: list[dict], title: str) -> StreamingResponse:
    if not files:
        raise HTTPException(status_code=404, detail="No files are ready to download yet.")
    name = (re.sub(r"[^A-Za-z0-9_-]+", "-", title).strip("-") or "export") + ".zip"
    return StreamingResponse(_zip_stream(files), media_type="application/zip",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@app.get("/projects/{project_id}/exports/{export_id}/zip")
def batch_export_zip(project_id: str, export_id: str, owner: str = Depends(media_owner)) -> StreamingResponse:
    """Every made file as one zip, built on demand while it downloads."""
    _batch_flag(owner)
    project = _owned_project(project_id, owner)
    files = _export_files(_export_or_404(project_id, export_id))
    analytics.track("export.zip_downloaded", owner, {"project_id": project_id, "export_id": export_id, "files": len(files)})
    return _zip_response(files, f"{project.name}-export")


class ExportShareRequest(BaseModel):
    days: float = shares_store.DEFAULT_DAYS


@app.post("/projects/{project_id}/exports/{export_id}/share", status_code=201)
def share_batch_export(project_id: str, export_id: str, req: ExportShareRequest | None = None,
                       owner: str = Depends(current_owner)) -> dict:
    """An F6 viewer link to the export's files: no account, 30 days unless asked."""
    _batch_flag(owner)
    _owned_project(project_id, owner)
    _export_or_404(project_id, export_id)
    try:
        share, _ = shares_store.create(database, share_key, owner=owner, project_id=project_id, scope="export",
                                       target=export_id, days=(req.days if req else shares_store.DEFAULT_DAYS), by=owner)
    except shares_store.ShareError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return _share_dict(share)


def _export_share(share: shares_store.Share) -> dict:
    record = export_engine.get(share.target, share.project_id)
    project = repo.get_project(share.project_id or "")
    if record is None or project is None:
        raise shares_store.ShareRefused("gone")
    return {"title": project.name, "files": _export_files(record), "exported_at": record.get("finished_at") or record["created_at"]}


SHARE_CONTENTS["export"] = _export_share


@app.get("/share/{token}/zip")
def shared_zip(token: str) -> StreamingResponse:
    """No account: every file a live link shares, as one zip."""
    share, contents = _shared(token)
    files = [f for f in contents["files"] if Path(f["path"]).exists()]
    analytics.track("export.zip_downloaded", share.owner, {"share_id": share.share_id, "files": len(files)})
    return _zip_response(files, contents["title"])


# ── G4: notifications ────────────────────────────────────────────────────────
#
# The bell (app/notify/inbox.py, app/notify_api.py): long work finishing,
# failures, review news (hooked into C2's review routes above) and spend
# alerts. Activity jobs tell `_job_notice` when they end: a failure always
# (but not a line inside a turn, nor a batch's or export's child: the turn or
# the parent says it), a finish only when it took JOB_NOTICE_SECONDS or more
# and is not a line or a mix. Spend alerts come from the ledger's
# `on_record`: after each charge the existing spend summary is read and each
# scope with a ceiling (the video, its project, the month) is checked against
# 50/80/100%, each said once per ceiling and period. All need `golive.g4`
# for the owner.

JOB_NOTICE_SECONDS = 60.0
JOB_WORDS = {"voice_line": "Voicing a line", "design_voice": "Designing a voice", "clone": "Cloning a voice",
             "mix": "The mix", "render_preview": "The preview", "export": "The export",
             "brief_update": "Bringing it up to date with the brief", "check": "The project check", "batch": "The batch",
             "learn": "Learning your style", "import": "The import", "data_export": "Your data export"}


def _workspace_of_video(c, video_id: str) -> str | None:
    row = c.execute("SELECT workspace_id FROM videos WHERE id = ?", (video_id,)).fetchone()
    return row[0] if row else None


def _job_place(key: str) -> tuple[str | None, str, str | None]:
    """(owner, what it is called, link) for a job's slot: a video, a project, or someone's own store."""
    record = repo.get(key)
    if record is not None:
        return record.owner, record.source.filename, f"#v/{key}"
    project = repo.get_project(key)
    if project is not None:
        return project.owner, project.name, f"#p/{key}"
    if key.startswith("user-"):
        return key[len("user-"):], "", None
    return None, "", None


def _job_notice(job) -> None:
    try:
        if job.status not in ("done", "failed") or job.detail.get("parent_id"):
            return
        if job.status == "failed" and job.kind == "voice_line" and job.turn_id:
            return
        took = job.detail.get("seconds")
        if job.status == "done" and (job.kind in ("voice_line", "mix")
                                     or not isinstance(took, (int, float)) or took < JOB_NOTICE_SECONDS):
            return
        owner, name, link = _job_place(job.video_id)
        if owner is None or not flags.enabled("golive.g4", owner):
            return
        what = JOB_WORDS.get(job.kind, "The work")
        if job.kind == "import":
            name = str(job.detail.get("filename") or "")
            link = f"#v/{job.detail['video_id']}" if job.detail.get("video_id") else None
        of = f" of {name}" if name else ""
        if job.status == "failed":
            title, body, kind = f"{what}{of} failed.", job.error_text or "", "job_failed"
        else:
            title, body, kind = f"{what}{of} is done.", job.step_label or "", "job_done"
        # Launch item 1: the notice goes to whoever started the work (a member), else the owner.
        to = job.detail.get("started_by") or owner
        with database.tx() as c:
            inbox.add_in(c, to, kind, title, body=body, link=link,
                         video_id=job.video_id if (link or "").startswith("#v/") else None,
                         project_id=job.video_id if (link or "").startswith("#p/") else None)
    except Exception:  # noqa: BLE001 - a notice never breaks the work it reports
        log.exception("notice for job %s", getattr(job, "job_id", "?"))


def _after_charge(video_id: str | None, folder_id: str | None) -> None:
    """Spend alerts at 50, 80 and 100% of each ceiling, from the spend summary."""
    try:
        record = repo.get(video_id) if video_id else None
        project = repo.get_project(folder_id) if folder_id else (_folder_of(record) if record else None)
        owner = record.owner if record else (project.owner if project else None)
        if owner is not None:
            _credit_alerts(owner)
        if owner is None or not flags.enabled("golive.g4", owner):
            return
        summary = _spend_summary(owner, video_id=video_id) if record else _spend_summary(owner, project_id=project.project_id)
        month = month_start().strftime("%Y-%m")
        checks = [("month", owner, summary.get("month"), f"{month}", "your monthly ceiling", "#usage")]
        if record is not None:
            checks.append(("video", video_id, summary.get("video"), "all", f"the ceiling of {record.source.filename}", f"#v/{video_id}"))
        if project is not None:
            checks.append(("project", project.project_id, summary.get("project"), "all", f"the ceiling of {project.name}", f"#p/{project.project_id}"))
        for scope, scope_id, s, period, whose, link in checks:
            if not s or not s.get("ceiling_usd"):
                continue
            hit = inbox.crossed(float(s["spent_usd"]), float(s["ceiling_usd"]))
            if hit is None:
                continue
            # Launch item 1: the owner always, and the member whose step made the charge.
            for to in dict.fromkeys(r for r in (owner, current_actor.get()) if r):
                with database.tx() as c:
                    if not inbox.spend_alert_once(c, to, scope, scope_id, f"{period}:{s['ceiling_usd']}", hit):
                        continue
                    said = (f"You have used {hit}% of {whose} ({money(float(s['spent_usd']))} of {money(float(s['ceiling_usd']))})."
                            if hit < 100 else f"You have reached {whose} ({money(float(s['ceiling_usd']))}). Paid steps stop until it is raised.")
                    if to != owner:
                        said = said.replace("You have used", "This workspace has used").replace("You have reached", "This workspace has reached").replace("your monthly", "its monthly")
                    inbox.add_in(c, to, "spend_alert", said, link=link,
                                 video_id=video_id if scope == "video" else None,
                                 project_id=scope_id if scope == "project" else None)
    except Exception:  # noqa: BLE001 - an alert never breaks a charge
        log.exception("spend alert after a charge")


def _credit_alerts(owner: str) -> None:
    """G3: 50/80/100% of the owner's credits, each said once per amount granted
    (a top-up or a new month starts again), through G4's bell and digest."""
    try:
        if not (flags.enabled("golive.g3", owner) and flags.enabled("golive.g4", owner)):
            return
        from app import billing
        if not billing.has_account(database, owner):
            return
        got = billing.credits(database, owner, lambda at: ledger.spent_usd_by_owner(owner, at))
        hit = inbox.crossed(got["used"], got["granted"])
        if hit is None:
            return
        with database.tx() as c:
            if not inbox.spend_alert_once(c, owner, "credits", owner, f"granted:{got['granted']:.2f}", hit):
                return
            said = (f"You have used {hit}% of your credits ({got['used']:.2f} of {got['granted']:.2f})."
                    if hit < 100 else "You have used all your credits. Paid steps are paused until you top up or pick a plan.")
            inbox.add_in(c, owner, "spend_alert", said, link="#billing")
    except Exception:  # noqa: BLE001 - an alert never breaks a charge
        log.exception("credit alert after a charge")


ledger.on_record = _after_charge


# ── G6: trust and safety ────────────────────────────────────────────────────
# Routes in app/safety_api.py; these are the pieces that need the app.

def withdraw_consent_now(video_id: str, owner: str) -> dict:
    """Consent withdrawn now (the owed D3 item): the video's clones are deleted
    at the voice service at once (a kept voice of the owner's is only
    forgotten here), consent is cleared so nothing new is cloned until it is
    given again, and the withdrawal is logged."""
    _owned(video_id, owner)
    before = repo.clones(video_id)
    kept = _kept_voice_ids()
    failed = clones.purge(video_id, keep=kept)
    deleted = len([v for v in before.values() if v and v not in kept and v not in failed])
    had = repo.withdraw_consent(video_id)
    with database.tx() as c:
        activity_log.record(c, "consent.withdrawn", user_actor(owner), video_id=video_id, target=video_id,
                            payload={"deleted": deleted, "failed": len(failed), "had": bool(had)})
    if failed:
        said = (f"Consent withdrawn. {len(failed)} voice {'clone' if len(failed) == 1 else 'clones'} could not be deleted at "
                "the voice service yet; they cannot be used, and deleting them is tried again when the Bin empties.")
    elif deleted:
        said = "Consent withdrawn. The speaker's voice clone was deleted at the voice service."
    else:
        said = "Consent withdrawn. There was no voice clone to delete."
    return {"withdrawn": True, "deleted": deleted, "failed": failed, "said": said}


def data_export_path(owner: str, job_id: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", owner)
    return settings.data_dir / "data-exports" / safe / f"{job_id}.zip"


def start_data_export(owner: str) -> dict:
    """Your data as a zip, as an Activity job keyed by your own store."""
    job = activity.create(_user_store(owner), "data_export", step_label="Queued", detail={"owner": owner})
    with database.tx() as c:
        c.execute("UPDATE jobs SET workspace_id = ? WHERE job_id = ?", (personal(c, owner), job.job_id))
        cur = c.execute("INSERT INTO data_requests (owner, kind, status, job_id, created_at) VALUES (?, 'export', 'running', ?, ?)",
                        (owner, job.job_id, _now()))
        request_id = int(cur.lastrowid)
        analytics.track_in(c, "data.export_requested", owner, {})

    def run() -> None:
        activity.start(job.job_id, "Collecting your records")
        try:
            made = dataexport.build(database, owner, artifacts.root, data_export_path(owner, job.job_id))
            activity.finish(job.job_id, step_label="Ready", detail={"owner": owner, **made})
            status = "done"
            analytics.track("data.export_ready", owner, {"rows": made["rows"], "media": made["media"]})
        except Exception as exc:  # noqa: BLE001 - a failed export says why; the server stays up
            log.exception("data export %s failed", job.job_id)
            activity.fail(job.job_id, "export_failed", f"The export stopped: {str(exc)[:200] or type(exc).__name__}")
            status = "failed"
        with database.tx() as c:
            c.execute("UPDATE data_requests SET status = ?, done_at = ? WHERE id = ?", (status, _now(), request_id))
    if DATA_EXPORT_IN_BACKGROUND:
        work_pool.submit(run)
    else:
        run()
    with database.tx() as c:
        row = dict(c.execute("SELECT * FROM data_requests WHERE id = ?", (request_id,)).fetchone())
    found = activity.get(job.job_id)
    return {"request": {**row, "job": found.to_dict() if found else None}}


DATA_EXPORT_IN_BACKGROUND = True


def _stamp_export(path: Path, video_id: str, owner: str, source_sha: str | None) -> dict | None:
    """G6: the invisible mark and the C2PA-style manifest on one exported file
    (golive.g6); recorded so the mark can be traced. Never fails the export."""
    if not flags.enabled("golive.g6", owner):
        return None
    try:
        made = provenance_mod.stamp(path, video_id=video_id, owner=owner, watermarker=watermarker, signer=c2pa_signer,
                                    source_sha=source_sha)
        with database.tx() as c:
            c.execute("INSERT INTO provenance_marks (mark, owner, video_id, file, sha256, manifest, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      (made["mark"], owner, video_id, path.name, made["sha256"], Path(made["manifest"]).read_text(), _now()))
            analytics.track_in(c, "export.provenance_stamped", owner, {"video_id": video_id})
        return made
    except Exception:  # noqa: BLE001 - provenance never breaks an export; the log says why
        log.exception("could not stamp the export of %s", video_id)
        return None


def _provenance_export(record: ProjectRecord, out: dict) -> dict:
    """The Export page's file, marked and with its manifest (G6): a marked copy of
    the render as its own artifact, made once per render; the manifest sits
    beside it and is served at /videos/{id}/artifacts/{sha}/c2pa."""
    video_id, owner = record.source.project_id, record.owner
    if not flags.enabled("golive.g6", owner):
        return out
    src_sha = out["render"]["sha256"]
    done = (repo.settings(video_id).get("provenance") or {}).get(src_sha)
    if done and artifacts.find(video_id, done["sha256"]) is not None:
        return {**out, "render": {**out["render"], "sha256": done["sha256"]}, "provenance": done}
    src = artifacts.find(video_id, src_sha)
    if src is None:
        return out
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / f"{Path(record.source.filename).stem}-voltage.mp4"
        shutil.copyfile(src, work)
        made = _stamp_export(work, video_id, owner, record.source.media.sha256)
        if made is None:
            return out
        art = artifacts.put_file(video_id, work, kind="video", container="mp4", duration=float(out["render"].get("duration") or 0.0))
        stored = artifacts.find(video_id, art.sha256)
        if stored is not None:
            shutil.copyfile(made["manifest"], provenance_mod.manifest_path(Path(stored)))
    done = {"sha256": art.sha256, "mark": made["mark"], "source_sha256": src_sha}
    marks = dict(repo.settings(video_id).get("provenance") or {})
    marks[src_sha] = done
    repo.set_settings(video_id, provenance=marks)
    return {**out, "render": {**out["render"], "sha256": art.sha256}, "provenance": done}


@app.get("/videos/{video_id}/artifacts/{sha256}/c2pa")
def get_c2pa(video_id: str, sha256: str, owner: str = Depends(media_owner)) -> dict:
    """G6: the C2PA-style manifest beside an exported file."""
    _owned(video_id, owner)
    path = artifacts.find(video_id, sha256)
    manifest = provenance_mod.manifest_path(Path(path)) if path else None
    if manifest is None or not manifest.exists():
        raise HTTPException(status_code=404, detail="That file has no provenance manifest.")
    return json.loads(manifest.read_text())


# ── G8: errors nothing caught ────────────────────────────────────────────────
# A request that raises is reported (with the route and who) and then raised
# on as before, so the response and the tests see exactly what they did.

@app.middleware("http")
async def _report_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as exc:
        me = acting.get()
        error_reporter.capture_exception(exc, {"source": "server", "where": f"{request.method} {request.url.path}",
                                               "owner": me.user if me else None})
        raise


# ── Launch item 1: a Reviewer sees only what was shared with them ────────────
# The role middleware (below) has already refused a Reviewer's writes other
# than comments. Here, reads: the lists (/videos, /projects) are filtered in
# their routes; a video or project not shared, and every account-wide page
# (usage, voices, templates, the Bin, search...), answers 404 as if it were not there.

_REVIEWER_OPEN = re.compile(r"^/(auth/|me(/|$)|invites/|help(/|$)|workspace(/switch)?$|videos$|projects$|health$|ready$|status$|media/|account$)")
_REVIEWER_VIDEO = re.compile(r"^/videos/([^/]+)(/|$)")
_REVIEWER_PROJECT = re.compile(r"^/projects/([^/]+)(/|$)")
_REVIEWER_JOB = re.compile(r"^/jobs/([^/]+)$")


def _reviewer_may_read(me: Acting, path: str) -> bool:
    path = path[4:] if path.startswith("/api/") else path
    if _REVIEWER_OPEN.match(path):
        return True
    wid = me.workspace_id or members_store.workspace_of(database, me.owner)
    hit = _REVIEWER_VIDEO.match(path)
    if hit:
        return members_store.can_see(database, wid, me.user, video_id=hit.group(1))
    hit = _REVIEWER_PROJECT.match(path)
    if hit:
        return members_store.can_see(database, wid, me.user, project_id=hit.group(1))
    hit = _REVIEWER_JOB.match(path)
    if hit:
        job = jobs.get(hit.group(1))
        return job is not None and members_store.can_see(database, wid, me.user, video_id=job.project_id)
    return False


def _reviewer_filter() -> tuple[set[str], set[str]] | None:
    """(video ids, project ids) a Reviewer may list, or None for everyone else."""
    me = acting.get()
    if me is None or me.role != "reviewer":
        return None
    wid = me.workspace_id or members_store.workspace_of(database, me.owner)
    got = members_store.shares(database, wid, me.user)
    projects = set(got["projects"])
    from app.store.repository import ANY_FOLDER
    videos = set(got["videos"]) | {r.source.project_id for r in repo.list(me.owner, folder=ANY_FOLDER) if r.folder_id in projects}
    return videos, projects


# ── Launch item 2: rate limits per user ──────────────────────────────────────
# Defined before the roles middleware, so it runs inside it and knows who is acting.

from app.ratelimit import Limits, refusal as limit_refusal  # noqa: E402

rate_limits = Limits()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@app.middleware("http")
async def _rate_limited(request: Request, call_next):
    me = acting.get()
    over = rate_limits.check(request.method, request.url.path, me.user if me else None, _client_ip(request))
    if over:
        window = rate_limits.window(over)
        analytics.track("rate_limited", me.user if me else None, {"bucket": over})
        return JSONResponse(status_code=429, content={"detail": limit_refusal(over, window), "code": "rate_limited"},
                            headers={"Retry-After": str(int(window))})
    return await call_next(request)


# ── G2: roles ────────────────────────────────────────────────────────────────
# Defined last so it is the outermost middleware: who is acting is known
# before any other middleware or route runs (app/workspace_api.py).

@app.middleware("http")
async def _roles(request: Request, call_next):
    from app.workspace_api import role_refusal
    me = _resolve_acting(request) if settings.auth_mode == "off" else await asyncio.to_thread(_resolve_acting, request)
    a, b = acting.set(me), current_actor.set(me.user if me else None)
    try:
        if me is not None and me.role != "owner":
            refusal = role_refusal(me.role, request.method, request.url.path)
            if refusal:
                return JSONResponse(status_code=403, content={"detail": refusal, "code": "role"})
            if me.role == "reviewer" and not await asyncio.to_thread(_reviewer_may_read, me, request.url.path):
                return JSONResponse(status_code=404, content={"detail": "Not found"})
        return await call_next(request)
    finally:
        acting.reset(a)
        current_actor.reset(b)


# ── Help, the tutorial, onboarding: the coordinator's routers ────────────────

def _mount_optional_routers() -> None:
    import importlib
    for name in ("app.onboarding", "app.help", "app.tutorial", "app.workspace_api", "app.accounts_api", "app.notify_api", "app.analytics_api", "app.feedback_api", "app.billing_api", "app.safety_api"):
        try:
            module = importlib.import_module(name)
        except ImportError:
            log.info("%s is not here yet; its routes are not mounted", name)
            continue
        router = getattr(module, "router", None)
        if router is not None:
            app.include_router(router)


_mount_optional_routers()


# ── Launch item 2: the edges ─────────────────────────────────────────────────
# A failure nothing caught answers one sentence (no stack trace, no
# exception text); the details go to the log and the error reporter. Every
# response says not to sniff types or be framed. CORS lets only Voltage's
# own address call the API with cookies (AVE_CORS_ORIGINS, default the public URL).

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

SERVER_FAULT = "Something went wrong on our side. It has been reported; please try again."


@app.exception_handler(Exception)
async def _no_stack_traces(request: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return JSONResponse(status_code=500, content={"detail": SERVER_FAULT})


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    return response


app.add_middleware(
    CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["content-type", "x-requested-with", "range"], max_age=600,
)
