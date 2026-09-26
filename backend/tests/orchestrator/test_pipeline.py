from pathlib import Path

import pytest

from app.domain.models import Selection, EditPlan
from tests.factories import make_source
from app.media import ffmpeg
from app.adapters.mock import MockVoiceAdapter, MockLipSyncAdapter
from app.continuity.engine import ContinuityEngine
from app.orchestrator.pipeline import run_edit

SOURCE = make_source()

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


def run(store, plan, candidate_id="c1"):
    return run_edit(
        candidate_id, plan, SOURCE,
        MockVoiceAdapter(store), MockLipSyncAdapter(store), ContinuityEngine(),
    )


def test_run_edit_produces_candidate_with_real_artifacts_and_report(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run(store, plan)

    assert candidate.candidate_id == "c1"
    assert candidate.plan == plan
    assert candidate.audio.kind == "audio" and Path(candidate.audio.path).is_file()
    assert candidate.frames.kind == "video" and Path(candidate.frames.path).is_file()
    assert candidate.continuity.passed is True


def test_run_edit_surfaces_failed_continuity(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "unknown")
    assert run(store, plan).continuity.passed is False


def test_audio_and_frames_cover_the_same_span(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    candidate = run(store, plan)
    assert candidate.audio.duration == pytest.approx(candidate.frames.duration, abs=0.05)


# --- Phase 4a: honest labelling, transcript context -------------------------

from app.domain.models import Transcript, Word  # noqa: E402
from app.orchestrator.pipeline import STOCK_VOICE_WARNING  # noqa: E402


class RecordingVoice(MockVoiceAdapter):
    """The mock voice, but claiming a given identity and recording its inputs."""

    def __init__(self, store, identity):
        super().__init__(store)
        self.identity = identity
        self.transcripts = []

    def synthesize(self, source, plan, transcript=None):
        self.transcripts.append(transcript)
        return super().synthesize(source, plan, transcript)


def run_with(store, voice, transcript=None):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1")
    return run_edit(
        "c1", plan, SOURCE, voice, MockLipSyncAdapter(store), ContinuityEngine(),
        transcript=transcript,
    )


def test_a_stock_voice_is_labelled_as_not_the_speaker(store):
    candidate = run_with(store, RecordingVoice(store, "stock"))
    assert STOCK_VOICE_WARNING in candidate.continuity.warnings
    # Still approvable, or 4a could never be exercised end to end.
    assert candidate.continuity.passed is True


def test_a_mock_voice_is_not_labelled(store):
    candidate = run_with(store, RecordingVoice(store, "mock"))
    assert STOCK_VOICE_WARNING not in candidate.continuity.warnings


def test_the_transcript_reaches_the_voice_for_context(store):
    transcript = Transcript(words=(Word("Get", 0.0, 0.4),))
    voice = RecordingVoice(store, "mock")
    run_with(store, voice, transcript)
    assert voice.transcripts == [transcript]


# --- Phase 6a: regenerate until continuity passes, within limits ------------

from app.budget import BudgetExceeded  # noqa: E402
from app.continuity.engine import Assessment  # noqa: E402
from app.domain.models import ContinuityReport  # noqa: E402
from app.media.ffmpeg import SpanMismatch  # noqa: E402


def verdict(prosody):
    return ContinuityReport(
        voice_match=None, prosody=prosody, audio_integration=1.0, lip_sync=None,
        passed=prosody >= 0.8, warnings=() if prosody >= 0.8 else ("Pitch is off.",),
        measured=("prosody", "audio_integration"),
    )


class ScriptedVoice(MockVoiceAdapter):
    """A 'real' voice whose successive takes are scripted: a prosody score per
    take, or an exception to raise instead."""

    identity = "stock"

    def __init__(self, store, takes):
        super().__init__(store)
        self.takes = list(takes)
        self.calls = 0
        self.scores: dict[str, float] = {}

    def synthesize(self, source, plan, transcript=None):
        take = self.takes[self.calls]
        self.calls += 1
        if isinstance(take, Exception):
            raise take
        audio = super().synthesize(source, EditPlan(plan.selection, f"{plan.new_text}#{self.calls}", "v"))
        self.scores[audio.sha256] = take
        return audio


class ScriptedContinuity:
    def __init__(self, voice):
        self.voice = voice

    def assess(self, source, transcript, plan, audio):
        return Assessment(verdict(self.voice.scores[audio.sha256]), audio)


class CountingLipSync(MockLipSyncAdapter):
    def __init__(self, store):
        super().__init__(store)
        self.synced = []

    def sync(self, source, plan, audio):
        self.synced.append(audio.sha256)
        return super().sync(source, plan, audio)


def regenerate(store, takes, max_regenerations=2):
    voice = ScriptedVoice(store, takes)
    lipsync = CountingLipSync(store)
    candidate = run_edit(
        "c1", EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1"), SOURCE,
        voice, lipsync, ScriptedContinuity(voice), max_regenerations=max_regenerations,
    )
    return candidate, voice, lipsync


def test_a_passing_first_take_is_not_regenerated(store):
    candidate, voice, _ = regenerate(store, [0.95])
    assert voice.calls == 1
    assert candidate.continuity.passed
    assert not any("Regenerated" in w for w in candidate.continuity.warnings)


def test_a_failing_take_is_regenerated_until_one_passes(store):
    candidate, voice, _ = regenerate(store, [0.5, 0.9])
    assert voice.calls == 2
    assert candidate.continuity.prosody == 0.9
    assert "Regenerated 1× to improve continuity." in candidate.continuity.warnings


def test_the_cap_holds_and_the_best_take_is_kept(store):
    candidate, voice, _ = regenerate(store, [0.5, 0.7, 0.6, 0.99], max_regenerations=2)
    assert voice.calls == 3                      # 1 + 2 regenerations, never the 4th
    assert candidate.continuity.prosody == 0.7   # the best of the three
    assert candidate.continuity.passed is False


def test_running_out_of_budget_keeps_the_best_so_far(store):
    candidate, voice, _ = regenerate(store, [0.5, BudgetExceeded(7, 3)])
    assert candidate.continuity.prosody == 0.5
    assert any("budget" in w for w in candidate.continuity.warnings)


def test_no_budget_for_the_first_take_is_still_an_error(store):
    with pytest.raises(BudgetExceeded):
        regenerate(store, [BudgetExceeded(7, 3)])


def test_a_retake_that_cannot_be_fitted_is_skipped(store):
    candidate, voice, _ = regenerate(store, [0.5, SpanMismatch(2.0, 0.9), 0.9])
    assert voice.calls == 3
    assert candidate.continuity.prosody == 0.9


def test_a_first_take_that_cannot_be_fitted_is_not_regenerated(store):
    # Phase 8: the user is asked how to place it, rather than paying for more
    # takes that may not fit either.
    with pytest.raises(SpanMismatch):
        regenerate(store, [SpanMismatch(2.0, 0.9), 0.9])


def test_lip_sync_runs_once_on_the_winning_audio(store):
    candidate, _, lipsync = regenerate(store, [0.5, 0.9])
    assert lipsync.synced == [candidate.audio.sha256]


def test_a_mock_voice_is_never_regenerated(store):
    # Deterministic: a second take would be byte-identical, so it is pointless.
    candidate = run_edit(
        "c1", EditPlan(Selection(0.4, 1.3), "30% off", "unknown"), SOURCE,
        MockVoiceAdapter(store), MockLipSyncAdapter(store), ContinuityEngine(),
        max_regenerations=2,
    )
    assert candidate.continuity.passed is False
    assert not any("Regenerated" in w for w in candidate.continuity.warnings)


# --- Phase 8: a line allowed to run past the selection ----------------------

class LongVoice(MockVoiceAdapter):
    """Speaks a 1.5 s line whatever the selection."""

    def synthesize(self, source, plan, transcript=None):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path, duration = ffmpeg.generate_tone(Path(tmp) / "v.wav", 1.5, 300)
            return self._store.put_file(source.project_id, path, kind="audio",
                                        container="wav", duration=duration)


def test_a_line_running_past_the_selection_grows_the_edit(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1", fit="start")
    candidate = run_edit("c1", plan, SOURCE, LongVoice(store), MockLipSyncAdapter(store), ContinuityEngine())
    assert candidate.plan.selection.start == 0.4
    assert candidate.plan.selection.end == pytest.approx(1.9, abs=0.02)


def test_an_insert_keeps_its_selection(store):
    plan = EditPlan(Selection(0.4, 1.3), "30% off", "speaker-1", mix="concatenate")
    candidate = run_edit("c1", plan, SOURCE, LongVoice(store), MockLipSyncAdapter(store), ContinuityEngine())
    assert candidate.plan.selection == Selection(0.4, 1.3)
