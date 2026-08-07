from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.domain.models import Source, Selection, ContinuityReport, EditCandidate, ApprovedEdit
from app.domain.transcript import snap_to_word_boundaries
from app.adapters.mock import MockTranscriptionAdapter, MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.planner import build_edit_plan
from app.orchestrator.pipeline import run_edit
from app.store.repository import ProjectRepository
from app.render.renderer import render

app = FastAPI(title="Agentic Video Editor")

# Wiring (module-level singletons for this in-memory slice).
repo = ProjectRepository()
transcriber = MockTranscriptionAdapter()
voice = MockVoiceAdapter()
lipsync = MockLipSyncAdapter()
continuity = ContinuityEngine()


class CreateProjectRequest(BaseModel):
    filename: str
    duration: float


class EditRequest(BaseModel):
    prompt: str
    start: float
    end: float
    voice_profile_id: str = "speaker-1"


def _continuity_dict(report: ContinuityReport) -> dict:
    return {
        "voice_match": report.voice_match,
        "prosody": report.prosody,
        "audio_integration": report.audio_integration,
        "lip_sync": report.lip_sync,
        "passed": report.passed,
        "warnings": list(report.warnings),
    }


def _candidate_dict(candidate: EditCandidate) -> dict:
    return {
        "plan": {
            "selection": {
                "start": candidate.plan.selection.start,
                "end": candidate.plan.selection.end,
            },
            "new_text": candidate.plan.new_text,
            "voice_profile_id": candidate.plan.voice_profile_id,
        },
        "audio_ref": candidate.audio_ref,
        "frames_ref": candidate.frames_ref,
        "continuity": _continuity_dict(candidate.continuity),
    }


def _build_candidate(project_id: str, req: EditRequest) -> EditCandidate:
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    selection = snap_to_word_boundaries(record.transcript, Selection(req.start, req.end))
    plan = build_edit_plan(req.prompt, selection, req.voice_profile_id)
    return run_edit(plan, record.source, voice, lipsync, continuity)


@app.post("/projects")
def create_project(req: CreateProjectRequest) -> dict:
    project_id = repo.next_id()
    source = Source(project_id=project_id, filename=req.filename, duration=req.duration)
    transcript = transcriber.transcribe(source)
    repo.create(source, transcript)
    return {
        "project_id": project_id,
        "transcript": [
            {"text": w.text, "start": w.start, "end": w.end} for w in transcript.words
        ],
    }


@app.post("/projects/{project_id}/edits/preview")
def preview_edit(project_id: str, req: EditRequest) -> dict:
    candidate = _build_candidate(project_id, req)
    return _candidate_dict(candidate)


@app.post("/projects/{project_id}/edits")
def approve_edit(project_id: str, req: EditRequest) -> dict:
    # KNOWN LIMITATION (deferred to the real-adapters plan): approval re-runs the
    # pipeline rather than persisting the exact candidate the user previewed. This is
    # safe only because the mock adapters are deterministic. With non-deterministic
    # real adapters, the committed candidate could differ from the previewed one and
    # must instead be persisted at preview time and looked up here by id.
    candidate = _build_candidate(project_id, req)
    if not candidate.continuity.passed:
        raise HTTPException(status_code=422, detail="continuity check failed")
    edit_id = f"e{len(repo.list_edits(project_id)) + 1}"
    repo.append_edit(project_id, ApprovedEdit(
        edit_id=edit_id,
        plan=candidate.plan,
        audio_ref=candidate.audio_ref,
        frames_ref=candidate.frames_ref,
    ))
    return {"edit_id": edit_id, "continuity": _continuity_dict(candidate.continuity)}


@app.post("/projects/{project_id}/export")
def export_project(project_id: str) -> dict:
    record = repo.get(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail="project not found")
    manifest = render(record.source, repo.list_edits(project_id))
    return {
        "segments": [
            {"start": s.start, "end": s.end, "kind": s.kind, "ref": s.ref}
            for s in manifest.segments
        ],
    }
