"""Deterministic mock adapters that produce *real, decodable media files*.

These stand in for paid vendors (Phases 2/4/5) while keeping the suite offline
and free. The media is fake — a tone, a flat colour — but everything around it
is real: real WAV/MP4 containers, real durations matching the selected span,
real bytes in the content-addressed store.

Both generators are keyed to their inputs, so different text or different audio
yields different media. Plain silence would collapse every candidate on a span
onto one content address and make the artifacts useless for telling candidates
apart.
"""
from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from app.domain.models import Source, Statement, Transcript, Word, EditPlan, MediaArtifact
from app.media import ffmpeg
from app.store.artifacts import ArtifactStore

# A fixed canned transcript so the whole pipeline is deterministic offline.
# Replaced by real Whisper output in Phase 2.
_CANNED_WORDS = (
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
    Word("only", 1.8, 2.3),
)

_MIN_DURATION = 0.05  # ffmpeg needs a non-degenerate span to encode


def _digest(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def _span(plan: EditPlan) -> float:
    return max(plan.selection.end - plan.selection.start, _MIN_DURATION)


class MockTranscriptionAdapter:
    def transcribe(self, source: Source) -> Transcript:
        return Transcript(
            words=_CANNED_WORDS, statements=(Statement("Get 20% off today only.", 0.0, 2.3),),
        )


class MockVoiceAdapter:
    """Real WAV, as long as the selected span, pitched by the text being spoken."""

    identity = "mock"

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def cost_of(self, plan: EditPlan) -> int:
        return 0

    default_voice = "mock"

    def voices(self) -> list[dict]:
        return [{"voice_id": "mock", "name": "Test tone", "description": "Offline stand-in",
                 "gender": None, "accent": None, "age": None}]

    def synthesize(
        self, source: Source, plan: EditPlan, transcript: Transcript | None = None,
    ) -> MediaArtifact:
        seed = _digest(plan.voice_profile_id, plan.new_text)
        frequency = 200 + int(seed[:4], 16) % 600  # 200–800 Hz, stable per input
        with tempfile.TemporaryDirectory() as tmp:
            path, duration = ffmpeg.generate_tone(
                Path(tmp) / "voice.wav", _span(plan), frequency,
            )
            return self._store.put_file(
                source.project_id, path, kind="audio", container="wav", duration=duration,
            )


class MockLipSyncAdapter:
    """Real MP4, as long as the selected span, tinted by the audio it syncs to."""

    def __init__(self, store: ArtifactStore) -> None:
        self._store = store

    def sync(self, source: Source, plan: EditPlan, audio: MediaArtifact) -> MediaArtifact:
        seed = _digest(source.project_id, plan.new_text, audio.sha256)
        colour = f"0x{seed[:6]}"  # stable per (project, text, audio)
        with tempfile.TemporaryDirectory() as tmp:
            path, duration = ffmpeg.generate_solid_video(
                Path(tmp) / "frames.mp4", _span(plan), colour,
            )
            return self._store.put_file(
                source.project_id, path, kind="video", container="mp4", duration=duration,
            )
