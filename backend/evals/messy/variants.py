"""The 20 messy variants, made from `evals/clips/chai.mp4` (five lines, two
speakers, exact word times in `evals/clips/transcripts.json`).

Everything is synthesised so a build needs no download and is the same every
time: the music is an ffmpeg expression (a four-chord loop with a melody in the
speech band and a kick), the cafe is pink noise, unintelligible babble (the
clip's own speech reversed and pitched) and cup clinks, the rooms are
exponentially decaying noise impulse responses, the phone is a 300 to 3400 Hz
band at 8 kHz through mu-law. Interferers are mixed in numpy at a stated level
against the clip's speech, so "music at -6 dB" means exactly that.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import wave
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from evals import clips

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
RATE = 48000

# The four-chord loop: root steps 0, 5, 7, 3 semitones over A2, two seconds each,
# a third, a fifth and a melody two octaves up that pulses at 4 Hz, and a kick
# every half second. The melody sits where voices sit, which is what makes music hard.
MUSIC = ("st(0,mod(floor(t/2),4));"
         "st(1,110*pow(2,if(eq(ld(0),0),0,if(eq(ld(0),1),5,if(eq(ld(0),2),7,3)))/12));"
         "0.30*sin(2*PI*ld(1)*t)+0.20*sin(2*PI*ld(1)*1.26*t)+0.20*sin(2*PI*ld(1)*1.5*t)"
         "+0.25*sin(2*PI*ld(1)*4*(1+0.125*mod(floor(t*4),3))*t)*(0.5+0.5*sin(2*PI*4*t))"
         "+0.50*sin(2*PI*55*t)*exp(-18*mod(t,0.5))")
# Kick and hats forward: a dance bed.
BEAT = ("0.9*sin(2*PI*50*t)*exp(-14*mod(t,0.5))"
        "+0.25*(2*random(0)-1)*exp(-60*mod(t+0.25,0.5))"
        "+0.15*sin(2*PI*220*pow(2,mod(floor(t),4)/12)*t)")
CLINKS = "0.6*sin(2*PI*3100*t)*exp(-40*mod(t,1.7))*gt(mod(t,3.4),1.7)+0.4*sin(2*PI*4200*t)*exp(-50*mod(t+0.6,2.3))"


@dataclass(frozen=True)
class Variant:
    name: str
    family: str          # music, noise, echo, overlap, phone, clipped, combo, control
    what: str            # one plain sentence for the report
    music_db: float | None = None     # bed level against the speech, dB
    beat: bool = False
    cafe_db: float | None = None
    babble_db: float | None = None
    hum_db: float | None = None
    rt60: float | None = None
    wet_only: bool = False
    overlap: tuple[tuple[int, float, float], ...] = ()   # (line index, at seconds, level dB)
    phone: bool = False
    dropouts: bool = False
    clip_db: float | None = None
    bed: bool = field(default=False)  # has a music or noise bed a separation should keep


VARIANTS: tuple[Variant, ...] = (
    Variant("clean", "control", "The chai clip as made.", bed=False),
    Variant("music_soft", "music", "Music bed 20 dB under the speech.", music_db=-20, bed=True),
    Variant("music_mid", "music", "Music bed 12 dB under the speech.", music_db=-12, bed=True),
    Variant("music_loud", "music", "Music bed 6 dB under the speech.", music_db=-6, bed=True),
    Variant("music_beat_loud", "music", "A dance beat 4 dB under the speech.", music_db=-4, beat=True, bed=True),
    Variant("cafe_light", "noise", "Cafe noise 20 dB under the speech.", cafe_db=-20, bed=True),
    Variant("cafe_heavy", "noise", "Cafe noise 6 dB under the speech.", cafe_db=-6, bed=True),
    Variant("babble", "noise", "Crowd babble 8 dB under the speech.", babble_db=-8, cafe_db=-24, bed=True),
    Variant("hum_hiss", "noise", "Mains hum and hiss 14 dB under the speech.", hum_db=-14, bed=True),
    Variant("echo_small", "echo", "A small room, RT60 0.4 s.", rt60=0.4),
    Variant("echo_large", "echo", "A hall, RT60 1.2 s.", rt60=1.2),
    Variant("echo_far", "echo", "Far from the mic: mostly reverb, RT60 0.9 s.", rt60=0.9, wet_only=True),
    Variant("crosstalk_brief", "overlap", "A second voice talks over the end of line 1.", overlap=((3, 1.2, -6),)),
    Variant("crosstalk_heavy", "overlap", "Both speakers talk over each other twice, at the same level.",
            overlap=((3, 1.0, 0), (0, 7.4, 0))),
    Variant("phone", "phone", "Phone quality: 300 to 3400 Hz at 8 kHz, mu-law.", phone=True),
    Variant("phone_dropouts", "phone", "Phone quality with dropped packets.", phone=True, dropouts=True),
    Variant("phone_noisy", "phone", "Phone quality from a cafe.", phone=True, cafe_db=-10, bed=True),
    Variant("clipped_mild", "clipped", "Recorded 10 dB too hot: peaks clipped.", clip_db=10),
    Variant("clipped_hard", "clipped", "Recorded 22 dB too hot: heavily clipped.", clip_db=22),
    Variant("music_echo", "combo", "Music bed 10 dB under, in a hall (RT60 1.0 s).", music_db=-10, rt60=1.0, bed=True),
    Variant("everything", "combo", "Music, cafe, a room and a phone at once.", music_db=-12, cafe_db=-14, rt60=0.6,
            phone=True, bed=True),
)
MESSY = tuple(v for v in VARIANTS if v.family != "control")


def truth() -> dict:
    """The chai clip's words and lines as made: [text, start, end, speaker]."""
    known = json.loads((clips.CLIPS / "transcripts.json").read_text())
    return next(v for v in known.values() if v["clip"] == "chai.mp4")


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768.0


def write_wav(path: Path, x: np.ndarray, rate: int = RATE) -> None:
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm.tobytes())


def _decode(src: Path, tmp: Path, name: str, af: str | None = None) -> np.ndarray:
    dest = tmp / f"{name}.wav"
    _ff("-i", str(src), *(["-af", af] if af else []), "-vn", "-ac", "1", "-ar", str(RATE), "-c:a", "pcm_s16le", str(dest))
    return read_wav(dest)


def _synth(tmp: Path, name: str, expr: str, seconds: float) -> np.ndarray:
    dest = tmp / f"{name}.wav"
    _ff("-f", "lavfi", "-i", f"aevalsrc='{expr}':s={RATE}:d={seconds:.3f}", "-ac", "1", "-c:a", "pcm_s16le", str(dest))
    return read_wav(dest)


def _noise(tmp: Path, name: str, color: str, seed: int, seconds: float, af: str = "") -> np.ndarray:
    dest = tmp / f"{name}.wav"
    src = f"anoisesrc=c={color}:r={RATE}:a=0.5:d={seconds:.3f}:s={seed}"
    _ff("-f", "lavfi", "-i", src, *(["-af", af] if af else []), "-ac", "1", "-c:a", "pcm_s16le", str(dest))
    return read_wav(dest)


def speech_rms(x: np.ndarray) -> float:
    """RMS over the frames that hold speech (within 30 dB of the loudest)."""
    frame = RATE // 50
    n = len(x) // frame
    rms = np.sqrt(np.mean(x[: n * frame].reshape(n, frame) ** 2, axis=1) + 1e-12)
    db = 20 * np.log10(rms)
    active = db > db.max() - 30
    return float(np.sqrt(np.mean(rms[active] ** 2)))


def _at(x: np.ndarray, level_db: float, ref: float, n: int) -> np.ndarray:
    x = np.resize(x, n)
    r = float(np.sqrt(np.mean(x ** 2))) or 1.0
    return x * (ref * 10 ** (level_db / 20) / r)


def _impulse(rt60: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    t = np.arange(int(RATE * rt60 * 1.2)) / RATE
    ir = rng.standard_normal(t.size) * np.exp(-6.91 * t / rt60)
    ir[:int(RATE * 0.004)] *= np.linspace(0, 1, int(RATE * 0.004))
    return ir / np.sqrt(np.sum(ir ** 2))


def _reverb(x: np.ndarray, rt60: float, wet_only: bool) -> np.ndarray:
    wet = np.convolve(x, _impulse(rt60, 7))[: len(x)]
    out = wet + (0.25 if wet_only else 1.0) * x
    return out * (speech_rms(x) / speech_rms(out))


def _phone(x: np.ndarray, tmp: Path, dropouts: bool) -> np.ndarray:
    src = tmp / "phone_in.wav"
    write_wav(src, x)
    mu = tmp / "phone.wav"
    _ff("-i", str(src), "-af", "highpass=f=300,lowpass=f=3400,acompressor=threshold=0.1:ratio=4,aresample=8000",
        "-c:a", "pcm_mulaw", "-ar", "8000", str(mu))
    y = _decode(mu, tmp, "phone_back")[: len(x)]
    y = np.pad(y, (0, max(0, len(x) - len(y))))
    if dropouts:
        rng = np.random.default_rng(11)
        hop = int(0.02 * RATE)
        for i in range(0, len(y), hop):
            if rng.random() < 0.06:
                y[i:i + hop * int(rng.integers(1, 5))] = 0.0
    return y


def make(v: Variant, base: np.ndarray, tmp: Path) -> np.ndarray:
    n, ref = len(base), speech_rms(base)
    seconds = n / RATE + 0.1
    x = base.copy()
    lines = truth()["statements"]
    for line, at, level in v.overlap:
        _, s, e, _ = lines[line]
        piece = base[int(s * RATE): int(e * RATE)] * 10 ** (level / 20)
        i = int(at * RATE)
        x[i: i + len(piece)] += piece[: max(0, n - i)]
    if v.rt60:
        x = _reverb(x, v.rt60, v.wet_only)
    if v.music_db is not None:
        x += _at(_synth(tmp, "music", BEAT if v.beat else MUSIC, seconds), v.music_db, ref, n)
    if v.cafe_db is not None:
        cafe = _noise(tmp, "pink", "pink", 3, seconds, "lowpass=f=5000")
        cafe = cafe + 0.3 * _synth(tmp, "clinks", CLINKS, seconds)[: len(cafe)]
        x += _at(cafe, v.cafe_db, ref, n)
    if v.babble_db is not None:
        talk = tmp / "talk.wav"
        write_wav(talk, base)
        babble = sum(np.resize(_decode(talk, tmp, f"b{k}", f"areverse,asetrate={RATE * f:.0f},aresample={RATE},adelay={d}"), n)
                     for k, (f, d) in enumerate(((1.08, 0), (0.93, 700), (1.17, 1900), (0.86, 3100))))
        x += _at(np.resize(babble, n), v.babble_db, ref, n)
    if v.hum_db is not None:
        t = np.arange(n) / RATE
        hum = np.sin(2 * np.pi * 50 * t) + 0.5 * np.sin(2 * np.pi * 150 * t) + 0.25 * np.sin(2 * np.pi * 250 * t)
        x += _at(hum, v.hum_db, ref, n) + _at(_noise(tmp, "hiss", "white", 5, seconds), v.hum_db - 4, ref, n)
    if v.phone:
        x = _phone(x, tmp, v.dropouts)
    if v.clip_db is not None:
        x = np.clip(x * 10 ** (v.clip_db / 20), -1.0, 1.0) * 10 ** (-3 / 20)
    peak = float(np.max(np.abs(x))) or 1.0
    return x * (0.97 / peak) if peak > 0.97 else x


def path_of(v: Variant) -> Path:
    return OUT / f"{v.name}.mp4"


def build(only: list[str] | None = None) -> list[Path]:
    """Write every variant as an mp4 (the chai picture, the messy sound) and
    `out/truth.json` (the clean words and lines every variant is scored on)."""
    OUT.mkdir(parents=True, exist_ok=True)
    chai = clips.path("chai.mp4")
    made = []
    with tempfile.TemporaryDirectory() as t:
        tmp = Path(t)
        base = _decode(chai, tmp, "base")
        for v in VARIANTS:
            if only and v.name not in only:
                continue
            audio = tmp / f"{v.name}.wav"
            write_wav(audio, make(v, base, tmp))
            _ff("-i", str(chai), "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                "-c:a", "aac", "-b:a", "128k", "-shortest", str(path_of(v)))
            made.append(path_of(v))
    (OUT / "truth.json").write_text(json.dumps(truth(), indent=1))
    return made
