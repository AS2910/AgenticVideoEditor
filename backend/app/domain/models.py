from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds
    end: float    # seconds


@dataclass(frozen=True)
class Transcript:
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Source:
    project_id: str
    filename: str            # the name the file was uploaded under, for display
    duration: float          # seconds, measured by ffprobe — never client-supplied
    media: "MediaArtifact"   # the immutable original, as stored


@dataclass(frozen=True)
class Selection:
    start: float
    end: float


@dataclass(frozen=True)
class EditPlan:
    selection: Selection
    new_text: str
    voice_profile_id: str


@dataclass(frozen=True)
class Consent:
    """The uploader's confirmation that they may edit and clone this speaker.

    Design spec §2 calls this non-negotiable, and §7 fixes the moment it binds:
    before any voice generation runs. Its presence *is* the grant — there is no
    revoked state, because a revoked consent should remove the project, not sit
    in the record as a flag someone might forget to check.
    """
    granted_at: str  # ISO-8601 UTC


@dataclass(frozen=True)
class MediaArtifact:
    """A real media file on disk, addressed by the hash of its own bytes.

    Replaces the opaque `audio://` / `frames://` strings the mock slice used.
    Identical bytes always produce an identical artifact, so generation is
    still deduplicated and still comparable in tests.
    """
    kind: str        # "audio" | "video"
    sha256: str      # content address; also the on-disk basename
    path: str        # absolute path
    duration: float  # seconds
    container: str   # "wav" | "mp4"


@dataclass(frozen=True)
class ContinuityReport:
    # A score is None when it cannot be measured yet (no clone, no real
    # lip-sync) — never a made-up number standing in for one.
    voice_match: float | None
    prosody: float | None
    audio_integration: float | None
    lip_sync: float | None
    passed: bool
    warnings: tuple[str, ...]
    # Which of the four scores were measured from the media. The rest are
    # either None or simulated by the mock engine.
    measured: tuple[str, ...] = ()


@dataclass(frozen=True)
class EditCandidate:
    candidate_id: str
    plan: EditPlan
    audio: MediaArtifact
    frames: MediaArtifact
    continuity: ContinuityReport


@dataclass(frozen=True)
class ApprovedEdit:
    edit_id: str
    candidate_id: str  # the exact candidate the user previewed
    plan: EditPlan
    audio: MediaArtifact
    frames: MediaArtifact
