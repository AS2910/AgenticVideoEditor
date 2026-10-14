"""Which voice speaks a line, and making the speaker's own (Phase 15a). No network."""
from pathlib import Path

import pytest

from app.adapters.base import VendorError
from app.domain.models import MediaArtifact, Transcript, Word
from app.errors import NonRetryableError
from app.orchestrator.clones import CloneService
from app.store.repository import ProjectRepository
from tests.factories import make_source

STOCK = "S" * 20
PICKED = "P" * 20
CLONE = "C" * 20

# Speaker A speaks 12 s, speaker B 3 s.
WORDS = tuple(Word(f"a{i}", i, i + 0.9, "A") for i in range(12)) + \
        tuple(Word(f"b{i}", 12 + i, 12 + i + 0.9, "B") for i in range(3))
TRANSCRIPT = Transcript(words=WORDS)


class FakeVoice:
    can_clone = True

    def __init__(self, fail: Exception | None = None):
        self.fail, self.made, self.deleted, self.registered = fail, [], [], []

    def create_clone(self, name, reference):
        if self.fail:
            raise self.fail
        self.made.append((name, Path(reference)))
        return CLONE

    def delete_clone(self, voice_id):
        if self.fail:
            raise self.fail
        self.deleted.append(voice_id)

    def register_clone(self, voice_id):
        self.registered.append(voice_id)


def fake_extract(source, transcript, store, *, speaker=None, min_seconds=10.0, **_):
    return MediaArtifact("audio", "r" * 64, f"/tmp/ref-{speaker}.wav", 12.0, "wav")


@pytest.fixture()
def setup(store):
    repo = ProjectRepository()
    pid = repo.next_id()
    source = make_source(project_id=pid, duration=15.0)
    repo.create(source, TRANSCRIPT)

    def service(voice=None, **kw):
        voice = voice or FakeVoice()
        kw.setdefault("extract", fake_extract)
        return CloneService(repo, store, voice, **kw), voice

    return repo, pid, source, service


def test_a_speaker_with_enough_speech_is_cloned_once_and_reused(setup):
    repo, pid, source, service = setup
    svc, voice = service()
    first = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert (first.voice_id, first.cloned, first.notes) == (CLONE, True, ())
    assert repo.clones(pid) == {"A": CLONE}
    assert voice.made[0][0] == f"voltage-{pid}-A"

    again = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert again.voice_id == CLONE and again.cloned
    assert len(voice.made) == 1                       # never a second clone for the same speaker
    assert voice.registered                            # the adapter is told it is a clone


def test_a_clone_made_in_an_earlier_run_is_found_in_the_store(setup):
    repo, pid, source, service = setup
    repo.set_clone(pid, "A", CLONE)
    svc, voice = service()
    assert svc.resolve(pid, source, TRANSCRIPT, "A", STOCK).voice_id == CLONE
    assert voice.made == [] and voice.registered == [CLONE]


def test_a_voice_picked_on_purpose_beats_the_clone(setup):
    repo, pid, source, service = setup
    repo.set_speaker(pid, "A", voice_id=PICKED)
    svc, voice = service()
    choice = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert (choice.voice_id, choice.cloned) == (PICKED, False)
    assert voice.made == []


def test_too_little_speech_is_stock_with_the_reason(setup):
    repo, pid, source, service = setup
    svc, voice = service()
    choice = svc.resolve(pid, source, TRANSCRIPT, "B", STOCK)
    assert choice.voice_id == STOCK and not choice.cloned
    assert "only 2.9 s" in choice.notes[0] and "10 s needed" in choice.notes[0]
    assert voice.made == []


def test_cloning_switched_off_or_unsupported_leaves_the_requested_voice(setup):
    repo, pid, source, service = setup
    off, voice = service(enabled=False)
    assert off.resolve(pid, source, TRANSCRIPT, "A", STOCK).voice_id == STOCK
    plain = FakeVoice()
    plain.can_clone = False
    svc, _ = service(voice=plain)
    assert svc.resolve(pid, source, TRANSCRIPT, "A", STOCK) == svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert svc.resolve(pid, source, TRANSCRIPT, "A", STOCK).notes == ()


def test_a_refusal_falls_back_to_stock_and_is_not_retried_every_line(setup):
    repo, pid, source, service = setup
    refusing = FakeVoice(fail=NonRetryableError("The ElevenLabs key is missing the voices_write permission."))
    calls = []
    refusing.create_clone = lambda *a: (calls.append(a), (_ for _ in ()).throw(NonRetryableError("no slot")))[1]
    svc, _ = service(voice=refusing)
    first = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    second = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert first.voice_id == second.voice_id == STOCK
    assert "could not clone" in first.notes[0] and "no slot" in first.notes[0]
    assert len(calls) == 1 and repo.clones(pid) == {}


def test_a_vendor_outage_falls_back_but_the_next_line_tries_again(setup):
    repo, pid, source, service = setup
    voice = FakeVoice(fail=VendorError("down"))
    svc, _ = service(voice=voice)
    out = svc.resolve(pid, source, TRANSCRIPT, "A", STOCK)
    assert out.voice_id == STOCK and "try again" in out.notes[0]
    voice.fail = None
    assert svc.resolve(pid, source, TRANSCRIPT, "A", STOCK).voice_id == CLONE


def test_a_clip_with_no_speakers_is_cloned_under_the_whole_clip(setup, store):
    repo = ProjectRepository()
    pid = repo.next_id()
    plain = Transcript(words=tuple(Word(f"w{i}", i, i + 0.9) for i in range(12)))
    source = make_source(project_id=pid, duration=12.0)
    repo.create(source, plain)
    svc = CloneService(repo, store, FakeVoice(), extract=fake_extract)
    assert svc.resolve(pid, source, plain, None, STOCK).voice_id == CLONE
    assert repo.clones(pid) == {ProjectRepository.WHOLE_CLIP: CLONE}


def test_purging_deletes_every_clone_and_forgets_it(setup):
    repo, pid, source, service = setup
    repo.set_clone(pid, "A", CLONE)
    svc, voice = service()
    assert svc.purge(pid) == []
    assert voice.deleted == [CLONE] and repo.clones(pid) == {}


def test_a_clone_that_cannot_be_deleted_is_counted_and_kept_to_try_again(setup):
    repo, pid, source, service = setup
    repo.set_clone(pid, "A", CLONE)
    svc, _ = service(voice=FakeVoice(fail=VendorError("down")))
    assert svc.purge(pid) == [CLONE]
    assert repo.clones(pid) == {"A": CLONE}
