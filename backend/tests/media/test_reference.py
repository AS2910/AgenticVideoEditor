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
