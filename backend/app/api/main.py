import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, File, Form, UploadFile
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
from app.store.repository import ProjectRepository
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
repo = ProjectRepository()
artifacts = ArtifactStore(settings.data_dir / "artifacts")
# Real vendors when a key is configured, the deterministic mocks otherwise, and
# the mocks always under AVE_DRY_RUN — so the app runs offline and free.
budget = VoiceBudget(ceiling=settings.voice_budget_chars)
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


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str


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
    # The chat so far, oldest first, so follow-ups can be understood.
    history: list[ChatTurn] = []


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


@app.post("/projects")
async def create_project(
    file: UploadFile = File(...),
    consent: bool = Form(False),
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
    repo.create(source, transcript, granted)
    return {
        "project_id": project_id,
        "filename": filename,
        "duration": probed.duration,
        "media": _artifact_dict(media),
        "consent": _consent_dict(granted),
        "transcript": [
            {"text": w.text, "start": w.start, "end": w.end} for w in transcript.words
        ],
    }


@app.post("/projects/{project_id}/consent")
def grant_consent(project_id: str) -> dict:
    """Confirm rights for a project uploaded without them.

    Lets a refused generation be recovered without re-uploading.
    """
    if repo.get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
    recorded = repo.grant_consent(project_id, Consent(granted_at=_now()))
    return {"project_id": project_id, "consent": _consent_dict(recorded)}


@app.get("/projects/{project_id}/artifacts/{sha256}")
def get_artifact(project_id: str, sha256: str) -> FileResponse:
    """Serve stored media by content address, with range requests.

    Scoped to the project so one project's id cannot be used to read another's
    media, and `sha256` is validated as a bare hex digest by the store.
    """
    if repo.get(project_id) is None:
        raise HTTPException(status_code=404, detail="project not found")
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
def preview_edit(project_id: str, req: EditRequest) -> dict:
    """Start generation and hand back a job to poll.

    Generation takes minutes once lip-sync is a real vendor (design spec §7),
    so this cannot be a synchronous call.
    """
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    if record.consent is None:
        # Design spec §2/§7: non-negotiable, and this is the moment it binds —
        # the last point before anything synthesizes this speaker's voice.
        raise HTTPException(status_code=403, detail=CONSENT_REQUIRED)

    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    context = edit_context(record.transcript, selection, record.source.duration)
    history = [Turn(t.role, t.text) for t in req.history]
    candidate_id = repo.next_candidate_id(project_id)
    job = jobs.create("preview", project_id)

    def work(report) -> dict:
        if req.text is not None:
            intent = Intent(action="speak", new_text=req.text)
        else:
            report(0.02, "Reading your request")
            intent = interpreter.interpret(req.prompt, history, context)
        if intent.action != "speak":
            return {"type": "reply", "text": intent.reply}

        # Replacing speech is the obvious reading of an edit over words; over
        # music or silence it is not, so the user is asked.
        mix = req.mix or intent.mix or ("replace" if context.has_speech else None)
        if mix is None:
            return mix_question(intent.new_text, context)

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
            return fit_question(
                plan.new_text, mix, exc.natural, exc.target,
                selection.start, record.source.duration,
            )
        # Retained so approval commits this exact candidate rather than
        # re-running generation, which real vendors would not reproduce
        # byte-for-byte.
        repo.save_candidate(project_id, candidate)
        return _candidate_dict(candidate)

    runner.submit(job, work)
    return _job_dict(job)


@app.get("/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return _job_dict(job)


@app.post("/projects/{project_id}/edits")
def approve_edit(project_id: str, req: ApproveRequest) -> dict:
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
def export_project(project_id: str) -> dict:
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
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
