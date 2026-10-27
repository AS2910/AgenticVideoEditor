from dataclasses import dataclass


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconds
    end: float    # seconds
    speaker: str | None = None  # diarization label ("A", "B", …); None if unknown


@dataclass(frozen=True)
class Statement:
    """A sentence as spoken, with punctuation — what the transcript panel
    shows and edits. Whisper's segments; its words carry no punctuation."""
    text: str
    start: float
    end: float
    speaker: str | None = None


@dataclass(frozen=True)
class Transcript:
    words: tuple[Word, ...]
    statements: tuple[Statement, ...] = ()


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
#   "over"        — asked for by the UI for an added line: play it after the
#                   selection, over the picture that follows (the API turns it
#                   into "layer" over the pause there, or "concatenate" when
#                   there is no room); never stored on a plan
#   "remove"      — the selection's dialogue is taken out and the room's own
#                   sound left in its place
MIXES = ("replace", "layer", "concatenate", "over", "remove")

# How a line is said (UX-1): a short instruction the voice understands.
DELIVERIES = ("warmer", "more excited", "calmer", "slower", "firmer")


@dataclass(frozen=True)
class EditPlan:
    selection: Selection
    new_text: str
    voice_profile_id: str
    fit: str | None = None
    mix: str = "replace"
    delivery: str | None = None
    # Phase 16: the picture over the selection runs this many times slower
    # (1.08 = 8% slower) so the take fits at natural speech; None = as shot.
    flex: float | None = None
    # Phase 20b: how it is said, as the vendor's own settings (stability,
    # style, speed, similarity) chosen by Voltage from its direction; None =
    # whatever `delivery` maps to. `model` names the vendor model for this
    # take (expressive models take audio tags in the text); None = the default.
    voice_settings: dict | None = None
    model: str | None = None
    # 20c: how far the picture over this take may flex to fit it (1.0 = as
    # shot); None = the project's setting.
    flex_max: float | None = None
    # 2026-10-20: what an added line is in the mix, which sets its level
    # against the clip's own speech (app/render/mix.py): "voice" (words meant
    # to be understood), "bed" (music, a crowd, cheers, ambience: under the
    # words and ducking while they play) or "effect" (a sound at the speech's
    # level). None = voice. A line of the original speech is always a voice.
    role: str | None = None
    # The user's fine-tune on top of the role's level, in dB (-24 to +6).
    offset_db: float | None = None
    # Run 5 item 7: the take was put in the speaker's room when it was made
    # (EQ and reverb), so the render's stems path does not add them again.
    roomed: bool | None = None


ROLES = ("voice", "bed", "effect")
OFFSET_RANGE = (-24.0, 6.0)


def role_of(plan) -> str:
    """The line's role in the mix; anything not set is a voice."""
    role = getattr(plan, "role", None)
    return role if role in ROLES else "voice"


def role_from_level(level_db: float | None) -> tuple[str | None, float | None]:
    """A level from before roles (20g's fixed -12 dB background) as a role:
    -12 dB (anything under -9) was a background, so a bed; 0 or none a voice;
    anything else a voice with that level as its fine-tune."""
    if level_db is None or abs(level_db) < 0.05:
        return None, None
    if level_db <= -9.0:
        return "bed", None
    return "voice", round(max(OFFSET_RANGE[0], min(OFFSET_RANGE[1], level_db)), 1)


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
    # Mean opinion score of the take, 1-5 (Phase 15d); None when not measured.
    naturalness: float | None = None
    # Run 5 item 7: how far the take's delivery (pitch contour plus speaking
    # rate) is from the line it replaces, 0 = the same, 1 = just noticeable;
    # None when not measured. Lower is better, unlike the scores above.
    prosody_distance: float | None = None


@dataclass(frozen=True)
class EditCandidate:
    candidate_id: str
    plan: EditPlan
    audio: MediaArtifact
    frames: MediaArtifact
    continuity: ContinuityReport
    # What was done to make the take fit its slot, in words (Phase 14):
    # "nearest of 3 takes", "trimmed 120 ms of pauses", "speech at 1.08× speed".
    fit_notes: tuple[str, ...] = ()
    # The take's own words with their times, relative to the take's start
    # (P-3): from the vendor's alignment, remapped through the fit.
    words: tuple[Word, ...] = ()


@dataclass(frozen=True)
class ApprovedEdit:
    edit_id: str
    candidate_id: str  # the exact candidate the user previewed
    plan: EditPlan
    audio: MediaArtifact
    frames: MediaArtifact
    # Approved although continuity failed — the user chose to, for a trial.
    overridden: bool = False
    # Undone after approval (Phase 12 Revert). Kept, not deleted — edits only
    # ever append — but the render skips it and the transcript shows it undone.
    reverted: bool = False
    # The other half of a shifted line (UX-1c): the removal and the placing
    # elsewhere are two edits that are undone together.
    partner: str | None = None
