"""Measured identity and naturalness of a take (Phase 15d), optional extra `measure`.

Two numbers, both from open models that run on this machine:
- **SIM-o** is the cosine similarity between speaker embeddings of the
  speaker's own speech and the take (WavLM speaker verification), mapped to
  [0, 1]. It answers "does this sound like them?".
- **Naturalness** is a UTMOS-style mean opinion score (1-5) of the take alone.
  It answers "does this sound like a person, not a synthesiser?".

Neither may ever break the pipeline. Without torch/transformers, without the
weights (offline), or on audio too short to judge, a score is None and the
take is not blocked, as before this phase. Models load on first use and stay
loaded; `embed` / `predict` are injectable so tests never load one.
"""
from __future__ import annotations

import logging
import os
from collections.abc import Callable
from pathlib import Path

import numpy as np

from app.continuity import signals

log = logging.getLogger(__name__)

SPEAKER_MODEL = "microsoft/wavlm-base-plus-sv"
MOS_REPO, MOS_MODEL, MOS_REVISION = "tarepan/SpeechMOS", "utmos22_strong", "v1.2.0"
MIN_SECONDS = 0.5     # shorter audio carries no judgeable voice
MAX_SECONDS = 20.0    # longer is trimmed: the score settles well before this

Embed = Callable[[np.ndarray], np.ndarray]    # 16 kHz mono samples -> speaker vector
Predict = Callable[[np.ndarray], float]       # 16 kHz mono samples -> MOS

_embedder: Embed | None = None
_predictor: Predict | None = None
_failed: set[str] = set()     # a model that could not load is not retried every take


def available() -> bool:
    """Whether the `measure` extra can run: importable, and not switched off
    with AVE_MEASURE=0."""
    if os.environ.get("AVE_MEASURE") == "0":
        return False
    try:
        import torch  # noqa: F401
        import transformers  # noqa: F401
    except ImportError:
        return False
    return True


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else "cpu"


def _load_embedder() -> Embed | None:
    global _embedder
    if _embedder is None and "embed" not in _failed:
        try:
            import torch
            from transformers import AutoFeatureExtractor, WavLMForXVector

            device = _device()
            extractor = AutoFeatureExtractor.from_pretrained(SPEAKER_MODEL)
            model = WavLMForXVector.from_pretrained(SPEAKER_MODEL).to(device).eval()

            def embed(x: np.ndarray) -> np.ndarray:
                inputs = extractor(x, sampling_rate=signals.RATE, return_tensors="pt")
                with torch.no_grad():
                    out = model(**{k: v.to(device) for k, v in inputs.items()})
                return out.embeddings[0].float().cpu().numpy()

            _embedder = embed
        except Exception as exc:  # noqa: BLE001  # offline, no disk, no extra: unmeasured, not broken
            log.warning("speaker model unavailable: %s", exc)
            _failed.add("embed")
    return _embedder


def _load_predictor() -> Predict | None:
    global _predictor
    if _predictor is None and "predict" not in _failed:
        try:
            import torch

            model = torch.hub.load(
                MOS_REPO + ":" + MOS_REVISION, MOS_MODEL, trust_repo=True,
            ).eval()

            def predict(x: np.ndarray) -> float:
                with torch.no_grad():
                    return float(model(torch.from_numpy(x)[None, :], signals.RATE)[0])

            _predictor = predict
        except Exception as exc:  # noqa: BLE001
            log.warning("naturalness model unavailable: %s", exc)
            _failed.add("predict")
    return _predictor


def _samples(path: Path) -> np.ndarray | None:
    """The audio as 16 kHz mono, trimmed, or None when too short to judge."""
    x = signals.load(path)
    if x.size < MIN_SECONDS * signals.RATE:
        return None
    return x[: int(MAX_SECONDS * signals.RATE)]


def speaker_similarity(reference: Path, candidate: Path, *, embed: Embed | None = None) -> float | None:
    """SIM-o in [0, 1]: how much `candidate` sounds like the speaker in `reference`."""
    try:
        embed = embed or _load_embedder()
        if embed is None:
            return None
        ref, cand = _samples(reference), _samples(candidate)
        if ref is None or cand is None:
            return None
        a, b = np.asarray(embed(ref), dtype=np.float64), np.asarray(embed(cand), dtype=np.float64)
        norm = float(np.linalg.norm(a) * np.linalg.norm(b))
        if norm == 0.0:
            return None
        return max(0.0, min(1.0, float(a @ b) / norm))
    except Exception as exc:  # noqa: BLE001
        log.warning("speaker similarity failed: %s", exc)
        return None


def naturalness(candidate: Path, *, predict: Predict | None = None) -> float | None:
    """UTMOS-style mean opinion score (1-5) of `candidate`."""
    try:
        predict = predict or _load_predictor()
        if predict is None:
            return None
        x = _samples(candidate)
        if x is None:
            return None
        return max(1.0, min(5.0, float(predict(x))))
    except Exception as exc:  # noqa: BLE001
        log.warning("naturalness failed: %s", exc)
        return None
