import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import shutil

from fastapi import Depends, FastAPI, HTTPException, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from typing import Literal

from app.domain.models import (
    Source, Selection, ContinuityReport, EditCandidate, ApprovedEdit, MediaArtifact,
    Consent, EditPlan, Intent,
)
from app.domain.transcript import snap_to_word_boundaries
from app.config import load_settings
from app.media import ffmpeg, ingest
from app.adapters.mock import MockLipSyncAdapter
from app.adapters.openai_whisper import TranscriptionError
from app.adapters.selection import (
    select_continuity, select_interpreter, select_transcriber, select_voice,
)
from app.budget import VoiceBudget, BudgetExceeded
from app.orchestrator.intent import Turn, edit_context
from app.orchestrator.questions import fit_question, mix_question
from app.media.ffmpeg import SpanMismatch
from app.orchestrator.pipeline import run_edit
from app.store.db import Database
from app.usage import Ledger, WHISPER_USD_PER_MINUTE, claude_usd
from app.store.repository import ProjectRecord, ProjectRepository, LOCAL_OWNER
from app.store.artifacts import ArtifactStore
from app.render.renderer import render
from app.render.compose import compose
from app.jobs.store import JobStore, Job
from app.jobs.runner import JobRunner

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
jobs = JobStore()
runner = JobRunner(jobs)


@app.get("/health")
def health() -> dict:
    """Which capabilities are real in this process — handy when a key is missing."""
    return {
        "transcription": transcriber_label,
        "voice": voice_label,
        "lipsync": "mock",
        "continuity": continuity_label,
        "intent": interpreter_label,
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
    mix: Literal["replace", "layer", "concatenate"] | None = None
    # What the chat shows for this turn when it isn't the prompt itself — the
    # label of an option picked in answer to a question.
    display: str | None = None


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
        },
        "audio": _artifact_dict(candidate.audio),
        "frames": _artifact_dict(candidate.frames),
        "continuity": _continuity_dict(candidate.continuity),
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


def current_owner() -> str:
    """Who is calling — the auth seam (Phase 9c).

    Everyone is the local owner until sign-in lands; then this returns the
    verified subject from the session, and every route below is already
    scoped by it.
    """
    return LOCAL_OWNER


def _owned(project_id: str, owner: str) -> ProjectRecord:
    """The caller's project, or 404. Someone else's project is indistinguishable
    from a missing one, so ids leak nothing."""
    record = repo.get(project_id)
    if record is None or record.owner != owner:
        raise HTTPException(status_code=404, detail="project not found")
    return record


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
    }


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
    return _project_dict(repo.get(project_id))


@app.get("/projects")
def list_projects(owner: str = Depends(current_owner)) -> dict:
    """The caller's projects, newest first — enough to show and reopen them."""
    return {"projects": [
        {
            "project_id": r.source.project_id,
            "filename": r.source.filename,
            "duration": r.source.duration,
            "created_at": r.created_at,
            "edits": len(repo.list_edits(r.source.project_id)),
        }
        for r in repo.list(owner)
    ]}


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
                "overridden": e.overridden,
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
        "voice_characters": budget.spent(project_id),
        "voice_characters_ceiling": budget.ceiling,
        "lines": [
            {"vendor": u.vendor, "what": u.what, "unit": u.unit, "units": round(u.units, 4),
             "usd": round(u.usd, 4), "calls": u.calls}
            for u in ledger.lines(project_id)
        ],
    }


@app.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, owner: str = Depends(current_owner)) -> None:
    """Delete the project and all of its media. This is also how consent is
    withdrawn (design spec §2): nothing of the speaker is kept."""
    _owned(project_id, owner)
    repo.delete(project_id)
    shutil.rmtree(artifacts.root / project_id, ignore_errors=True)


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

    def meter(model: str, input_tokens: int, output_tokens: int) -> None:
        ledger.record(project_id, "anthropic", "intent", input_tokens + output_tokens, "tokens",
                      claude_usd(model, input_tokens, output_tokens))

    def work(report) -> dict:
        # No new paid work once the project has reached its spend ceiling.
        ledger.ensure_can_spend(project_id)
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

        plan = EditPlan(selection, intent.new_text, req.voice_profile_id, fit=req.fit, mix=mix)
        cost = voice.cost_of(plan)
        if not budget.can_afford(project_id, cost):
            raise BudgetExceeded(cost, budget.remaining(project_id))
        try:
            candidate = run_edit(
                candidate_id, plan, record.source, voice, lipsync, continuity, report,
                transcript=record.transcript,
                max_regenerations=settings.max_regenerations,
            )
        except SpanMismatch as exc:
            if plan.fit is not None:
                raise
            return _asked(fit_question(
                plan.new_text, mix, exc.natural, exc.target,
                selection.start, record.source.duration,
            ))
        # Retained so approval commits this exact candidate rather than
        # re-running generation, which real vendors would not reproduce
        # byte-for-byte.
        repo.save_candidate(project_id, candidate)
        return _candidate_dict(candidate)

    def _asked(question: dict) -> dict:
        repo.add_message(project_id, "assistant", question["question"])
        return question

    runner.submit(job, work)
    return _job_dict(job)


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
    edit_id = f"e{len(repo.list_edits(project_id)) + 1}"
    repo.append_edit(project_id, ApprovedEdit(
        edit_id=edit_id,
        candidate_id=candidate.candidate_id,
        plan=candidate.plan,
        audio=candidate.audio,
        frames=candidate.frames,
        overridden=overridden,
    ))
    return {
        "edit_id": edit_id,
        "candidate_id": candidate.candidate_id,
        "overridden": overridden,
        "continuity": _continuity_dict(candidate.continuity),
    }


@app.post("/projects/{project_id}/export")
def export_project(project_id: str, owner: str = Depends(current_owner)) -> dict:
    record = _owned(project_id, owner)
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
