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
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

from app.domain.models import Source, role_of
from app.media import ffmpeg, loudness, room as roommod
from app.render import check as checkmod, clean, mix as mixmod
from app.media.stems import Stems
from app.render import retime
from app.render.renderer import RenderInsert, RenderSegment

OUT_RATE = 48000
CROSSFADE = 0.02     # seconds per seam
AUDIO_BITRATE = "192k"
SILENT_BED_DB = -60.0  # an accompaniment quieter than this is no bed at all
# Codecs that play in every browser inside MP4. Anything else is re-encoded.
# Codecs whose picture an MP4 can carry as it is: an unretimed render copies them
# instead of re-encoding. HEVC (phones, WhatsApp; 8K in one bug report) re-encoded
# took minutes; copied, it takes as long as the audio.
_COPYABLE_VIDEO = {"h264", "hevc"}
_COPY_TAG = {"hevc": ["-tag:v", "hvc1"]}


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


@dataclass(frozen=True)
class Room:
    """What 15c knows about the original: the bed under the voice and the
    voice's own room, ready to put on a new take."""
    accompaniment: np.ndarray            # (samples, channels), the length of the source audio
    profile: roommod.RoomProfile | None  # None: a dry voice (no tail to read); the bed still plays
    context: np.ndarray                  # the speaker's separated vocals

    @classmethod
    def prepare(cls, stems: Stems | None, channels: int, samples: int) -> Room | None:
        """None, so the render stays exactly as without stems, when there are
        no stems or no audible bed. Run 5 item 8: a dry voice (a lavalier or a
        voice-over, no reverb tail to read) used to return None here too, and
        the music under a replaced line dropped out; now the bed stays and only
        the reverb match is skipped."""
        if stems is None:
            return None
        try:
            bed = _exact(decode(stems.accompaniment, channels=channels), samples, channels)
            vocals = _exact(decode(stems.vocals, channels=channels), samples, channels)
        except Exception:  # noqa: BLE001 - a bad stem file just means no room matching
            return None
        rms = float(np.sqrt(np.mean(bed.astype(np.float64) ** 2))) if bed.size else 0.0
        if rms < 10 ** (SILENT_BED_DB / 20):
            return None
        profile = roommod.estimate_reverb(vocals, OUT_RATE)
        return cls(bed, profile, vocals.mean(axis=1))

    def take(self, audio: np.ndarray) -> np.ndarray:
        """A generated take in the speaker's room and spectrum."""
        wet = roommod.match_room(audio, self.profile, OUT_RATE) if self.profile is not None else audio
        return roommod.spectral_match(wet, self.context, OUT_RATE).astype(np.float32)


def unity(edit) -> float:
    """Every line as voiced. The mix (render.mix) sets real levels by role."""
    return 1.0


def _join_envelope(old: np.ndarray, new: np.ndarray) -> np.ndarray:
    """The take's weight over a replaced span (mono `old` and `new`, alike in
    length): 0 before the snapped start join, 1 inside, 0 after the snapped end
    join, with 10 to 30 ms sine ramps (`render.clean`)."""
    length = len(new)
    env = np.zeros(length, dtype=np.float32)
    if length <= 0:
        return env
    limit = min(round(clean.SNAP * OUT_RATE), length // 4)
    a = clean.snap(old, new, 0, +1, limit)
    b = clean.snap(old, new, length - 1, -1, limit) + 1
    if b - a < 2:
        a, b = 0, length
    w = round(clean.JOIN_MAX * OUT_RATE)
    fa = min(clean.fade_length(old[a:a + w], new[a:a + w], OUT_RATE), (b - a) // 2)
    fb = min(clean.fade_length(old[max(a, b - w):b], new[max(a, b - w):b], OUT_RATE), (b - a) // 2)
    env[a:b] = 1.0
    if fa:
        env[a:a + fa] = np.sin(np.linspace(0, np.pi / 2, fa, dtype=np.float32))
    if fb:
        env[b - fb:b] = np.minimum(env[b - fb:b], np.sin(np.linspace(0, np.pi / 2, fb, dtype=np.float32))[::-1])
    return env


def splice(
    base: np.ndarray, segments: Sequence[RenderSegment], room: Room | None = None,
    layers: Sequence = (),
    gain_for=unity,
) -> np.ndarray:
    """Replace each edited span of `base` with its edit's audio, crossfaded,
    then mix every layer over the result at its own level (20h): layers add
    to whatever plays there, so any number coexist at one moment.

    With a `room`, a replaced span becomes the room-matched take over the
    original's accompaniment: the voice part of the original (what is left of
    `base` once the bed is taken away) fades out, the take fades in, and the
    bed plays throughout. At the span's edges that is exactly `base`, so the
    seams are as before and nothing outside a span is touched."""
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
        # Run 5 item 7: a take put in the room when it was made is not put there twice.
        if room is not None and edit.plan.mix != "layer" and not getattr(edit.plan, "roomed", None):
            piece = room.take(piece)
        if edit.plan.mix == "layer":
            # A layer that still arrives as a segment (an older manifest): add it, never replace.
            fade = min(round(CROSSFADE * OUT_RATE), length // 2)
            new = np.ones(length, dtype=np.float32)
            if fade:
                ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))
                new[:fade] = ramp
                new[-fade:] = ramp[::-1]
            out[i0:i1] = out[i0:i1] + piece * new[:, None]
            continue
        # Addendum 3, item 1: the voice part of the original fades out and the
        # take in, at joins snapped to a zero crossing or silence, with a 10 to
        # 30 ms equal-power crossfade; the room's tone plays under any part of
        # the take quieter than the room. With stems the bed plays throughout.
        bed = room.accompaniment[i0:i1] if room is not None else None
        voice_old = base[i0:i1] - bed if bed is not None else base[i0:i1]
        new = _join_envelope(voice_old.mean(axis=1), piece.mean(axis=1))
        old = np.sqrt(np.maximum(0.0, 1.0 - new ** 2))  # equal power
        reach = int(clean.ROOM_READ * OUT_RATE)
        lo, hi = max(0, i0 - reach), min(len(base), i1 + reach)
        talk = base[lo:hi] - room.accompaniment[lo:hi] if room is not None else base[lo:hi]
        tone = clean.tone_around(talk.mean(axis=1), i0 - lo, i1 - lo, OUT_RATE)
        fill = clean.gap_fill(piece.mean(axis=1), tone, OUT_RATE)
        spoken = piece + fill[:, None]
        mixed_in = voice_old * old[:, None] + spoken * new[:, None]
        out[i0:i1] = (bed + mixed_in) if bed is not None else mixed_in
    for edit in layers:
        i0 = min(round(edit.plan.selection.start * OUT_RATE), len(out))
        i1 = min(round(edit.plan.selection.end * OUT_RATE), len(out))
        length = i1 - i0
        if length <= 0:
            continue
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        piece = cache[edit.audio.sha256][:length]
        if len(piece) < length:
            piece = np.pad(piece, ((0, length - len(piece)), (0, 0)))
        if gain_for(edit) != 1.0:
            piece = piece * gain_for(edit)
        fade = min(round(CROSSFADE * OUT_RATE), length // 2)
        new = np.ones(length, dtype=np.float32)
        if fade:
            ramp = np.sin(np.linspace(0, np.pi / 2, fade, dtype=np.float32))
            new[:fade] = ramp
            new[-fade:] = ramp[::-1]
        out[i0:i1] = out[i0:i1] + piece * new[:, None]
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


def assemble(base: np.ndarray, pieces: Sequence[retime.Piece], gain_for=None) -> np.ndarray:
    """The soundtrack, piece by piece, each the exact length of its picture.
    `base` is the source's audio with the replaced spans already spliced."""
    channels = base.shape[1]
    cache: dict[str, np.ndarray] = {}

    def audio_of(edit) -> np.ndarray:
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        g = gain_for(edit, cache[edit.audio.sha256]) if gain_for else 1.0
        return cache[edit.audio.sha256] * g if g != 1.0 else cache[edit.audio.sha256]

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


def placed_edits(segments: Sequence[RenderSegment], layers: Sequence, pieces: Sequence[retime.Piece] | None,
                 audio_of) -> list[checkmod.Placed]:
    """Every edit as the render plays it, for `render.check`: its span, its
    take as it sounds there (mono), and how much of the take's sound its span
    cut off. `audio_of(edit)` is the take at OUT_RATE, (samples, channels)."""
    flexed = {p.edit.edit_id: p for p in (pieces or ()) if p.kind == "flex" and p.edit is not None}
    out: list[checkmod.Placed] = []

    def one(edit, kind: str, a: float, b: float, offset: int, length: int) -> checkmod.Placed:
        audio = audio_of(edit).mean(axis=1)
        peak = float(checkmod._frame_db(audio, OUT_RATE).max()) if len(audio) >= OUT_RATE // 100 else None
        head, take, tail = audio[:max(0, offset)], audio[max(0, offset):max(0, offset) + length], audio[max(0, offset) + length:]
        return checkmod.Placed(
            edit.edit_id, kind, edit.plan.new_text or "", a, b, take,
            lost_head=checkmod.sound_seconds(head, OUT_RATE, peak) if peak is not None else 0.0,
            lost_tail=checkmod.sound_seconds(tail, OUT_RATE, peak) if peak is not None else 0.0,
            voice=role_of(edit.plan) == "voice" and kind != "remove")

    for seg in segments:
        if seg.kind != "edited" or seg.edit is None or seg.end <= seg.start:
            continue
        edit = seg.edit
        kind = "remove" if edit.plan.mix == "remove" else "layer" if edit.plan.mix == "layer" else "replace"
        if edit.edit_id in flexed:
            piece = flexed[edit.edit_id]
            out.append(one(edit, kind, piece.start, piece.end, 0, round(piece.out * OUT_RATE)))
            continue
        offset = round((seg.start - edit.plan.selection.start) * OUT_RATE)
        out.append(one(edit, kind, seg.start, seg.end, offset, round((seg.end - seg.start) * OUT_RATE)))
    for edit in layers:
        a, b = edit.plan.selection.start, edit.plan.selection.end
        if b > a:
            out.append(one(edit, "layer", a, b, 0, round((b - a) * OUT_RATE)))
    return out


def compose(
    source: Source,
    segments: Sequence[RenderSegment],
    dest: str | Path,
    use_generated_frames: bool = False,
    inserts: Sequence[RenderInsert] = (),
    pieces: Sequence[retime.Piece] | None = None,
    interpolator: str = "minterpolate",
    stems: Stems | None = None,
    layers: Sequence = (),
    mix_settings: mixmod.MixSettings | None = None,
    words: Sequence[tuple[float, float]] = (),
    lines: Sequence[tuple[float, float]] = (),
    on_mix=None,
    on_check=None,
) -> Path:
    """Write the edited video to `dest` (MP4, H.264 + AAC).

    With `pieces` (Phase 16) the picture and sound are assembled from them;
    with only `inserts` every added line is a plain hold, as before.

    With `stems` (Phase 15c: `media.stems.separate` of the source's audio) each
    replaced span keeps the original's accompaniment under a take matched to
    the speaker's room. Flexed, living and held lines are as before. Without
    stems, with a silent bed, or with too little speech to hear the room, the
    audio is exactly what it is without this argument."""
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
    elif (codec := _video_codec(source.media.path)) in _COPYABLE_VIDEO:
        video_map = ["-map", "0:v:0", "-c:v", "copy", *_COPY_TAG.get(codec or "", [])]
    else:
        video_map = ["-map", "0:v:0", *reencode]
    # Flexed spans take their audio from their piece, not the splice.
    flexed = {p.edit.edit_id for p in (pieces or ()) if p.kind == "flex" and p.edit is not None}
    original = decode(source.media.path)
    room = Room.prepare(stems, original.shape[1], len(original))
    spliced = splice(original, [s for s in segments if not (s.edit and s.edit.edit_id in flexed)], room)
    # 2026-10-20: added lines are mixed by role, against the clip's own speech
    # (render.mix): voices at its loudness, beds under them and ducking, the
    # original's music dipping under an added voice; then the whole mix at the
    # export loudness with a true-peak ceiling.
    settings = mix_settings or mixmod.MixSettings()
    channels = original.shape[1]
    cache: dict[str, np.ndarray] = {}

    def audio_of(edit) -> np.ndarray:
        if edit.audio.sha256 not in cache:
            cache[edit.audio.sha256] = decode(edit.audio.path, channels=channels)
        return cache[edit.audio.sha256]

    mixed = mixmod.mix(spliced, layers, audio_of, words, settings,
                       bed=room.accompaniment if room is not None else None, lines=lines)

    def gain_for(edit, audio) -> float:
        if (edit.plan.mix in ("replace", "remove") and edit.plan.role is None) or mixmod.as_shot(edit):
            return 1.0
        return mixed.gains.get(edit.edit_id) or loudness.gain(mixmod.standalone_gain_db(edit, audio, mixed.voice_lufs, settings))

    track = assemble(mixed.audio, pieces, gain_for) if not plain else mixed.audio
    final_lufs = None
    if settings.export_lufs is not None:
        normalised, final_lufs = loudness.normalize(track, settings.export_lufs, settings.true_peak_db)
        track = normalised.astype(np.float32)
    if on_check is not None:
        # Addendum 3, item 1: the finished soundtrack, the original, and every
        # edit as it was placed, for the check after the render (render.check).
        out_time = (lambda t: t) if plain else (lambda t: retime.render_time(t, pieces))
        on_check(track, original, placed_edits(segments, layers, pieces, audio_of), out_time)
    if on_mix is not None:
        on_mix({"voice_lufs": round(mixed.voice_lufs, 1), "lines": [r.as_dict() for r in mixed.reports],
                "loudness_lufs": None if final_lufs is None else round(final_lufs, 1),
                "true_peak_db": round(loudness.true_peak_db(track), 1) if len(track) else None})
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / "audio.wav"
        _write(audio, track)
        ffmpeg._run(ffmpeg.FFMPEG, [
            "-y", "-loglevel", "error", *ffmpeg._BITEXACT_IN,
            "-i", str(source.media.path), "-i", str(audio),
            *video_map, "-map", "1:a:0",
            "-c:a", "aac", "-b:a", AUDIO_BITRATE,
            "-movflags", "+faststart", *ffmpeg._BITEXACT_OUT, str(dest),
        ])
    return dest
