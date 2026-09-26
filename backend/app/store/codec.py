"""Domain objects to and from JSON-able dicts, for the SQLite store (Phase 9a).

Explicit per type rather than generic reflection: the stored shape is a
contract with every database already on disk, so a field added to a model
must be added here on purpose — with a default for rows written before it.
"""
from __future__ import annotations

from dataclasses import asdict

from app.domain.models import (
    ApprovedEdit, ContinuityReport, EditCandidate, EditPlan, MediaArtifact, Selection,
    Source, Transcript, Word,
)

dump = asdict  # every model is a plain (nested) dataclass


def artifact(d: dict) -> MediaArtifact:
    return MediaArtifact(**d)


def source(d: dict) -> Source:
    return Source(
        project_id=d["project_id"], filename=d["filename"], duration=d["duration"],
        media=artifact(d["media"]),
    )


def transcript(d: dict) -> Transcript:
    return Transcript(words=tuple(Word(**w) for w in d["words"]))


def plan(d: dict) -> EditPlan:
    return EditPlan(
        selection=Selection(**d["selection"]), new_text=d["new_text"],
        voice_profile_id=d["voice_profile_id"], fit=d.get("fit"), mix=d.get("mix", "replace"),
    )


def report(d: dict) -> ContinuityReport:
    return ContinuityReport(
        voice_match=d["voice_match"], prosody=d["prosody"],
        audio_integration=d["audio_integration"], lip_sync=d["lip_sync"],
        passed=d["passed"], warnings=tuple(d["warnings"]), measured=tuple(d.get("measured", ())),
    )


def candidate(d: dict) -> EditCandidate:
    return EditCandidate(
        candidate_id=d["candidate_id"], plan=plan(d["plan"]), audio=artifact(d["audio"]),
        frames=artifact(d["frames"]), continuity=report(d["continuity"]),
    )


def edit(d: dict) -> ApprovedEdit:
    return ApprovedEdit(
        edit_id=d["edit_id"], candidate_id=d["candidate_id"], plan=plan(d["plan"]),
        audio=artifact(d["audio"]), frames=artifact(d["frames"]),
        overridden=d.get("overridden", False),
    )
