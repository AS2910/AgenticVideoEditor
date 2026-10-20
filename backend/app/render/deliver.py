"""B3: one delivered file from a finished render: the platform's frame, the
codec, the loudness target and, when asked, captions burned into the picture.

    deliver(src, dest, platform=, codec=, loudness_lufs=, cues=) -> report
    measure(path)        -> {"lufs", "true_peak_db"}   ffmpeg's EBU R128 meter on the file
    codecs()             -> the codecs this ffmpeg can write
    caption_renderer()   -> "libass" | "opencv" | None

Frame: the picture is scaled to fit the platform's frame and padded with
black (letterbox or pillarbox), never cropped, so nothing in the shot is
lost; the report says which and by how much.
Loudness: the render's audio is normalised with the mix's own BS.1770 code
(app/media/loudness.py) to the target, under a true-peak ceiling of -1 dBTP
(-2 for broadcast), then encoded; the report carries ffmpeg's measurement of
the file as written.
Captions: ffmpeg's subtitles filter (libass) when this ffmpeg has it; else
OpenCV's Hershey font drawn into PNGs and overlaid at their times (Latin
letters only: other scripts need libass); with neither, the file fails with
a sentence saying so.
"""
from __future__ import annotations

import functools
import re
import shutil
import tempfile
import unicodedata
from pathlib import Path
from typing import Sequence

import numpy as np

from app.media import ffmpeg, loudness
from app.render import captions as captions_mod
from app.render.compose import OUT_RATE, _write, decode

PLATFORMS = {
    "youtube": {"label": "YouTube 16:9", "aspect": "16:9", "size": (1920, 1080)},
    "reels": {"label": "Reels 9:16", "aspect": "9:16", "size": (1080, 1920)},
    "feed": {"label": "Feed 1:1", "aspect": "1:1", "size": (1080, 1080)},
}
CODECS = {
    "h264": {"label": "H.264", "encoder": "libx264",
             "args": ["-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-profile:v", "high"]},
    "hevc": {"label": "HEVC (H.265)", "encoder": "libx265",
             "args": ["-preset", "fast", "-crf", "24", "-pix_fmt", "yuv420p", "-tag:v", "hvc1", "-x265-params", "log-level=error"]},
}
# The loudness targets a preset may ask for, with their true-peak ceilings.
LOUDNESS = {
    -14.0: {"label": "Web · -14 LUFS", "ceiling": -1.0},
    -16.0: {"label": "General · -16 LUFS", "ceiling": -1.0},
    -24.0: {"label": "Broadcast · -24 LUFS", "ceiling": -2.0},
}
AUDIO_BITRATE = "192k"


class DeliverError(RuntimeError):
    """A file that cannot be made, with a sentence fit to show."""


@functools.lru_cache(maxsize=1)
def _ffmpeg_lists() -> tuple[str, str]:
    encoders, _ = ffmpeg.run_capture(["-hide_banner", "-encoders"])
    filters, _ = ffmpeg.run_capture(["-hide_banner", "-filters"])
    return str(encoders), str(filters)


def codecs() -> list[str]:
    """The preset codecs this machine's ffmpeg can write (h264 first)."""
    try:
        encoders, _ = _ffmpeg_lists()
    except ffmpeg.FFmpegError:
        return ["h264"]
    return [k for k, c in CODECS.items() if re.search(rf"\s{c['encoder']}\s", encoders)] or ["h264"]


def caption_renderer() -> str | None:
    try:
        _, filters = _ffmpeg_lists()
    except ffmpeg.FFmpegError:
        filters = ""
    if re.search(r"\ssubtitles\s", filters):
        return "libass"
    try:
        import cv2  # noqa: F401
    except ImportError:
        return None
    return "opencv"


def fit(width: int, height: int, frame: tuple[int, int]) -> tuple[int, int, str]:
    """The picture's size inside the frame (even numbers) and what was done
    to fit it: scaled, then padded; never cropped."""
    fw, fh = frame
    scale = min(fw / width, fh / height)
    w = max(2, min(fw, int(round(width * scale / 2)) * 2))
    h = max(2, min(fh, int(round(height * scale / 2)) * 2))
    if fw - w < 4 and fh - h < 4:
        return fw, fh, "Fills the frame."
    if w < fw:
        return w, fh if fh - h < 4 else h, f"Pillarboxed: black bars of {(fw - w) // 2} px left and right, nothing cropped."
    return w, h, f"Letterboxed: black bars of {(fh - h) // 2} px above and below, nothing cropped."


def _display_size(src: Path) -> tuple[int, int]:
    for s in ffmpeg.probe(src)["streams"]:
        if s.get("codec_type") == "video":
            w, h = int(s["width"]), int(s["height"])
            sar = s.get("sample_aspect_ratio") or "1:1"
            if re.fullmatch(r"\d+:\d+", sar) and not sar.startswith("0"):
                n, d = (int(x) for x in sar.split(":"))
                w = int(round(w * n / d))
            rotate = int(float((s.get("tags") or {}).get("rotate", 0) or 0)) % 180
            side = [x for x in s.get("side_data_list") or [] if "rotation" in x]
            if rotate == 90 or (side and abs(int(side[0]["rotation"])) % 180 == 90):
                w, h = h, w
            return w, h
    raise DeliverError("The render has no picture to export.")


def _has_audio(src: Path) -> bool:
    return any(s.get("codec_type") == "audio" for s in ffmpeg.probe(src)["streams"])


def _ascii(text: str) -> str:
    swaps = {"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2026": "...", "\u20b9": "Rs "}
    text = "".join(swaps.get(ch, ch) for ch in text)
    plain = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return plain.encode("ascii", "replace").decode()


def _caption_png(lines: Sequence[str], frame: tuple[int, int], dest: Path) -> int:
    """White words with a black outline on a clear strip the frame's width; returns its height."""
    import cv2

    fw, fh = frame
    font = cv2.FONT_HERSHEY_DUPLEX
    scale = max(0.5, min(fw, fh) / 1080 * 1.5)
    thick = max(1, round(scale * 1.6))
    lines = [_ascii(line) for line in lines]
    widest = max(cv2.getTextSize(line, font, scale, thick)[0][0] for line in lines)
    if widest > fw * 0.9:
        scale *= fw * 0.9 / widest
        thick = max(1, round(scale * 1.6))
    (_, th), base = cv2.getTextSize("Hg", font, scale, thick)
    line_h = th + base + int(th * 0.35)
    pad = thick * 3
    height = pad * 2 + line_h * len(lines)
    img = np.zeros((height, fw, 4), dtype=np.uint8)
    for i, line in enumerate(lines):
        (w, _), _ = cv2.getTextSize(line, font, scale, thick)
        org = ((fw - w) // 2, pad + i * line_h + th)
        cv2.putText(img, line, org, font, scale, (0, 0, 0, 255), thick * 4, cv2.LINE_AA)
        cv2.putText(img, line, org, font, scale, (255, 255, 255, 255), thick, cv2.LINE_AA)
    if not cv2.imwrite(str(dest), img):
        raise DeliverError("The captions could not be drawn.")
    return height


def _margin(platform: str, frame: tuple[int, int]) -> int:
    # Reels' own buttons and caption sit over the bottom fifth of the frame.
    return int(frame[1] * (0.2 if platform == "reels" else 0.07))


def _audio_track(src: Path, dest: Path, target: float, ceiling: float) -> float | None:
    """The render's audio at `target` LUFS under `ceiling` dBTP as a WAV;
    the loudness the code measures on it (None for silence)."""
    if _has_audio(src):
        x = decode(src, channels=2)
    else:
        x = np.zeros((int(ffmpeg.duration_of(src) * OUT_RATE), 2), dtype=np.float32)
    out, lufs = loudness.normalize(x.astype(np.float64), target, ceiling, OUT_RATE)
    _write(dest, out)
    return None if lufs <= loudness.SILENCE else round(float(lufs), 2)


def measure(path: str | Path) -> dict:
    """ffmpeg's EBU R128 meter on a file: integrated loudness and true peak."""
    _, err = ffmpeg.run_capture(["-hide_banner", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = str(err)[str(err).rfind("Summary:"):]
    lufs = re.search(r"I:\s+(-?[\d.]+|-inf) LUFS", summary)
    peak = re.search(r"Peak:\s+(-?[\d.]+|-inf) dBFS", summary)
    as_float = lambda m: None if not m or "inf" in m.group(1) else float(m.group(1))  # noqa: E731
    return {"lufs": as_float(lufs), "true_peak_db": as_float(peak)}


def deliver(src: str | Path, dest: str | Path, *, platform: str, codec: str = "h264", loudness_lufs: float = -14.0,
            cues: Sequence[captions_mod.Cue] | None = None) -> dict:
    """Write `dest` from the render at `src`; the report says what was done."""
    src, dest = Path(src), Path(dest)
    if platform not in PLATFORMS:
        raise DeliverError(f"Unknown platform {platform}.")
    if codec not in CODECS or codec not in codecs():
        raise DeliverError(f"This server cannot write {CODECS.get(codec, {}).get('label', codec)}.")
    target = float(loudness_lufs)
    ceiling = LOUDNESS.get(target, {"ceiling": -1.0})["ceiling"]
    frame = PLATFORMS[platform]["size"]
    sw, sh = _display_size(src)
    w, h, framing = fit(sw, sh, frame)
    duration = ffmpeg.duration_of(src)
    renderer = caption_renderer() if cues else None
    if cues and renderer is None:
        raise DeliverError("Burned-in captions need ffmpeg built with libass, or OpenCV, on the server.")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        audio = tmpdir / "audio.wav"
        code_lufs = _audio_track(src, audio, target, ceiling)
        chain = (f"[0:v]scale={w}:{h}:flags=lanczos,setsar=1,"
                 f"pad={frame[0]}:{frame[1]}:(ow-iw)/2:(oh-ih)/2:color=black")
        inputs: list[str] = ["-i", str(src), "-i", str(audio)]
        graph: list[str] = []
        last = "v0"
        if cues and renderer == "libass":
            subs = tmpdir / "captions.srt"
            subs.write_text(captions_mod.srt(cues), encoding="utf-8")
            size = max(14, int(min(frame) / 1080 * 22))
            style = f"FontSize={size},Outline=2,Shadow=0,MarginV={int(_margin(platform, frame) * 288 / frame[1])},Alignment=2"
            chain += f",subtitles=filename={subs}:original_size={frame[0]}x{frame[1]}:force_style='{style}'"
            graph.append(chain + "[v0]")
        else:
            graph.append(chain + "[v0]")
            for k, cue in enumerate(cues or ()):
                png = tmpdir / f"cap{k}.png"
                height = _caption_png(cue.lines, frame, png)
                y = frame[1] - _margin(platform, frame) - height
                inputs += ["-loop", "1", "-i", str(png)]
                graph.append(f"[{last}][{k + 2}:v]overlay=0:{y}:enable='between(t,{cue.start:.3f},{cue.end:.3f})':shortest=1[v{k + 1}]")
                last = f"v{k + 1}"
        out = tmpdir / "out.mp4"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(graph),
            "-map", f"[{last}]", "-map", "1:a", "-c:v", CODECS[codec]["encoder"], *CODECS[codec]["args"],
            "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", str(OUT_RATE), "-t", f"{duration:.3f}",
            "-movflags", "+faststart", str(out),
        ])
        shutil.move(str(out), dest)
    measured = measure(dest)
    return {
        "platform": platform, "codec": codec, "width": frame[0], "height": frame[1], "picture": [w, h],
        "framing": framing, "loudness_target": target, "true_peak_ceiling": ceiling,
        "loudness_lufs": measured["lufs"], "true_peak_db": measured["true_peak_db"], "loudness_code_lufs": code_lufs,
        "captions": len(cues or ()), "captions_renderer": renderer, "duration": round(ffmpeg.duration_of(dest), 3),
        "size": dest.stat().st_size,
    }
