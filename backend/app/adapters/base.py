from typing import Protocol
from app.domain.models import Source, Transcript, EditPlan


class TranscriptionAdapter(Protocol):
    def transcribe(self, source: Source) -> Transcript: ...


class VoiceAdapter(Protocol):
    def synthesize(self, text: str, voice_profile_id: str) -> str:
        """Return an opaque reference to generated audio."""
        ...


class LipSyncAdapter(Protocol):
    def sync(self, source: Source, plan: EditPlan, audio_ref: str) -> str:
        """Return an opaque reference to the re-synced frames."""
        ...
