import hashlib
from app.domain.models import Source, Transcript, Word, EditPlan

# A fixed canned transcript so the whole pipeline is deterministic offline.
_CANNED_WORDS = (
    Word("Get", 0.0, 0.4),
    Word("20%", 0.4, 0.9),
    Word("off", 0.9, 1.3),
    Word("today", 1.3, 1.8),
    Word("only", 1.8, 2.3),
)


def _digest(*parts: str) -> str:
    return hashlib.sha1("|".join(parts).encode()).hexdigest()[:12]


class MockTranscriptionAdapter:
    def transcribe(self, source: Source) -> Transcript:
        return Transcript(words=_CANNED_WORDS)


class MockVoiceAdapter:
    def synthesize(self, text: str, voice_profile_id: str) -> str:
        return f"audio://{voice_profile_id}/{_digest(voice_profile_id, text)}"


class MockLipSyncAdapter:
    def sync(self, source: Source, plan: EditPlan, audio_ref: str) -> str:
        ref = _digest(source.project_id, plan.new_text, audio_ref)
        return f"frames://{source.project_id}/{ref}"
