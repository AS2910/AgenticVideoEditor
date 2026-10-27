"""Run 5 item 7 in the pipeline: the first take follows the speaker, a refused
take is retaken steered back, the pick ranks delivery, a line whose words do
not change is the original passed through the new voice, and a roomed take
says so on its plan."""
from dataclasses import replace

import pytest

from app.adapters.base import VendorError
from app.adapters.mock import MockLipSyncAdapter, MockVoiceAdapter
from app.continuity import prosody
from app.continuity.engine import Assessment
from app.domain.models import ContinuityReport, EditPlan, Selection, Transcript, Word
from app.media import ffmpeg
from app.orchestrator.pipeline import _score, run_edit
from tests.factories import make_source

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")

SOURCE = make_source()
SELECTION = Selection(0.4, 1.3)
WORDS = Transcript(words=(Word("Get", 0.0, 0.4), Word("twenty", 0.4, 0.8), Word("off", 0.85, 1.3)))


class Voice(MockVoiceAdapter):
    """A 'real' voice that records the settings each take was asked for."""
    identity = "stock"

    def __init__(self, store, converts=True, fail=None):
        super().__init__(store)
        self.sent: list[dict | None] = []
        self.converts, self.fail, self.spoken_like = converts, fail, 0

    def synthesize(self, source, plan, transcript=None):
        self.sent.append(plan.voice_settings)
        return super().synthesize(source, replace(plan, new_text=f"{plan.new_text}#{len(self.sent)}"), transcript)

    def speak_like(self, source, plan, transcript=None):
        self.spoken_like += 1
        if self.fail:
            raise self.fail
        return super().synthesize(source, replace(plan, new_text="like the original"), transcript) if self.converts else None


def report(passed=True, warnings=(), distance=None):
    return ContinuityReport(None, 0.9, 0.9, None, passed, tuple(warnings), measured=("prosody",),
                            prosody_distance=distance)


class Engine:
    """Scripted verdicts per take; a first-take reference of its own."""

    def __init__(self, verdicts, settings=None, roomed=False):
        self.verdicts, self.settings, self.roomed, self.plans = list(verdicts), settings, roomed, []

    def reference(self, source, transcript, plan):
        return self.settings

    def assess(self, source, transcript, plan, audio):
        self.plans.append(plan)
        rep, delivery = self.verdicts.pop(0)
        return Assessment(rep, audio, roomed=self.roomed, delivery=delivery)


def run(store, voice, engine, plan=None, regenerations=2):
    plan = plan or EditPlan(SELECTION, "thirty off", "v")
    return run_edit("c1", plan, SOURCE, voice, MockLipSyncAdapter(store), engine,
                    transcript=WORDS, max_regenerations=regenerations)


FAST = prosody.Verdict(1.4, ("Said faster than the lines around it (6.0 syllables a second; they run 4.0 to 5.0).",),
                       faster=1.3)


def test_the_first_take_is_asked_in_the_speakers_delivery_and_the_plan_stays_as_asked(store):
    voice, engine = Voice(store), Engine([(report(), None)], settings={"stability": 0.35})
    candidate = run(store, voice, engine)
    assert voice.sent == [{"stability": 0.35}]
    assert candidate.plan.voice_settings is None          # what was asked is kept; the steer is a note
    assert engine.plans[0].voice_settings is None         # and assessed as asked, so it can be refused
    assert any(n.startswith("delivery matched to the speaker") for n in candidate.fit_notes)


def test_a_take_refused_for_its_delivery_is_retaken_steered_back(store):
    voice = Voice(store)
    engine = Engine([(report(False, FAST.outside, 1.4), FAST), (report(True, (), 0.3), None)])
    candidate = run(store, voice, engine)
    assert voice.sent[0] is None and voice.sent[1]["speed"] < 1.0
    assert candidate.continuity.passed and candidate.continuity.prosody_distance == 0.3


def test_a_directed_line_is_never_steered(store):
    voice = Voice(store)
    engine = Engine([(report(False, FAST.outside), FAST)] * 3, settings=None)
    run(store, voice, engine, plan=EditPlan(SELECTION, "thirty off", "v", delivery="more excited"))
    assert voice.sent == [None, None, None]


def test_the_pick_ranks_delivery_and_puts_a_refused_take_last():
    close, far = report(distance=0.2), report(distance=2.0)
    assert _score(close) > _score(far)
    refused = report(False, FAST.outside, 0.1)
    assert _score(refused) < _score(far)


def test_a_line_whose_words_stay_is_the_original_in_the_new_voice(store):
    voice, engine = Voice(store), Engine([(report(), None)])
    candidate = run(store, voice, engine, plan=EditPlan(SELECTION, "twenty off.", "v"))
    assert voice.spoken_like == 1 and voice.sent == []
    assert candidate.fit_notes == ("spoken from the original line's delivery",)


def test_changed_words_or_a_directed_line_are_synthesised(store):
    voice = Voice(store)
    run(store, voice, Engine([(report(), None)]))
    run(store, voice, Engine([(report(), None)]), plan=EditPlan(SELECTION, "twenty off", "v", delivery="calmer"))
    assert voice.spoken_like == 0 and len(voice.sent) == 2


def test_the_vendor_failing_to_carry_the_delivery_falls_back_to_the_words(store):
    voice = Voice(store, fail=VendorError("down"))
    candidate = run(store, voice, Engine([(report(), None)]), plan=EditPlan(SELECTION, "twenty off", "v"))
    assert voice.spoken_like == 1 and len(voice.sent) == 1
    assert any("Could not carry the original delivery" in w for w in candidate.continuity.warnings)


def test_a_take_put_in_the_room_says_so_on_its_plan(store):
    candidate = run(store, Voice(store), Engine([(report(), None)], roomed=True))
    assert candidate.plan.roomed is True
    plain = run(store, Voice(store), Engine([(report(), None)]))
    assert plain.plan.roomed is None


def test_a_mock_voice_is_never_steered_nor_spoken_like(store):
    voice = Voice(store)
    voice.identity = "mock"
    run(store, voice, Engine([(report(), None)], settings={"stability": 0.35}), plan=EditPlan(SELECTION, "twenty off", "v"))
    assert voice.sent == [None] and voice.spoken_like == 0
