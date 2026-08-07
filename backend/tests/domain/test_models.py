import dataclasses

import pytest

from app.domain.models import (
    Word, Transcript, Source, Selection, EditPlan,
    ContinuityReport, EditCandidate, ApprovedEdit,
)


def test_models_construct_and_are_frozen():
    word = Word(text="hello", start=0.0, end=0.5)
    transcript = Transcript(words=(word,))
    source = Source(project_id="p1", filename="ad.mp4", duration=30.0)
    selection = Selection(start=0.0, end=0.5)
    plan = EditPlan(selection=selection, new_text="hi", voice_profile_id="speaker-1")
    report = ContinuityReport(
        voice_match=0.9, prosody=0.9, audio_integration=0.9,
        lip_sync=0.9, passed=True, warnings=(),
    )
    candidate = EditCandidate(
        plan=plan, audio_ref="audio://x", frames_ref="frames://x", continuity=report,
    )
    approved = ApprovedEdit(
        edit_id="e1", plan=plan, audio_ref="audio://x", frames_ref="frames://x",
    )

    assert transcript.words[0].text == "hello"
    assert candidate.continuity.passed is True
    assert approved.edit_id == "e1"

    with pytest.raises(dataclasses.FrozenInstanceError):
        source.duration = 10.0
