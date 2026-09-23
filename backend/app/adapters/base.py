from typing import Protocol

from app.domain.models import Source, Transcript, EditPlan, MediaArtifact


class VendorError(RuntimeError):
    """A generation vendor failed.

    Treated as possibly transient: the job runner retries these with backoff
    before surfacing an error (design spec §8). Raise something else for
    failures that retrying cannot fix.
    """


class TranscriptionAdapter(Protocol):
    def transcribe(self, source: Source) -> Transcript: ...


class VoiceAdapter(Protocol):
    def synthesize(self, source: Source, plan: EditPlan) -> MediaArtifact:
        """Generate speech for `plan.new_text` and return the stored audio.

        Takes the whole plan rather than loose text so an implementation can use
        the selected span for duration and prosody matching, and `source` so the
        artifact lands under the right project.
        """
        ...


class LipSyncAdapter(Protocol):
    def sync(self, source: Source, plan: EditPlan, audio: MediaArtifact) -> MediaArtifact:
        """Re-sync the mouth to `audio` and return the stored frames."""
        ...
