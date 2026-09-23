"""Clean reference audio of the speaker, for voice cloning (Phase 4b).

Built now so 4b is an adapter change only. The reference is every transcribed
word *outside* the selection, joined: the words being replaced are exactly the
ones a clone must not learn from, and silence between words is dead weight.
"""
from __future__ import annotations

import tempfile
import wave
from pathlib import Path

from app.domain.models import MediaArtifact, Selection, Source, Transcript
from app.media import ffmpeg
from app.store.artifacts import ArtifactStore

# Placeholder floor. ElevenLabs asks for roughly a minute for an instant clone;
# 4b pins the real number against the vendor.
MIN_REFERENCE_SECONDS = 10.0

# Words closer than this are cut as one run, so natural joins between words
# survive instead of being chopped at every boundary.
_JOIN_GAP = 0.25


def speech_runs(transcript: Transcript, exclude: Selection | None) -> list[tuple[float, float]]:
    """Spans of speech to cut, never crossing into `exclude`."""
    runs: list[tuple[float, float]] = []
    for word in transcript.words:
        if exclude and word.end > exclude.start and word.start < exclude.end:
            continue  # overlaps the selection
        if runs and word.start - runs[-1][1] <= _JOIN_GAP and not (
            exclude and runs[-1][1] <= exclude.start < word.start
        ):
            runs[-1] = (runs[-1][0], word.end)
        else:
            runs.append((word.start, word.end))
    return runs


def extract_reference_audio(
    source: Source,
    transcript: Transcript,
    store: ArtifactStore,
    *,
    exclude: Selection | None = None,
    min_seconds: float = MIN_REFERENCE_SECONDS,
) -> MediaArtifact | None:
    """Store the speaker's speech outside `exclude` as one WAV, or None if too short."""
    runs = speech_runs(transcript, exclude)
    if sum(end - start for start, end in runs) < min_seconds:
        return None

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        out_path = tmp_dir / "reference.wav"
        with wave.open(str(out_path), "wb") as out:
            for index, (start, end) in enumerate(runs):
                piece, _ = ffmpeg.extract_segment(
                    source.media.path, tmp_dir / f"run{index}.wav", start, end,
                )
                with wave.open(str(piece), "rb") as chunk:
                    if index == 0:
                        out.setparams(chunk.getparams())
                    out.writeframes(chunk.readframes(chunk.getnframes()))
        duration = ffmpeg.duration_of(out_path)
        return store.put_file(
            source.project_id, out_path, kind="audio", container="wav", duration=duration,
        )
