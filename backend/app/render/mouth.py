"""Moving the mouth in the export (Phase 17b/c).

For each approved line that replaced speech, find the stretches of the picture
where a face is on screen (`media.faces`, split at the cuts), send just those
seconds with the take's audio to the lip-sync vendor, and patch what comes back
into the source's picture, frame for frame. Everything else is the source's own
frames, and the audio is untouched: the patched file keeps the original's
soundtrack, so the compositor treats it exactly like the source.

Why at export and not at preview: a take is previewed and re-rolled many
times, and the editor plays only its audio, so a mouth made then would be paid
for and never seen. At export only approved lines are sent, each stretch once
(cached by take), and the project's spending ceiling decides what is affordable.
A vendor failure never fails the export: the stretch keeps its original picture
and the result says why.
"""
from __future__ import annotations

import hashlib
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.adapters.sync_so import (
    DEFAULT_MODEL, MouthConfigError, MouthError, MouthRefused, SyncSoClient,
)
from app.domain.models import Source
from app.media import faces, ffmpeg
from app.render.renderer import RenderSegment

# A scene score this sensitive finds the soft cuts of a fast montage; sending a
# stretch with a hidden cut in it gives the model two people to draw one mouth on.
CUT_THRESHOLD = 0.15
# sync.so's list prices per second of video (2026-10-14), used only when its own
# estimate endpoint will not answer.
MAX_PARALLEL = 4          # stretches in flight at once; each is about a minute at the vendor
USD_PER_SECOND = {"lipsync-2": 0.06, "lipsync-2-pro": 0.10, "sync-3": 0.16}


@dataclass(frozen=True)
class Moved:
    edit_id: str
    start: float          # source time, seconds
    end: float
    model: str
    usd: float            # what this stretch cost (0 when it came from the cache)
    cached: bool
    clip: Path


@dataclass(frozen=True)
class MouthResult:
    video: Path | None            # the source picture with new mouths patched in; None if nothing moved
    moved: tuple[Moved, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def seconds(self) -> float:
        return sum(m.end - m.start for m in self.moved)

    @property
    def usd(self) -> float:
        return sum(m.usd for m in self.moved)


def _key(source: Source, audio_sha: str, offset: float, start: float, end: float, model: str) -> str:
    raw = f"{source.media.sha256}|{audio_sha}|{offset:.3f}|{start:.3f}|{end:.3f}|{model}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


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


def patch_video(source_path: Path, moved: Sequence[Moved], dest: Path) -> Path:
    """The source's picture with each moved stretch's frames laid in, frame
    for frame, and its soundtrack copied through untouched."""
    info = ffmpeg.probe(source_path)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    width, height = int(video["width"]), int(video["height"])
    fps = ffmpeg.frame_rate(source_path)
    total = round(float(info["format"]["duration"]) * fps)
    ordered = sorted(moved, key=lambda m: m.start)
    spans = [(round(m.start * fps), round(m.end * fps)) for m in ordered]
    inputs: list[str] = ["-i", str(source_path)]
    for m in ordered:
        inputs += ["-i", str(m.clip)]
    dest.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", *inputs,
        "-filter_complex", patch_graph(spans, total, width, height, fps),
        "-map", "[v]", "-map", "0:a?", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
        "-crf", "16", "-c:a", "copy", "-movflags", "+faststart", str(dest),
    ])
    return dest


class MouthRenderer:
    def __init__(
        self, client: SyncSoClient, cache_dir: Path, *, model: str = DEFAULT_MODEL,
        afford: Callable[[float], bool] = lambda usd: True,
        record: Callable[[float, float, str], None] = lambda usd, seconds, model: None,
        stretches: Callable[..., list[faces.Stretch]] | None = None,
    ) -> None:
        self._client = client
        self._cache = Path(cache_dir)
        self._model = model
        self._afford = afford
        self._record = record
        self._stretches = stretches or faces.stretches      # looked up now, so a test can stand one in

    def apply(self, source: Source, segments: Sequence[RenderSegment], cuts: Sequence[float]) -> MouthResult:
        """Move the mouth where an approved replacement has a face on screen.

        Cached stretches are free. The rest are checked against the spending
        limit one after another (so the ceiling holds however many there are)
        and then sent together: each takes about a minute at the vendor."""
        notes: list[str] = []
        todo: list[tuple[RenderSegment, faces.Stretch, float, Path, float]] = []   # seg, stretch, offset, clip, estimate
        slots: list[Moved | None] = []                                              # in order; filled as work finishes
        committed = 0.0
        for seg in segments:
            edit = seg.edit
            if seg.kind != "edited" or edit is None or edit.reverted or edit.plan.mix != "replace":
                continue
            for s in self._stretches(source.media.path, seg.start, seg.end, cuts):
                offset = s.start - edit.plan.selection.start     # where in the take this stretch begins
                clip = self._cache / f"{_key(source, edit.audio.sha256, offset, s.start, s.end, self._model)}.mp4"
                if clip.is_file():
                    slots.append(Moved(edit.edit_id, s.start, s.end, self._model, 0.0, True, clip))
                    continue
                estimate = (self._client.estimate(self._model, s.end - s.start)
                            or USD_PER_SECOND.get(self._model, 0.16) * (s.end - s.start))
                if not self._afford(committed + estimate):
                    notes.append(f"No mouth at {s.start:.1f} s: it would pass the project's spending limit.")
                    continue
                committed += estimate
                todo.append((seg, s, offset, clip, estimate))
                slots.append(None)

        blocked = threading.Event()                              # a key or plan problem: stop starting new calls

        def run(item) -> tuple[Moved | None, str | None]:
            seg, s, offset, clip, estimate = item
            if blocked.is_set():
                return None, None
            try:
                self._make(source, seg.edit, s, offset, clip)
            except MouthRefused as exc:
                return None, f"The mouth at {s.start:.1f} s was left as it was: {exc}"
            except MouthConfigError as exc:
                blocked.set()
                return None, f"The mouth could not be moved: {exc}"
            except MouthError:
                blocked.set()
                return None, "sync.so was unavailable, so the picture was left as it was; export again to retry."
            self._record(estimate, s.end - s.start, self._model)
            return Moved(seg.edit.edit_id, s.start, s.end, self._model, estimate, False, clip), None

        if todo:
            with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
                done = iter(pool.map(run, todo))
            for i, slot in enumerate(slots):
                if slot is None:
                    moved, note = next(done)
                    slots[i] = moved
                    if note and note not in notes:
                        notes.append(note)
        moved_all = tuple(m for m in slots if m is not None)
        return MouthResult(None, moved_all, tuple(notes))

    def _make(self, source: Source, edit, s: faces.Stretch, offset: float, dest: Path) -> None:
        """Cut the stretch and its slice of the take, send both, keep what comes back."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            clip, take = tmp / "clip.mp4", tmp / "take.wav"
            ffmpeg._run(ffmpeg.FFMPEG, [
                "-y", "-loglevel", "error", "-ss", f"{s.start:.3f}", "-t", f"{s.end - s.start:.3f}",
                "-i", str(source.media.path), "-an", "-c:v", "libx264", "-crf", "16",
                "-pix_fmt", "yuv420p", "-preset", "veryfast", str(clip),
            ])
            ffmpeg._run(ffmpeg.FFMPEG, [
                "-y", "-loglevel", "error", "-ss", f"{max(0.0, offset):.3f}", "-t", f"{s.end - s.start:.3f}",
                "-i", str(edit.audio.path), "-ar", "44100", "-ac", "1", "-c:a", "pcm_s16le", str(take),
            ])
            options = {"active_speaker_detection": {"auto_detect": True}} if s.faces > 1 else None
            out, _ = self._client.move_mouth(clip, take, tmp / "out.mp4", model=self._model, options=options)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(out.read_bytes())

    def patch(self, source: Source, result: MouthResult, dest: Path) -> MouthResult:
        """The same result with `video` set: the source picture with the moved stretches in."""
        if not result.moved:
            return result
        return MouthResult(patch_video(Path(source.media.path), result.moved, dest), result.moved, result.notes)
