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
    # Whose voice this produces: "mock" (a tone), "stock" (a real voice that is
    # not the speaker's), or "clone" (the speaker's). The pipeline labels
    # candidates by it, so a stock voice is never passed off as the speaker.
    identity: str

    def cost_of(self, plan: EditPlan) -> int:
        """Budget units one attempt at `plan` will charge. 0 for free adapters."""
        ...

    def synthesize(
        self, source: Source, plan: EditPlan, transcript: Transcript | None = None,
    ) -> MediaArtifact:
        """Generate speech for `plan.new_text` and return the stored audio.

        Takes the whole plan rather than loose text so an implementation can use
        the selected span for duration and prosody matching, `source` so the
        artifact lands under the right project, and `transcript` so the words
        either side of the edit can condition its delivery.
        """
        ...


class LipSyncAdapter(Protocol):
    def sync(self, source: Source, plan: EditPlan, audio: MediaArtifact) -> MediaArtifact:
        """Re-sync the mouth to `audio` and return the stored frames."""
        ...
