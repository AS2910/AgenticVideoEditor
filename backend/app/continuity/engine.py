from dataclasses import dataclass
from app.domain.models import EditPlan, ContinuityReport

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
    def __init__(self, thresholds: ContinuityThresholds | None = None) -> None:
        self.thresholds = thresholds or ContinuityThresholds()

    def evaluate(self, plan: EditPlan, audio_ref: str, frames_ref: str) -> ContinuityReport:
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
