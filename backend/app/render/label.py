"""Voice consent V1, step 7: the "AI voice" label on an export.

    geometry(width, height) -> (tag_height, x, y)   where the tag sits in that frame
    overlay(base, tag, out, frame) -> str            the filter graph piece (ffmpeg overlay)
    burn(src, dst) -> None                           the label drawn into a finished file
    description(...) -> str                          the export's description file

The tag is a small corner label, "AI voice" in the design system's display
face (Space Grotesk, ink on volt with an ink border, `assets/ai-voice-tag.png`),
shown for the first SECONDS of the picture and gone after. This server's
ffmpeg has no drawtext (no freetype), so the words are a picture drawn once
from `assets/ai-voice-tag.html` (open it in Chrome and take an element shot of
`#tag` with a clear background to redraw it) and overlaid, scaled to the
frame: 5% of the frame's short side tall (54 px at 1080, never under 22 px),
3% in from the top left, lower on a tall frame (9:16) where the platform's own
bar covers the top. `deliver` draws it in the same encode as the preset; the
Export page's file gets it from `burn`, which re-encodes the picture and copies
the sound.
"""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.media import ffmpeg

TAG = Path(__file__).with_name("assets") / "ai-voice-tag.png"
SECONDS = 3.0
LABEL_LINE = "AI voice: this video contains a voice made with AI."
H264 = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p"]


def geometry(width: int, height: int) -> tuple[int, int, int]:
    """The tag's height and its top-left corner in a frame of this size."""
    short = min(width, height)
    tag_h = max(22, int(round(short * 0.05 / 2)) * 2)
    x = max(8, int(round(short * 0.03)))
    y = int(round(height * 0.06)) if height >= width * 1.5 else x
    return tag_h, x, y


def overlay(base: str, tag: str, out: str, frame: tuple[int, int]) -> str:
    """`[base]` with the tag input `[tag]` drawn on it for the first SECONDS, as `[out]`."""
    tag_h, x, y = geometry(*frame)
    return (f"[{tag}]scale=-2:{tag_h}:flags=lanczos[aitag];"
            f"[{base}][aitag]overlay={x}:{y}:enable='lt(t,{SECONDS:g})'[{out}]")


def _size(src: Path) -> tuple[int, int]:
    for s in ffmpeg.probe(src)["streams"]:
        if s.get("codec_type") == "video":
            return int(s["width"]), int(s["height"])
    raise ValueError("The file has no picture to label.")


def burn(src: str | Path, dst: str | Path) -> None:
    """`dst`: `src` with the tag in its first SECONDS (picture re-encoded, sound copied)."""
    src, dst = Path(src), Path(dst)
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "labelled.mp4"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", "-i", str(src), "-i", str(TAG),
            "-filter_complex", overlay("0:v", "1:v", "v", _size(src)),
            "-map", "[v]", "-map", "0:a?", *H264, "-c:a", "copy", "-map_metadata", "0",
            "-movflags", "+faststart", str(out),
        ])
        shutil.move(str(out), dst)


def description(*, title: str, export_id: str, created: str, label_on: bool, mark: str | None = None) -> str:
    """The export's description file: what it is and where it came from, with the label's line when it is on."""
    lines = [title, "Made with Voltage."]
    if label_on:
        lines.append(LABEL_LINE)
    lines += [f"Export id: {export_id}", f"Exported: {created}"]
    if mark:
        lines.append(f"Provenance mark: {mark}")
    return "\n".join(lines) + "\n"


def description_path(path: str | Path) -> Path:
    """Where a file's description sits: beside it, `<name>.txt`."""
    path = Path(path)
    return path.with_name(path.stem + ".txt")
