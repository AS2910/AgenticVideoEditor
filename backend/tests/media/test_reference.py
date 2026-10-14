"""Reference audio for voice cloning (consumed by Phase 4b). No network."""
import re
import subprocess

import pytest

from app.domain.models import MediaArtifact, Selection, Transcript, Word
from app.media import ffmpeg
from app.media.reference import extract_reference_audio
from tests.factories import make_source

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)

# Three "words" per second across 3 s; the middle second is the selection.
WORDS = Transcript(words=tuple(
    Word(f"w{i}", i / 3, i / 3 + 0.3) for i in range(9)
))
SELECTION = Selection(1.0, 2.0)


@pytest.fixture()
def loud_middle(tmp_path):
    """3 s of audio: silence, then a tone for [1, 2), then silence.

    The tone sits exactly under the selection, so any leak of the selected
    span into the reference shows up as signal.
    """
    path = tmp_path / "src.wav"
    subprocess.run([
        ffmpeg.FFMPEG, "-y", "-loglevel", "error", "-f", "lavfi", "-i",
        "aevalsrc=if(between(t\\,1\\,2)\\,sin(2*PI*440*t)\\,0):s=16000:d=3",
        "-c:a", "pcm_s16le", str(path),
    ], check=True)
    media = MediaArtifact("audio", "a" * 64, str(path), 3.0, "wav")
    return make_source(media=media, duration=3.0)


def max_volume(path) -> float:
    out = subprocess.run(
        [ffmpeg.FFMPEG, "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return float(re.search(r"max_volume: (-?[\d.]+|-inf) dB", out).group(1).replace("-inf", "-999"))


def test_reference_is_the_speech_outside_the_selection(store, loud_middle):
    artifact = extract_reference_audio(
        loud_middle, WORDS, store, exclude=SELECTION, min_seconds=0.5,
    )
    assert artifact is not None and artifact.kind == "audio"
    # Words 0-2 and 6-8. Neighbouring words are cut as one run, so each run
    # keeps its short inter-word gaps: 0.00-0.97 and 2.00-2.97.
    assert artifact.duration == pytest.approx(1.93, abs=0.05)


def test_nothing_from_inside_the_selection_leaks_in(store, loud_middle):
    artifact = extract_reference_audio(
        loud_middle, WORDS, store, exclude=SELECTION, min_seconds=0.5,
    )
    assert max_volume(artifact.path) < -60  # silence only; the tone stayed out


def test_too_little_speech_returns_none(store, loud_middle):
    assert extract_reference_audio(
        loud_middle, WORDS, store, exclude=SELECTION, min_seconds=5.0,
    ) is None


def test_without_an_exclusion_every_word_counts(store, loud_middle):
    artifact = extract_reference_audio(loud_middle, WORDS, store, min_seconds=0.5)
    assert artifact.duration == pytest.approx(2.97, abs=0.05)


def test_a_word_whisper_gave_no_length_is_not_a_run():
    # Whisper returns some words with start == end; a zero-length run would be
    # cut as an empty file and crash whatever reads it.
    from app.domain.models import Transcript, Word
    from app.media.reference import speech_runs
    words = Transcript(words=(Word("Done", 14.52, 14.52), Word("hello", 20.0, 20.4)))
    assert speech_runs(words, None) == [(20.0, 20.4)]


# --- per speaker (Phase 15a) -------------------------------------------------

TWO_VOICES = Transcript(words=tuple(
    Word(f"w{i}", i / 3, i / 3 + 0.3, "A" if i < 6 else "B") for i in range(9)
))


def test_a_speakers_reference_holds_only_their_own_words():
    from app.media.reference import speech_runs, speech_seconds
    a = speech_runs(TWO_VOICES, None, "A")
    b = speech_runs(TWO_VOICES, None, "B")
    assert a and b
    assert max(end for _, end in a) <= 2.0 <= min(start for start, _ in b)
    assert speech_seconds(TWO_VOICES, "A") > speech_seconds(TWO_VOICES, "B") > 0
    # Everyone together also bridges the join between the two voices.
    assert speech_seconds(TWO_VOICES, None) >= speech_seconds(TWO_VOICES, "A") + speech_seconds(TWO_VOICES, "B")


def test_a_clone_reference_is_none_when_the_speaker_says_too_little(loud_middle, store):
    assert extract_reference_audio(loud_middle, TWO_VOICES, store, speaker="B", min_seconds=5.0) is None
    ref = extract_reference_audio(loud_middle, TWO_VOICES, store, speaker="A", min_seconds=1.0)
    assert ref is not None and ref.duration >= 1.0
