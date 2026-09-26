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

    adapter = WhisperTranscriptionAdapter("sk-test", post=fake_post, post_diarize=NO_TURNS)
    transcript = adapter.transcribe(make_source(media=_artifact_for(muxed)))

    assert [w.text for w in transcript.words][:2] == ["Get", "20"]
    assert seen["suffix"] == ".wav"
    assert len(seen["bytes"]) > 1000
    assert seen["key"] == "sk-test"


def test_a_source_without_audio_fails_with_a_clear_error(tmp_path):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")
    silent, _ = ffmpeg.generate_solid_video(tmp_path / "silent.mp4", 1.0)

    adapter = WhisperTranscriptionAdapter("sk-test", post=lambda *a: FIXTURE, post_diarize=NO_TURNS)
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

    adapter = WhisperTranscriptionAdapter("sk-test", post=boom, post_diarize=NO_TURNS)
    with pytest.raises(TranscriptionError, match="429"):
        adapter.transcribe(make_source(media=_artifact_for(muxed)))


def NO_TURNS(path, api_key, timeout):
    return {"segments": []}


def _muxed(tmp_path):
    video, _ = ffmpeg.generate_solid_video(tmp_path / "v.mp4", 1.0)
    audio, _ = ffmpeg.generate_silence(tmp_path / "a.wav", 1.0)
    muxed = tmp_path / "m.mp4"
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-i", str(video), "-i", str(audio),
        "-c:v", "copy", "-c:a", "aac", "-shortest", str(muxed),
    ])
    return muxed


# --- Phase 11: speakers ---------------------------------------------------------

TWO_SPEAKERS = {
    "words": [
        {"word": "Hi", "start": 5.2, "end": 5.5}, {"word": "there", "start": 5.5, "end": 6.9},
        {"word": "Sure", "start": 9.38, "end": 9.6}, {"word": "sir", "start": 9.6, "end": 9.88},
        {"word": "Done", "start": 14.52, "end": 14.52},   # zero-length, as Whisper gives
    ],
    "segments": [
        {"text": " Hi there.", "start": 5.2, "end": 6.94},
        {"text": " Sure, sir.", "start": 9.38, "end": 9.88},
    ],
}
# Shaped like gpt-4o-transcribe-diarize's diarized_json, as seen in the spike.
TURNS = {"segments": [
    {"type": "transcript.text.segment", "id": "seg_0", "speaker": "A", "start": 5.5, "end": 6.9, "text": " Hi there."},
    {"type": "transcript.text.segment", "id": "seg_1", "speaker": "B", "start": 9.2, "end": 10.7, "text": " Sure, sir."},
    {"type": "transcript.text.segment", "id": "seg_2", "speaker": "B", "start": 14.15, "end": 14.5, "text": " Done,"},
]}


def test_words_and_statements_are_labelled_by_speaker(tmp_path):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")
    adapter = WhisperTranscriptionAdapter(
        "sk-test", post=lambda *a: TWO_SPEAKERS, post_diarize=lambda *a: TURNS,
    )
    t = adapter.transcribe(make_source(media=_artifact_for(_muxed(tmp_path))))
    assert [(w.text, w.speaker) for w in t.words] == [
        ("Hi", "A"), ("there", "A"), ("Sure", "B"), ("sir", "B"), ("Done", "B"),
    ]
    assert [s.speaker for s in t.statements] == ["A", "B"]


def test_a_failed_diarization_keeps_the_words(tmp_path):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")

    def down(path, api_key, timeout):
        raise TranscriptionError("OpenAI diarization failed (500)")

    adapter = WhisperTranscriptionAdapter("sk-test", post=lambda *a: TWO_SPEAKERS, post_diarize=down)
    t = adapter.transcribe(make_source(media=_artifact_for(_muxed(tmp_path))))
    assert len(t.words) == 5 and all(w.speaker is None for w in t.words)


def test_to_turns_skips_unusable_segments():
    from app.adapters.openai_whisper import to_turns
    assert to_turns({"segments": [
        {"speaker": "A", "start": 1.0, "end": 2.0}, {"speaker": "B", "start": 3.0, "end": 3.0},
        {"start": 4.0, "end": 5.0},
    ]}) == [("A", 1.0, 2.0)]


def _artifact_for(path: Path):
    from app.domain.models import MediaArtifact
    return MediaArtifact(
        kind="video", sha256="0" * 64, path=str(path), duration=1.0, container="mp4",
    )


def test_segments_become_statements_with_their_punctuation():
    from app.adapters.openai_whisper import to_transcript
    t = to_transcript({
        "words": [{"word": "Sure", "start": 9.38, "end": 9.6}, {"word": "sir", "start": 9.6, "end": 9.88}],
        "segments": [{"text": " Sure, sir.", "start": 9.38, "end": 9.88},
                     {"text": " ", "start": 10.0, "end": 10.2}],
    })
    assert [(s.text, s.start, s.end) for s in t.statements] == [("Sure, sir.", 9.38, 9.88)]
