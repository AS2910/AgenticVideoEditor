"""The frame-exact patch (from Phase 17's `render/mouth.py`, kept as it was
built and tested there): lay clips over frame ranges of a source picture."""
from __future__ import annotations

from collections.abc import Sequence


def patch_graph(stretches: Sequence[tuple[int, int]], total: int, width: int, height: int, fps: float) -> str:
    """The filter graph that lays each clip (input 1..k) over its frames
    [first, last) of the source (input 0): copies of the source between, the
    clips exactly as many frames long as the spans they replace."""
    parts, labels, cursor = [], [], 0
    for i, (first, last) in enumerate(stretches):
        if first > cursor:
            parts.append(f"[0:v]trim=start_frame={cursor}:end_frame={first},setpts=PTS-STARTPTS[b{i}]")
            labels.append(f"[b{i}]")
        n = last - first
        # The clip's own length can differ by a frame; padded with its last frame, cut to the span.
        parts.append(
            f"[{i + 1}:v]fps={fps:.6f},scale={width}:{height},setsar=1,format=yuv420p,"
            f"tpad=stop_mode=clone:stop=5,trim=end_frame={n},setpts=PTS-STARTPTS[m{i}]"
        )
        labels.append(f"[m{i}]")
        cursor = last
    if cursor < total:
        parts.append(f"[0:v]trim=start_frame={cursor},setpts=PTS-STARTPTS[tail]")
        labels.append("[tail]")
    parts.append(f"{''.join(labels)}concat=n={len(labels)}:v=1:a=0,format=yuv420p[v]")
    return ";".join(parts)

