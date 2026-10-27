"""Where someone might be speaking, so silence is never sent to be transcribed
(run 5, item 4).

Whisper invents speech on silence ("Thanks for watching", "謝謝觀看"); the
screens in `adapters/openai_whisper.py` catch most of it after the fact, and
this keeps the silence from being heard at all. It is a small energy and
spectral detector in numpy, nothing to download: a 20 ms frame counts as
speech when its energy in the speech band (300 to 3400 Hz) stands out from
the clip's own quietest tenth and from digital silence. Measuring only the
speech band keeps wind, rumble and a music bed's bass out of the decision.

It errs towards speech on purpose. A span it wrongly keeps costs a few cents
and still meets the screens after transcription; a span it wrongly drops is a
real line lost. So it only ever leaves out QUIET audio: silence, room tone, a
hiss. Anything louder than ALWAYS_HEARD_DB in the speech band is sent, so a
music or cafe bed goes to the transcriber whole and speech under it is never
judged by level here (run 5 item 8 found the app's own silence screen dropping
real lines under a loud bed, because the floor there IS the music; see
`tests/adapters/test_transcription_vad.py`).

Only the kept spans are sent, joined by a short silence, and every time in the
reply is mapped back to the original clip with `TimeMap`, to the sample.
"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

RATE = 16000
FRAME = 512                  # 32 ms window, so the speech band has a few bins
HOP = 160                    # 10 ms
BAND = (300.0, 3400.0)       # where speech carries its energy (telephone band)
OVER_FLOOR_DB = 4.0          # a frame stands out from the clip's quietest tenth by this much
FLOOR_PERCENTILE = 10
SILENT_DB = -60.0            # below this (band level, dBFS) nothing is speech
ALWAYS_HEARD_DB = -45.0      # above this (band level, dBFS) a frame is always sent
MIN_RUN = 0.10               # seconds of standing-out frames in a row to count
MERGE_GAP = 1.0              # pauses shorter than this stay inside one span
PAD = 0.30                   # kept around each span, for the words' edges and context
JOIN = 0.30                  # silence between spans in what is sent
MIN_SAVING = 2.0             # cut only when it leaves out at least this much (seconds)


Span = tuple[float, float]


def _band_levels_db(x: np.ndarray, rate: int) -> np.ndarray:
    if len(x) < FRAME:
        x = np.pad(x, (0, FRAME - len(x)))
    count = 1 + (len(x) - FRAME) // HOP
    index = np.arange(FRAME)[None, :] + HOP * np.arange(count)[:, None]
    frames = x[index].astype(np.float64) * np.hanning(FRAME)[None, :]
    spectrum = np.abs(np.fft.rfft(frames, axis=1)) ** 2
    freqs = np.fft.rfftfreq(FRAME, 1.0 / rate)
    band = (freqs >= BAND[0]) & (freqs <= BAND[1])
    # Parseval with the window's power, so a full-scale sine in band reads near 0 dB.
    power = 2 * spectrum[:, band].sum(axis=1) / (FRAME * np.sum(np.hanning(FRAME) ** 2))
    return 10 * np.log10(np.maximum(power, 1e-10))


def speech_spans(x: np.ndarray, rate: int = RATE) -> list[Span]:
    """The spans (seconds) where someone might be speaking, padded and merged.
    Empty for silence, a steady hum or a steady tone."""
    if len(x) == 0:
        return []
    duration = len(x) / rate
    levels = _band_levels_db(x, rate)
    floor = float(np.percentile(levels, FLOOR_PERCENTILE))
    # Never more than ALWAYS_HEARD_DB: over a loud bed (music, a cafe) the
    # whole bed is sent, and the screens after transcription decide.
    loud = (levels > min(floor + OVER_FLOOR_DB, ALWAYS_HEARD_DB)) & (levels > SILENT_DB)
    hop = HOP / rate
    runs: list[Span] = []
    start = None
    for i, on in enumerate(np.append(loud, False)):
        if on and start is None:
            start = i
        elif not on and start is not None:
            if (i - start) * hop >= MIN_RUN:
                runs.append((start * hop, i * hop + FRAME / rate))
            start = None
    spans: list[Span] = []
    for a, b in runs:
        a, b = max(0.0, a - PAD), min(duration, b + PAD)
        if spans and a - spans[-1][1] < MERGE_GAP:
            spans[-1] = (spans[-1][0], max(spans[-1][1], b))
        else:
            spans.append((a, b))
    return spans


@dataclass(frozen=True)
class TimeMap:
    """Times in the sent audio back to times in the clip. `pieces` holds
    (start in the clip, end in the clip, start in the sent audio)."""
    pieces: tuple[tuple[float, float, float], ...]

    def __call__(self, t: float) -> float:
        for i, (a, b, at) in enumerate(self.pieces):
            if t <= at + (b - a):
                if t >= at:
                    return a + (t - at)
                # In the silence before this piece: whichever side is nearer.
                if i == 0:
                    return a
                prev_end = self.pieces[i - 1][1]
                return prev_end if t - (at - JOIN) < JOIN / 2 else a
        return self.pieces[-1][1] if self.pieces else t


def read_wav(path: Path) -> np.ndarray:
    """A 16-bit mono WAV (what `ffmpeg.extract_audio` writes) as float32."""
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
        channels = w.getnchannels()
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return x.reshape(-1, channels).mean(axis=1) if channels > 1 else x


def write_wav(path: Path, x: np.ndarray, rate: int = RATE) -> Path:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return path


def cut(x: np.ndarray, spans: list[Span], rate: int = RATE) -> tuple[np.ndarray, TimeMap]:
    """The spans' audio joined by `JOIN` of silence, and the map back."""
    parts, pieces, at = [], [], 0
    gap = np.zeros(int(round(JOIN * rate)), dtype=np.float32)
    for i, (a, b) in enumerate(spans):
        lo, hi = int(round(a * rate)), min(len(x), int(round(b * rate)))
        if i:
            parts.append(gap)
            at += len(gap)
        parts.append(x[lo:hi])
        pieces.append((lo / rate, hi / rate, at / rate))
        at += hi - lo
    joined = np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)
    return joined, TimeMap(tuple(pieces))


def speech_only(audio_path: Path, dest: Path) -> tuple[Path, TimeMap | None, list[Span]]:
    """What to send for `audio_path`: the file itself when there is little
    silence to leave out (map None), else the speech spans written to `dest`.
    The spans come back too; none means there is nothing to send."""
    x = read_wav(audio_path)
    spans = speech_spans(x)
    if not spans:
        return audio_path, None, []
    kept = sum(b - a for a, b in spans)
    if len(x) / RATE - kept < MIN_SAVING:
        return audio_path, None, spans
    joined, mapping = cut(x, spans)
    return write_wav(dest, joined), mapping, spans


def map_times(payload: dict, mapping: TimeMap | None) -> dict:
    """A transcription reply with its segment, word and turn times moved back
    onto the original clip."""
    if mapping is None:
        return payload
    out = dict(payload)
    for key in ("segments", "words"):
        items = payload.get(key)
        if not items:
            continue
        moved = []
        for raw in items:
            item = dict(raw)
            try:
                start, end = mapping(float(raw["start"])), mapping(float(raw["end"]))
            except (KeyError, TypeError, ValueError):
                moved.append(item)
                continue
            item["start"], item["end"] = start, max(start, end)
            moved.append(item)
        out[key] = moved
    return out
