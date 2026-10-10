"""Run the corpus: fit, assess, render and measure every case (Phase 19)."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from app.bench.corpus import Case
from app.continuity.measured import MeasuredContinuityEngine
from app.continuity.seam import discontinuity, worst
from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact
from app.media import ffmpeg, fit, motion
from app.media.ffmpeg import SpanMismatch
from app.render import compose, retime
from app.render.renderer import render
from app.store.artifacts import ArtifactStore
from tests.factories import make_source  # the same builder the suite uses; the bench is a test of the product


@dataclass
class Result:
    name: str
    label: str
    tags: list[str]
    mix: str
    ratio: float                 # the take's natural length over the slot
    rung: str                    # none | gaps | tempo | gaps+tempo | ask
    fit_notes: list[str]
    passed: bool | None          # continuity verdict; None when the take never fitted
    prosody: float | None
    audio_integration: float | None
    warnings: list[str]
    seam_level_db: float | None  # worst level step the edit added at its seams, on the render, vs the original
    seam_colour_st: float | None # worst spectral-centroid step added, in semitones
    frozen_seconds: float        # how long the export shows a frozen frame
    render_seconds: float | None
    ok: bool                     # the label's expectation was met

    @property
    def score(self) -> float:
        values = [v for v in (self.prosody, self.audio_integration) if v is not None]
        return min(values) if values else (1.0 if self.passed else 0.0)


def _rung(notes: Sequence[str]) -> str:
    """The rungs the fit used, in the ladder's order, joined with "+"; "none" when the take fitted as it was."""
    used = []
    if any(n.startswith(("trimmed", "opened")) for n in notes):
        used.append("gaps")
    if any(n.startswith("the picture at") for n in notes):
        used.append("flex")
    if any(n.startswith("speech at") for n in notes):
        used.append("tempo")
    return "+".join(used) or "none"


def _expectation_met(label: str, rung: str, passed: bool | None) -> bool:
    if label == "ask":
        return rung == "ask"
    if rung == "ask":
        return False
    return bool(passed) if label == "good" else not passed


def run_case(case: Case, workdir: Path) -> Result:
    d = workdir / "".join(c if c.isalnum() else "_" for c in case.name)
    d.mkdir(parents=True, exist_ok=True)
    duration = ffmpeg.duration_of(case.clip)
    media = MediaArtifact("video", "c" * 64, str(case.clip), duration, "mp4")
    source = make_source(project_id="bench", filename=case.clip.name, duration=duration, media=media)
    span = case.selection.end - case.selection.start
    take = case.take(d)
    natural = ffmpeg.duration_of(take)
    plan = EditPlan(case.selection, "bench", "bench-voice", mix=case.mix)
    try:
        fitted, fitted_len, notes, _ = fit.place(take, d / "fitted.wav", span, None, case.mix, flex_max=fit.DEFAULT_MAX_FLEX)
    except SpanMismatch:
        return Result(case.name, case.label, list(case.tags), case.mix, round(natural / span, 3), "ask", [],
                      None, None, None, [], None, None, 0.0, None, _expectation_met(case.label, "ask", None))
    rung = _rung(notes) if case.mix != "concatenate" else "none"
    store = ArtifactStore(d / "store")
    audio = store.put_file("bench", fitted, kind="audio", container="wav", duration=fitted_len)
    assessed = MeasuredContinuityEngine(store).assess(source, case.transcript, plan, audio)
    report = assessed.report

    # Render the edit as the export would (Phase 16: flexed, living or held), and listen at its seams.
    flex = fit.flex_of(notes)
    if abs(flex - 1) > 1e-6:
        plan = EditPlan(case.selection, "bench", "bench-voice", mix=case.mix, flex=flex)
    edit = ApprovedEdit("e1", "c1", plan, assessed.audio, assessed.audio)
    manifest = render(source, [edit])
    fps = ffmpeg.frame_rate(case.clip)
    motion_fn = lambda a, b: motion.motion(case.clip, a, b)   # noqa: E731
    flexed = retime.flex_pieces([edit], motion_fn)
    living = retime.living_pieces(manifest.inserts, case.transcript, duration, (), motion_fn,
                                  taken=[(p.start, p.end) for p in flexed])
    pieces = retime.tile(duration, [*flexed, *living], fps)
    out = compose.compose(source, manifest.segments, d / "render.mp4", inserts=manifest.inserts, pieces=pieces)
    rendered = compose.decode(out)
    original = compose.decode(case.clip, channels=rendered.shape[1])
    if case.mix == "concatenate":
        # The line sits between two halves of one moment of the original.
        at = min(case.selection.end, duration)
        seams, original_seams = [retime.render_time(at, pieces), retime.render_time(at, pieces) + fitted_len], [at, at]
    else:
        original_seams = [case.selection.start, case.selection.end]
        seams = [retime.render_time(t, pieces) for t in original_seams]
    level, colour = worst(discontinuity(rendered, original, compose.OUT_RATE, seams, original_seams))
    frozen = retime.held_seconds(pieces)
    return Result(
        case.name, case.label, list(case.tags), case.mix, round(natural / span, 3), rung, list(notes),
        report.passed, report.prosody, report.audio_integration, list(report.warnings),
        round(level, 3), round(colour, 3), round(frozen, 3), round(ffmpeg.duration_of(out), 3),
        _expectation_met(case.label, rung, report.passed),
    )


def run(cases: Sequence[Case], workdir: Path) -> list[Result]:
    return [run_case(c, workdir) for c in cases]


def to_json(results: Sequence[Result]) -> dict:
    return {
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cases": [asdict(r) for r in results],
        "summary": {
            "cases": len(results),
            "expectations_met": sum(r.ok for r in results),
            "frozen_seconds": round(sum(r.frozen_seconds for r in results), 3),
        },
    }


def from_json(data: dict) -> list[Result]:
    return [Result(**c) for c in data["cases"]]


def table(results: Sequence[Result]) -> str:
    """A markdown table: one row per case."""
    head = "| case | label | ratio | rung | passed | prosody | integration | seam dB | seam st | frozen s | ok |"
    rule = "|---|---|---:|---|---|---:|---:|---:|---:|---:|---|"
    fmt = lambda v: "—" if v is None else f"{v:.2f}"  # noqa: E731
    rows = [
        f"| {r.name} | {r.label} | {r.ratio:.2f} | {r.rung} | {'—' if r.passed is None else ('yes' if r.passed else 'no')} "
        f"| {fmt(r.prosody)} | {fmt(r.audio_integration)} | {fmt(r.seam_level_db)} | {fmt(r.seam_colour_st)} | {r.frozen_seconds:.2f} | {'✓' if r.ok else '✗'} |"
        for r in results
    ]
    return "\n".join([head, rule, *rows])


def save(results: Sequence[Result], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json(results), indent=2) + "\n")
    return path
