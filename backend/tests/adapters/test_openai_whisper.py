"""Transcription adapter tests. No network, no spend.

The parsing tests run against `tests/fixtures/whisper-verbose-json.json`, a
response genuinely recorded from whisper-1 — so the shape being parsed is the
shape the vendor actually sends, including its oddities.
"""
import json
from pathlib import Path

import pytest

from app.adapters.openai_whisper import (
    WhisperTranscriptionAdapter, TranscriptionError, to_transcript, MODEL,
)
from app.media import ffmpeg
from tests.factories import make_source

FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "whisper-verbose-json.json").read_text()
)


def test_model_is_the_one_that_supports_word_timestamps():
    # gpt-4o-transcribe rejects verbose_json, so it cannot return word timings.
    assert MODEL == "whisper-1"


def test_recorded_response_parses_into_ordered_words():
    transcript = to_transcript(FIXTURE)
    assert [w.text for w in transcript.words] == ["Get", "20", "off", "today", "only"]
    assert transcript.words[0].start == 0.0
    for earlier, later in zip(transcript.words, transcript.words[1:]):
        assert earlier.end <= later.start


def test_the_empty_word_whisper_emits_for_a_symbol_is_dropped():
    # Whisper returns '' for the stripped '%' in "20%", holding a real time
    # slot. A blank timeline cell would be worse than a gap.
    assert any(w["word"] == "" for w in FIXTURE["words"]), "fixture lost its empty word"
    assert all(w.text for w in to_transcript(FIXTURE).words)


def test_dropping_a_word_leaves_a_gap_rather_than_shifting_timings():
    words = to_transcript(FIXTURE).words
    twenty = next(w for w in words if w.text == "20")
    off = next(w for w in words if w.text == "off")
    assert twenty.end < off.start  # the dropped '%' span is simply absent


@pytest.mark.parametrize("payload", [{}, {"words": None}, {"words": []}])
def test_a_response_without_words_yields_an_empty_transcript(payload):
    assert to_transcript(payload).words == ()


def test_malformed_word_entries_are_skipped_not_fatal():
    payload = {"words": [
        {"word": "ok", "start": 0.0, "end": 0.5},
        {"word": "bad", "start": "x", "end": 1.0},
        {"word": "missing-end", "start": 1.0},
    ]}
    assert [w.text for w in to_transcript(payload).words] == ["ok"]


def test_transcribe_extracts_audio_and_parses_the_reply(tmp_path):
    pytest.importorskip("httpx")
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")

    # A real video with a real audio track for the adapter to extract from.
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 1.0)
    audio, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 1.0)
    muxed = tmp_path / "with-audio.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(muxed),
    ])

    seen = {}

    def fake_post(path, api_key, timeout):
        # The adapter must hand over a real, non-empty WAV it extracted itself.
        seen["bytes"] = path.read_bytes()
        seen["suffix"] = path.suffix
        seen["key"] = api_key
        return FIXTURE

    adapter = WhisperTranscriptionAdapter("sk-test", post=fake_post)
    transcript = adapter.transcribe(make_source(media=_artifact_for(muxed)))

    assert [w.text for w in transcript.words][:2] == ["Get", "20"]
    assert seen["suffix"] == ".wav"
    assert len(seen["bytes"]) > 1000
    assert seen["key"] == "sk-test"


def test_a_source_without_audio_fails_with_a_clear_error(tmp_path):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")
    silent, _ = ffmpeg.generate_solid_video(tmp_path / "silent.mp4", 1.0)

    adapter = WhisperTranscriptionAdapter("sk-test", post=lambda *a: FIXTURE)
    with pytest.raises(TranscriptionError, match="extract audio"):
        adapter.transcribe(make_source(media=_artifact_for(silent)))


def test_vendor_failures_surface_as_transcription_errors(tmp_path):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 1.0)
    audio, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 1.0)
    muxed = tmp_path / "m.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(muxed),
    ])

    def boom(path, api_key, timeout):
        raise TranscriptionError("OpenAI transcription failed (429): rate limited")

    adapter = WhisperTranscriptionAdapter("sk-test", post=boom)
    with pytest.raises(TranscriptionError, match="429"):
        adapter.transcribe(make_source(media=_artifact_for(muxed)))


def _artifact_for(path: Path):
    from app.domain.models import MediaArtifact
    return MediaArtifact(
        kind="video", sha256="0" * 64, path=str(path), duration=1.0, container="mp4",
    )
