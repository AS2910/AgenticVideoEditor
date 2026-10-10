"""Real rendering (Phase 7): the source video, re-voiced where edits were approved.

The video frames are the source's own, everywhere. Lip-sync is backlogged
(Phase 5) and the mock "frames" are a flat colour, so splicing those in would
make the export worse; until real lip-sync lands, the mouth will not match the
new words. `use_generated_frames` is where Phase 5 switches that on.

Audio is decoded at 48 kHz in the source's own channel layout, each edited
span is replaced by its edit's audio, and every seam gets a short equal-power
crossfade *inside* the span — so everything outside an edit stays exactly the
source's audio. A layered edit is mixed over the span instead of replacing it.

Concatenated edits are inserts. Until Phase 16 the video held the frame at
the insert point while the line played; now the export is assembled from
*pieces* (`render.retime`): copies of the source, flexed spans whose picture
runs a touch slower or faster so a take fits at natural speech, living holds
that stretch (and if need be loop) the pause after an added line, and — only
when there is no window at all — the old frozen frame. Any piece but a copy
means re-encoding the video, so such an export is not stream-copied.
"""
from __future__ import annotations

import tempfile
import wave
from pathlib import Path
from typing import Sequence
import math

import numpy as np

from app.domain.models import Source
from app.media import ffmpeg
from app.render import retime
from app.render.renderer import RenderInsert, RenderSegment

OUT_RATE = 48000
CROSSFADE = 0.02     # seconds per seam
AUDIO_BITRATE = "192k"
# Codecs that play in every browser inside MP4. Anything else is re-encoded.
_COPYABLE_VIDEO = {"h264"}


def _channels(path: str | Path) -> int:
    streams = ffmpeg.probe(path)["streams"]
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    return min(int(audio[0].get("channels", 1)), 2) if audio else 1


def decode(path: str | Path, channels: int | None = None) -> np.ndarray:
    """Audio as float32 of shape (samples, channels) at OUT_RATE."""
    channels = channels or _channels(path)
    with tempfile.TemporaryDirectory() as tmp:
        dest = Path(tmp) / "a.wav"
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", "-i", str(path), "-vn",
            "-ac", str(channels), "-ar", str(OUT_RATE), "-c:a", "pcm_s16le", str(dest),
        ])
        with wave.open(str(dest), "rb") as w:
            raw = w.readframes(w.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return samples.reshape(-1, channels)


def _write(path: Path, x: np.ndarray) -> None:
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(x.shape[1])
        w.setsampwidth(2)
        w.setframerate(OUT_RATE)
        w.writeframes(pcm.tobytes())


def splice(base: np.ndarray, segments: Sequence[RenderSegment]) -> np.ndarray:
    """Replace each edited span of `base` with its edit's audio, crossfaded."""
    out = base.copy()
    channels = base.shape[1]
    cache: dict[str, np.ndarray] = {}
    for seg in segments:
        if seg.kind != "edited" or seg.edit is None:
            continue
        i0 = min(round(seg.start * OUT_RATE), len(out))
        i1 = min(round(seg.end * OUT_RATE), len(out))
        length = i1 - i0
        if length <= 0:
            continue
        edit = seg.edit
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        audio = cache[edit.audio.sha256]
        # A span may be only the tail of its edit (a later approval took the
        # head), so start reading the edit's audio at the matching offset.
        offset = round((seg.start - edit.plan.selection.start) * OUT_RATE)
        piece = audio[offset:offset + length]
        if len(piece) < length:
            piece = np.pad(piece, ((0, length - len(piece)), (0, 0)))

        fade = min(round(CROSSFADE * OUT_RATE), length // 2)
        new = np.ones(length, dtype=np.float32)
        if fade:
            ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))
            new[:fade] = ramp
            new[-fade:] = ramp[::-1]
        if edit.plan.mix == "layer":
            # The original keeps playing; only the line fades in and out.
            out[i0:i1] = base[i0:i1] + piece * new[:, None]
        else:
            old = np.sqrt(np.maximum(0.0, 1.0 - new ** 2))  # equal power
            out[i0:i1] = base[i0:i1] * old[:, None] + piece * new[:, None]
    return out


def _holds(inserts: Sequence[RenderInsert], duration: float) -> list[tuple[float, float]]:
    """(point, seconds held) per distinct insert point, in time order."""
    held: dict[float, float] = {}
    for ins in inserts:
        at = round(min(max(ins.at, 0.0), duration), 3)
        held[at] = held.get(at, 0.0) + ins.duration
    return sorted(held.items())


def insert_audio(
    base: np.ndarray, inserts: Sequence[RenderInsert], duration: float,
) -> np.ndarray:
    """`base` with each insert's line added at its point, pushing the rest later."""
    if not inserts:
        return base
    channels = base.shape[1]
    lines: dict[float, list[np.ndarray]] = {}
    for ins in inserts:
        at = round(min(max(ins.at, 0.0), duration), 3)
        line = decode(ins.edit.audio.path, channels=channels)
        fade = min(round(CROSSFADE * OUT_RATE), len(line) // 2)
        if fade:
            ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))[:, None]
            line = line.copy()
            line[:fade] *= ramp
            line[-fade:] *= ramp[::-1]
        lines.setdefault(at, []).append(line)
    parts, cursor = [], 0
    for at in sorted(lines):
        i = min(round(at * OUT_RATE), len(base))
        parts.append(base[cursor:i])
        parts.extend(lines[at])
        cursor = i
    parts.append(base[cursor:])
    return np.concatenate(parts)


def hold_filter(holds: list[tuple[float, float]], duration: float) -> str:
    """A filter graph that cuts the video at each hold point and freezes the
    frame there for the hold's length. Output label: [v]."""
    duration = round(duration, 3)  # the same rounding as the hold points
    points = [p for p, _ in holds if 0.0 < p < duration]
    edges = [0.0, *points, duration]
    pieces = list(zip(edges, edges[1:]))
    pad_at = dict(holds)
    chains = []
    labels = [f"[s{i}]" for i in range(len(pieces))]
    chains.append(f"[0:v]split={len(pieces)}{''.join(labels)}" if len(pieces) > 1
                  else "[0:v]null[s0]")
    for i, (a, b) in enumerate(pieces):
        pads = []
        if i == 0 and 0.0 in pad_at:
            pads.append(f"start_mode=clone:start_duration={pad_at[0.0]:.3f}")
        if b in pad_at and b > 0.0:
            pads.append(f"stop_mode=clone:stop_duration={pad_at[b]:.3f}")
        tpad = f",tpad={':'.join(pads)}" if pads else ""
        chains.append(f"[s{i}]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS{tpad}[v{i}]")
    joined = "".join(f"[v{i}]" for i in range(len(pieces)))
    chains.append(f"{joined}concat=n={len(pieces)}:v=1:a=0[v]")
    return ";".join(chains)


def _video_codec(path: str | Path) -> str | None:
    for stream in ffmpeg.probe(path)["streams"]:
        if stream.get("codec_type") == "video":
            return stream.get("codec_name")
    return None


# ── Phase 16: the output as pieces ─────────────────────────────────────────────

INTERPOLATORS = ("minterpolate", "none", "rife")


def interpolation(interpolator: str, fps: float) -> str:
    """The filter that makes the in-between frames of a stretched piece.
    `minterpolate` is motion-compensated and slow; `none` repeats frames; `rife`
    is a seam for a self-hosted model — this build has no RIFE binary, so it
    falls back to `minterpolate`."""
    if interpolator == "none":
        return f"fps={fps:g}"
    return f"minterpolate=fps={fps:g}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"


def _f(seconds: float, fps: float) -> int:
    return int(round(seconds * fps))


def _chunk_frames(chunks: Sequence[retime.Chunk], total: int, fps: float) -> list[int]:
    """Frames per chunk, summing exactly to `total`."""
    raw = [(c.end - c.start) * c.factor * fps for c in chunks]
    scale = total / sum(raw) if sum(raw) > 0 else 1.0
    out, acc = [], 0.0
    for r in raw:
        acc += r * scale
        n = int(round(acc)) - sum(out)
        out.append(max(0, n))
    out[-1] += total - sum(out)
    return out


def video_graph(pieces: Sequence[retime.Piece], fps: float, interpolator: str = "minterpolate") -> str:
    """One filter graph for the whole picture: every piece a whole number of
    frames with uniform timestamps, then concatenated. Output label: [v]."""
    n = len(pieces)
    labels = "".join(f"[s{i}]" for i in range(n))
    chains = [f"[0:v]fps={fps:g},split={n}{labels}" if n > 1 else f"[0:v]fps={fps:g}[s0]"]
    pts = f"setpts=N/({fps:g}*TB)"
    outs = []
    for i, p in enumerate(pieces):
        total = _f(p.out, fps)
        if p.kind == "copy":
            chains.append(f"[s{i}]trim=start_frame={_f(p.start, fps)}:end_frame={_f(p.end, fps)},{pts}[v{i}]")
        elif p.kind == "hold":
            fa = _f(p.start, fps)
            chains.append(f"[s{i}]trim=start_frame={max(0, fa - 1)}:end_frame={max(1, fa)},{pts},"
                          f"tpad=stop=-1:stop_mode=clone,trim=end_frame={total},{pts}[v{i}]")
        else:
            one_pass = _f(sum((c.end - c.start) * c.factor for c in p.chunks), fps) if p.loops > 1 else total
            per = _chunk_frames(p.chunks, one_pass, fps)
            k = len(p.chunks)
            chains.append(f"[s{i}]split={k}" + "".join(f"[s{i}_{j}]" for j in range(k)) if k > 1 else f"[s{i}]null[s{i}_0]")
            for j, (c, frames) in enumerate(zip(p.chunks, per)):
                stretch = (f"setpts=(PTS-STARTPTS)*{c.factor:.6f},{interpolation(interpolator, fps)},"
                           if abs(c.factor - 1) > 1e-6 else "setpts=PTS-STARTPTS,")
                chains.append(f"[s{i}_{j}]trim=start_frame={_f(c.start, fps)}:end_frame={_f(c.end, fps)},{stretch}"
                              f"tpad=stop=-1:stop_mode=clone,trim=end_frame={max(1, frames)},{pts}[c{i}_{j}]")
            joined = "".join(f"[c{i}_{j}]" for j in range(k))
            passes = f"[w{i}]" if p.loops > 1 else f"[v{i}]"
            chains.append(f"{joined}concat=n={k}:v=1:a=0,{pts}{passes}" if k > 1 else f"[c{i}_0]null{passes}")
            if p.loops > 1:
                chains.append(f"[w{i}]split={p.loops}" + "".join(f"[l{i}_{j}]" for j in range(p.loops)))
                for j in range(p.loops):
                    if j % 2:
                        chains.append(f"[l{i}_{j}]reverse,{pts}[m{i}_{j}]")
                    else:
                        chains.append(f"[l{i}_{j}]null[m{i}_{j}]")
                chains.append("".join(f"[m{i}_{j}]" for j in range(p.loops))
                              + f"concat=n={p.loops}:v=1:a=0,trim=end_frame={total},{pts}[v{i}]")
        outs.append(f"[v{i}]")
    chains.append(f"{''.join(outs)}concat=n={n}:v=1:a=0,{pts}[v]")
    return ";".join(chains)


def _fade(x: np.ndarray) -> np.ndarray:
    fade = min(round(CROSSFADE * OUT_RATE), len(x) // 2)
    if fade:
        ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))[:, None]
        x = x.copy()
        x[:fade] *= ramp
        x[-fade:] *= ramp[::-1]
    return x


def _room_tone(window: np.ndarray, samples: int) -> np.ndarray:
    """The quietest fifth of the window, tiled to `samples`: the room under an added line."""
    if len(window) == 0 or samples <= 0:
        return np.zeros((samples, window.shape[1] if window.ndim == 2 else 1), dtype=np.float32)
    frame = max(1, OUT_RATE // 50)
    count = len(window) // frame
    if count < 5:
        return np.resize(window, (samples, window.shape[1]))
    frames = window[: count * frame].reshape(count, frame, -1)
    levels = np.sqrt((frames ** 2).mean(axis=(1, 2)))
    quiet = frames[np.argsort(levels)[: max(1, count // 5)]].reshape(-1, window.shape[1])
    return np.resize(quiet, (samples, window.shape[1]))


def _exact(x: np.ndarray, samples: int, channels: int) -> np.ndarray:
    if len(x) >= samples:
        return x[:samples]
    return np.vstack([x, np.zeros((samples - len(x), channels), dtype=np.float32)])


def assemble(base: np.ndarray, pieces: Sequence[retime.Piece]) -> np.ndarray:
    """The soundtrack, piece by piece, each the exact length of its picture.
    `base` is the source's audio with the replaced spans already spliced."""
    channels = base.shape[1]
    cache: dict[str, np.ndarray] = {}

    def audio_of(edit) -> np.ndarray:
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        return cache[edit.audio.sha256]

    parts = []
    for p in pieces:
        samples = round(p.out * OUT_RATE)
        i0, i1 = min(round(p.start * OUT_RATE), len(base)), min(round(p.end * OUT_RATE), len(base))
        if p.kind == "copy":
            parts.append(_exact(base[i0:i1], samples, channels))
        elif p.kind == "flex" and p.edit is not None:
            take = _exact(audio_of(p.edit), samples, channels)
            # The same equal-power seams as a splice, against the original at the span's edges.
            fade = min(round(CROSSFADE * OUT_RATE), samples // 2, max(0, i1 - i0) // 2)
            if fade:
                ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))[:, None]
                old = np.sqrt(np.maximum(0.0, 1.0 - ramp ** 2))
                take = take.copy()
                take[:fade] = take[:fade] * ramp + base[i0:i0 + fade] * old
                take[-fade:] = take[-fade:] * ramp[::-1] + base[i1 - fade:i1] * old[::-1]
            parts.append(take)
        elif p.kind == "living" and p.edit is not None:
            window = base[i0:i1]
            line = _fade(audio_of(p.edit))
            under = _room_tone(window, len(line))
            spoken = under + line
            seq = np.vstack([spoken, window]) if p.line_first else np.vstack([window, spoken])
            parts.append(_exact(seq, samples, channels))
        elif p.kind == "hold" and p.edit is not None:
            parts.append(_exact(_fade(audio_of(p.edit)), samples, channels))
        else:
            parts.append(np.zeros((samples, channels), dtype=np.float32))
    return np.vstack(parts) if parts else base[:0]


def compose(
    source: Source,
    segments: Sequence[RenderSegment],
    dest: str | Path,
    use_generated_frames: bool = False,
    inserts: Sequence[RenderInsert] = (),
    pieces: Sequence[retime.Piece] | None = None,
    interpolator: str = "minterpolate",
) -> Path:
    """Write the edited video to `dest` (MP4, H.264 + AAC).

    With `pieces` (Phase 16) the picture and sound are assembled from them;
    with only `inserts` every added line is a plain hold, as before."""
    if use_generated_frames:
        raise NotImplementedError("Compositing generated frames arrives with real lip-sync (Phase 5).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fps = ffmpeg.frame_rate(source.media.path)
    if pieces is None:
        special = retime.plain_holds(inserts, source.duration) if inserts else []
        pieces = retime.tile(source.duration, special, fps) if special else None
    reencode = ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast", "-crf", "18"]
    plain = pieces is None or all(p.kind == "copy" for p in pieces)
    if not plain:
        video_map = ["-filter_complex", video_graph(pieces, fps, interpolator), "-map", "[v]", *reencode]
    elif _video_codec(source.media.path) in _COPYABLE_VIDEO:
        video_map = ["-map", "0:v:0", "-c:v", "copy"]
    else:
        video_map = ["-map", "0:v:0", *reencode]
    # Flexed spans take their audio from their piece, not the splice.
    flexed = {p.edit.edit_id for p in (pieces or ()) if p.kind == "flex" and p.edit is not None}
    spliced = splice(decode(source.media.path), [s for s in segments if not (s.edit and s.edit.edit_id in flexed)])
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        _write(audio, assemble(spliced, pieces) if not plain else spliced)
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN,
            "-i", str(source.media.path), "-i", str(audio),
            *video_map, "-map", "1:a:0",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart", *ffmpeg._BITEXACT_OUT, str(dest),
        ])
    return dest
