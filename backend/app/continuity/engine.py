from dataclasses import dataclass
from app.domain.models import (
    EditPlan, ContinuityReport, MediaArtifact, Source, Transcript,
)


@dataclass(frozen=True)
class Assessment:
    """A continuity verdict, plus the audio it applies to.

    The audio can differ from what was generated: an engine that auto-corrects
    (level, room tone) hands back the corrected artifact, and that is what the
    candidate must carry.
    """
    report: ContinuityReport
    audio: MediaArtifact

# Metric keys, in a fixed order, paired with a human label for warnings.
_METRICS = (
    ("voice_match", "voice identity"),
    ("prosody", "prosody & energy"),
    ("audio_integration", "audio integration"),
    ("lip_sync", "lip-sync accuracy"),
)


@dataclass(frozen=True)
class ContinuityThresholds:
    voice_match: float = 0.8
    prosody: float = 0.8
    audio_integration: float = 0.8
    lip_sync: float = 0.8


def _mock_probe(plan: EditPlan) -> dict[str, float]:
    """Deterministic stand-in for real signal extraction.

    Replaced later by real audio/lip-sync analysis. For now a known voice
    profile scores high; an unknown one fails voice identity so the failure
    path is exercised end-to-end.
    """
    metrics = {
        "voice_match": 0.95,
        "prosody": 0.92,
        "audio_integration": 0.97,
        "lip_sync": 0.94,
    }
    if plan.voice_profile_id == "unknown":
        metrics["voice_match"] = 0.40
    return metrics


class ContinuityEngine:
    """The mock engine: simulated scores, used when the voice is a mock too.

    Measuring a sine tone's "prosody" would be meaningless, so offline and
    dry-run keep this — and the report says none of it was measured.
    """

    measures: tuple[str, ...] = ()

    def __init__(self, thresholds: ContinuityThresholds | None = None) -> None:
        self.thresholds = thresholds or ContinuityThresholds()

    def assess(
        self, source: Source, transcript: Transcript | None, plan: EditPlan,
        audio: MediaArtifact,
    ) -> Assessment:
        return Assessment(self.evaluate(plan, audio), audio)

    def evaluate(
        self, plan: EditPlan, audio: MediaArtifact, frames: MediaArtifact | None = None,
    ) -> ContinuityReport:
        # Phase 6 replaces `_mock_probe` with real signal analysis over these
        # two artifacts — speaker embeddings, F0/energy, LUFS, AV-sync.
        metrics = _mock_probe(plan)
        warnings: list[str] = []
        for key, label in _METRICS:
            if metrics[key] < getattr(self.thresholds, key):
                warnings.append(f"Low {label} ({metrics[key]:.2f})")
        return ContinuityReport(
            voice_match=metrics["voice_match"],
            prosody=metrics["prosody"],
            audio_integration=metrics["audio_integration"],
            lip_sync=metrics["lip_sync"],
            passed=len(warnings) == 0,
            warnings=tuple(warnings),
        )
