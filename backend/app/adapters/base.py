import hashlib
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator, Protocol

from app.domain.models import Source, Transcript, EditPlan, MediaArtifact


class VendorError(RuntimeError):
    """A generation vendor failed.

    Treated as possibly transient: the job runner retries these with backoff
    before surfacing an error (design spec §8). Raise something else for
    failures that retrying cannot fix.
    """


class TranscriptionAdapter(Protocol):
    def transcribe(self, source: Source) -> Transcript: ...

    def diarize(self, source: Source) -> list[tuple[str, float, float]]:
        """Speaker turns (label, start, end), for projects transcribed before
        speakers were detected."""
        ...


class VoiceAdapter(Protocol):
    # Whose voice this produces: "mock" (a tone), "stock" (a real voice that is
    # not the speaker's), or "clone" (the speaker's). The pipeline labels
    # candidates by it, so a stock voice is never passed off as the speaker.
    identity: str

    def cost_of(self, plan: EditPlan) -> int:
        """Budget units one attempt at `plan` will charge. 0 for free adapters."""
        ...

    # The voice used when an edit doesn't pick one, and those it can pick from:
    # dicts of voice_id, name, description, gender, accent, age.
    default_voice: str

    def voices(self) -> list[dict]: ...

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


# ── Launch item 4: idempotency keys on paid vendor calls ─────────────────────
# A retried call carries the same key as its first attempt, so a vendor that
# honours keys (Stripe, Resend, OpenAI's newer APIs) does the work once. The
# key is the retry scope (one per logical call, set by `with_retries`) plus
# what is being asked; a call outside any scope gets a fresh key.

_idempotency_scope: ContextVar[str | None] = ContextVar("idempotency_scope", default=None)


@contextmanager
def idempotency_scope() -> Iterator[str]:
    """Every vendor call inside shares one scope (kept if one is already open)."""
    current = _idempotency_scope.get()
    if current is not None:
        yield current
        return
    token = _idempotency_scope.set(uuid.uuid4().hex)
    try:
        yield _idempotency_scope.get()  # type: ignore[misc]
    finally:
        _idempotency_scope.reset(token)


def idempotency_header(*parts: object) -> dict[str, str]:
    scope = _idempotency_scope.get() or uuid.uuid4().hex
    digest = hashlib.sha256("|".join([scope, *(str(p) for p in parts)]).encode()).hexdigest()[:40]
    return {"Idempotency-Key": f"ave-{digest}"}
