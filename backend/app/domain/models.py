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
    filename: str
    duration: float  # seconds


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
class ContinuityReport:
    voice_match: float
    prosody: float
    audio_integration: float
    lip_sync: float
    passed: bool
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class EditCandidate:
    plan: EditPlan
    audio_ref: str
    frames_ref: str
    continuity: ContinuityReport


@dataclass(frozen=True)
class ApprovedEdit:
    edit_id: str
    plan: EditPlan
    audio_ref: str
    frames_ref: str
