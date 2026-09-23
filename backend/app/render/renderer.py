from dataclasses import dataclass
from app.domain.models import Source, ApprovedEdit, MediaArtifact


@dataclass(frozen=True)
class RenderSegment:
    start: float
    end: float
    kind: str   # "original" | "edited"
    ref: str    # source filename for originals, artifact sha256 for edited spans
    artifact: MediaArtifact | None = None  # the media backing this span


@dataclass(frozen=True)
class RenderManifest:
    segments: tuple[RenderSegment, ...]


def render(source: Source, edits: list[ApprovedEdit]) -> RenderManifest:
    """Composite the immutable source with approved edits into a segment list.

    Edited spans replace their region; original footage fills every gap.
    Real ffmpeg compositing replaces this in a later plan.
    """
    ordered = sorted(edits, key=lambda e: e.plan.selection.start)
    segments: list[RenderSegment] = []
    cursor = 0.0
    # Overlapping edits are the caller's responsibility to prevent. If two edits
    # overlap, the later-starting one's span wins and a zero/negative gap is skipped.
    for e in ordered:
        sel = e.plan.selection
        if sel.start > cursor:
            segments.append(
                RenderSegment(cursor, sel.start, "original", source.filename, source.media)
            )
        segments.append(RenderSegment(sel.start, sel.end, "edited", e.frames.sha256, e.frames))
        cursor = max(cursor, sel.end)
    if cursor < source.duration:
        segments.append(
            RenderSegment(cursor, source.duration, "original", source.filename, source.media)
        )
    return RenderManifest(segments=tuple(segments))
