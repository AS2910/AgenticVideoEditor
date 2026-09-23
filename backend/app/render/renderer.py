from dataclasses import dataclass
from app.domain.models import Source, ApprovedEdit, MediaArtifact


@dataclass(frozen=True)
class RenderSegment:
    start: float
    end: float
    kind: str   # "original" | "edited"
    ref: str    # source filename for originals, artifact sha256 for edited spans
    artifact: MediaArtifact | None = None  # the media backing this span
    # The approved edit that owns an edited span. A span can be only part of
    # its edit (a later approval took the rest), so the compositor needs the
    # edit itself to find where in the edit's audio this span begins.
    edit: ApprovedEdit | None = None


@dataclass(frozen=True)
class RenderManifest:
    segments: tuple[RenderSegment, ...]


def render(source: Source, edits: list[ApprovedEdit]) -> RenderManifest:
    """Composite the immutable source with approved edits into a segment list.

    `edits` is in approval order, and the edit stack is last-write-wins: a
    later approval owns any span it overlaps, and an earlier edit keeps only
    what is left of it. Original footage fills every gap. The segments tile
    [0, duration] exactly.
    """
    # Each piece is (start, end, owning edit or None for original footage).
    pieces: list[tuple[float, float, ApprovedEdit | None]] = [(0.0, source.duration, None)]
    for e in edits:
        start = max(0.0, e.plan.selection.start)
        end = min(source.duration, e.plan.selection.end)
        if end <= start:
            continue
        kept: list[tuple[float, float, ApprovedEdit | None]] = []
        for a, b, owner in pieces:
            if b <= start or a >= end:
                kept.append((a, b, owner))
                continue
            if a < start:
                kept.append((a, start, owner))
            if b > end:
                kept.append((end, b, owner))
        kept.append((start, end, e))
        pieces = sorted(kept, key=lambda p: p[0])

    segments = []
    for a, b, owner in pieces:
        if owner is None:
            segments.append(RenderSegment(a, b, "original", source.filename, source.media))
        else:
            segments.append(
                RenderSegment(a, b, "edited", owner.frames.sha256, owner.frames, owner)
            )
    return RenderManifest(segments=tuple(segments))
