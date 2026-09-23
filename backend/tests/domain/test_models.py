import dataclasses

import pytest

from app.domain.models import (
    Word, Transcript, Source, Selection, EditPlan,
    ContinuityReport, EditCandidate, ApprovedEdit, MediaArtifact,
)

AUDIO = MediaArtifact(
    kind="audio", sha256="a" * 64, path="/tmp/a.wav", duration=0.5, container="wav",
)
FRAMES = MediaArtifact(
    kind="video", sha256="f" * 64, path="/tmp/f.mp4", duration=0.5, container="mp4",
)


def test_models_construct_and_are_frozen():
    word = Word(text="hello", start=0.0, end=0.5)
    transcript = Transcript(words=(word,))
    source = Source(project_id="p1", filename="ad.mp4", duration=30.0, media=FRAMES)
    selection = Selection(start=0.0, end=0.5)
    plan = EditPlan(selection=selection, new_text="hi", voice_profile_id="speaker-1")
    report = ContinuityReport(
        voice_match=0.9, prosody=0.9, audio_integration=0.9,
        lip_sync=0.9, passed=True, warnings=(),
    )
    candidate = EditCandidate(
        candidate_id="c1", plan=plan, audio=AUDIO, frames=FRAMES, continuity=report,
    )
    approved = ApprovedEdit(
        edit_id="e1", candidate_id="c1", plan=plan, audio=AUDIO, frames=FRAMES,
    )

    assert transcript.words[0].text == "hello"
    assert candidate.continuity.passed is True
    assert approved.edit_id == "e1"
    # An approved edit points back at the exact candidate that was previewed.
    assert approved.candidate_id == candidate.candidate_id
    assert approved.frames.sha256 == FRAMES.sha256

    with pytest.raises(dataclasses.FrozenInstanceError):
        source.duration = 10.0
