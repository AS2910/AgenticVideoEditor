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


# How a line that does not match the selection's length is placed in it.
#   None      — automatic: stretched at most 0.8–1.25×, else the user is asked
#   "start"   — at natural speed from the selection's start; a shorter line
#               leaves the rest to `mix`, a longer one runs past the end
#   "stretch" — slowed or sped up to fill the selection exactly, any amount
FITS = ("start", "stretch")

# How the line meets the original sound.
#   "replace"     — the selection's audio is replaced
#   "layer"       — the line plays over the selection's audio
#   "concatenate" — the selection plays as it was, then the video holds its
#                   last frame while the line plays; the video gets longer
MIXES = ("replace", "layer", "concatenate")


@dataclass(frozen=True)
class EditPlan:
    selection: Selection
    new_text: str
    voice_profile_id: str
    fit: str | None = None
    mix: str = "replace"


@dataclass(frozen=True)
class Intent:
    """What the user asked for, read from their words.

    `speak` carries the line to say; `unsupported` and `clarify` carry a reply
    for the chat instead. `mix` is None unless the request says how the line
    should meet the original sound.
    """
    action: str               # "speak" | "unsupported" | "clarify"
    new_text: str | None = None
    mix: str | None = None
    reply: str | None = None


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
    # Approved although continuity failed — the user chose to, for a trial.
    overridden: bool = False
