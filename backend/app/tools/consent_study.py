"""Run 4 item 2: the threshold study behind the consent gate's similarity bands.

    python -m app.tools.consent_study --out <scratch dir> --media <artifacts dir> \
        [--public frontend/public] [--manifest ../docs/cloning-consent-testset.json]

Builds a small test set from audio on this machine, scores every pair of clips
with the gate's own SIM-o (WavLM, app.continuity.similarity, local and free),
and prints the same-speaker and different-speaker score distributions with
the error rates at candidate thresholds. Nothing is sent anywhere: Whisper is
not called (the words rule is not what this measures; for a test pair the
transcript is the known text), and the clips stay in --out.

The clips (docs/cloning-consent.md has the why):
    say:<voice>     macOS `say` voices reading consent phrases and a longer
                    "source" passage: distinct speakers, generated here
    phone           a consent clip passed through a phone-like channel
                    (band-pass, noise, a low-rate Opus round trip), against
                    the clean source: the same person on a worse microphone
    media:<sha>     read-only clips from the dev database copy's artifacts:
                    ElevenLabs takes by voice id, a recorded voice sample, a
                    real speaker's video
    public          frontend/public/sample-ad.mp4
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from app.continuity import signals, similarity
from app.safety import consent

SAY_VOICES = ("Samantha", "Daniel", "Karen", "Moira", "Rishi", "Tara", "Aman", "Lekha",
              "Flo (English (US))", "Eddy (English (US))", "Reed (English (UK))", "Shelley (English (UK))")
SOURCE_TEXT = ("Thanks for coming by the shop today. Everything on the front table is fresh this morning, "
               "and the bread comes out of the oven at ten.")

# Read-only media from the dev database copy, by sha256 (the artifact store's
# file names). Speaker groups come from the candidates' voice ids and the
# recorded voice's sample (meta my_voices:local).
MEDIA = {
    "el:ALJq": ("p59/4248f56c4e3c4b981c947802f99a519952dda9ff1146064cb3790cd00e50f3a8.wav",
                "p59/3d5bae1a1384386c5854e09ecba0517c410ea9d1e617d95dacae242445e653b8.wav",
                "p59/091d92439bbb87ee4ff36b757387e4f40f169bb4a473c532b1b6e32b0333e277.wav",
                "p60/609a2fdf6c244cafab5c1d0ba28f4b3a69b2990168f21f150da74e6eab58f55d.wav",
                "p60/cf410874c66cb66ddb993d49b56a348de7c720c3a26f339ce798fe3c9b8aa425.wav"),
    "el:IKne": ("p61/8b1216e9153c2db41303e846b1d88d4a11312c07cf44a8c256b6fc149a47f114.wav",
                "p61/9344ed79abe6204e65a9adbd6ef60fc2084bf0e013091b42c37d29e2ba4787b8.wav",
                "p62/e2e4e9d27d6181d1792c9cf52abc0adde59c4cc5389aadbb1ebda09d45edd9f1.wav",
                "p62/fb15bdc84784ca0be6f8d52c208ba895092fd330a84961f67665464f430b2490.wav"),
    "el:onwK": ("p61/f04c2a3ae20b88594827f239019ba2c2163357600e58e564fed4010b11909f8f.wav",
                "p61/5e98a9137d02ac91f5feafc4dd945a9be45f7c2cc1f98d0014cf5986de49ce6e.wav",
                "p62/4676863cdda2d68e242b94e37ab7ba4d810fb5a95c6b0660c1007bb142a5bb46.wav",
                "p62/3d23d3cb8311e2ffe4148ba25bb010f01371e57da8a6ba934420fa50335f1c5e.wav"),
    "el:mCQM": ("p63/98b17c925559deb9d6fd6a4c1dea2d126c5f63f277d0e1f019069e45e202cec3.wav",
                "p63/d841bf967ad7ef49b024bb6f316a76890ad65d6419dfc122aa5d5f406d832d8e.wav",
                "p63/bd5ad249916676d9aec94a1b20ee29161e930804a6a25f6675359fa9fcd39316.wav"),
}
# Spans of longer files: (speaker, file, start, end).
SPANS = (
    ("rec:deewar", "user-local/610df99d33c121ba26918e51aeff8db3ae10ce284b237eece69b29524e733b16.wav", 0.0, 5.0),
    ("rec:deewar", "user-local/610df99d33c121ba26918e51aeff8db3ae10ce284b237eece69b29524e733b16.wav", 5.0, 10.0),
    ("rec:deewar", "user-local/610df99d33c121ba26918e51aeff8db3ae10ce284b237eece69b29524e733b16.wav", 10.0, 15.3),
    ("human:p60", "p60/aa0e7a1666b5df80dc41b6f10609c5f757af07c7eea15191b01d92c9dd6ed8a3.mp4", 0.0, 4.0),
    ("human:p60", "p60/aa0e7a1666b5df80dc41b6f10609c5f757af07c7eea15191b01d92c9dd6ed8a3.mp4", 4.0, 8.0),
)
PHONE = ("highpass=f=300,lowpass=f=3400,volume=0.7")


@dataclass
class Clip:
    clip_id: str
    speaker: str
    origin: str          # say | phone | media | public
    role: str            # consent | source | take
    detail: str          # the voice and text, or the file and span
    seconds: float = 0.0


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, capture_output=True)


def _wav(src: Path, dest: Path, start: float | None = None, end: float | None = None, af: str | None = None) -> None:
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    if start is not None:
        cmd += ["-ss", f"{start}", "-to", f"{end}"]
    cmd += ["-i", str(src), "-ac", "1", "-ar", "16000"]
    if af:
        cmd += ["-af", af]
    _run(cmd + [str(dest)])


def _phone(src: Path, dest: Path) -> None:
    """Band-pass, a little noise, and a 16 kbit/s Opus round trip."""
    mid = dest.with_suffix(".ogg")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.01:r=16000",
          "-filter_complex", f"[0:a]{PHONE}[v];[v][1:a]amix=inputs=2:duration=first:normalize=0", "-ac", "1", "-ar", "16000",
          "-c:a", "libopus", "-b:a", "16k", str(mid)])
    _wav(mid, dest)
    mid.unlink()


def build(out: Path, media: Path | None, public: Path | None) -> list[Clip]:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(20261024)
    clips: list[Clip] = []
    for voice in SAY_VOICES:
        slug = voice.split(" ")[0].lower() + ("-us" if "(US)" in voice else "-uk" if "(UK)" in voice else "")
        texts = [("source", SOURCE_TEXT)] + [("consent", consent.phrase(rng)) for _ in range(2)]
        for n, (role, text) in enumerate(texts):
            aiff = out / f"say-{slug}-{n}.aiff"
            _run(["say", "-v", voice, "-o", str(aiff), text])
            clip = Clip(f"say-{slug}-{n}", f"say:{slug}", "say", role, f"{voice}: {text}")
            _wav(aiff, out / f"{clip.clip_id}.wav")
            aiff.unlink()
            clips.append(clip)
            if role == "consent":
                phone = Clip(f"say-{slug}-{n}-phone", clip.speaker, "phone", "consent", f"{clip.clip_id} through the phone channel")
                _phone(out / f"{clip.clip_id}.wav", out / f"{phone.clip_id}.wav")
                clips.append(phone)
    if media is not None:
        for speaker, files in MEDIA.items():
            for f in files:
                if (media / f).exists():
                    clip = Clip(f"media-{f.split('/')[1][:10]}", speaker, "media", "take", f)
                    _wav(media / f, out / f"{clip.clip_id}.wav")
                    clips.append(clip)
        for speaker, f, start, end in SPANS:
            if (media / f).exists():
                clip = Clip(f"media-{f.split('/')[1][:10]}-{int(start)}", speaker, "media",
                            "source" if speaker.startswith("rec:") and start == 0.0 else "consent", f"{f} {start}-{end} s")
                _wav(media / f, out / f"{clip.clip_id}.wav", start, end)
                clips.append(clip)
    if public is not None and (public / "sample-ad.mp4").exists():
        clip = Clip("public-sample-ad", "public:sample-ad", "public", "source", "frontend/public/sample-ad.mp4")
        _wav(public / "sample-ad.mp4", out / f"{clip.clip_id}.wav")
        clips.append(clip)
    for clip in clips:
        clip.seconds = round(len(signals.load(out / f"{clip.clip_id}.wav")) / signals.RATE, 2)
    return clips


def score(out: Path, clips: list[Clip]) -> list[dict]:
    embed = similarity._load_embedder()
    if embed is None:
        raise SystemExit("the speaker model is not available (install the measure extra, or go online once)")
    vectors = {c.clip_id: np.asarray(embed(similarity._samples(out / f"{c.clip_id}.wav")), dtype=np.float64) for c in clips}
    pairs = []
    for a, b in itertools.combinations(clips, 2):
        if a.clip_id in b.clip_id or b.clip_id in a.clip_id:
            continue                     # a clip and its own phone copy: the same recording, not a pair
        if {a.speaker, b.speaker} & {"public:sample-ad"} and (a.speaker + b.speaker).count("say:"):
            continue                     # the sample was made with `say`'s default voice: which one is not known
        u, v = vectors[a.clip_id], vectors[b.clip_id]
        sim = max(0.0, min(1.0, float(u @ v) / float(np.linalg.norm(u) * np.linalg.norm(v))))
        pairs.append({"a": a.clip_id, "b": b.clip_id, "same": a.speaker == b.speaker,
                      "kind": _kind(a, b), "sim": round(sim, 4)})
    return pairs


def _kind(a: Clip, b: Clip) -> str:
    if a.speaker != b.speaker:
        return "different"
    if "phone" in (a.origin, b.origin):
        return "same, phone vs clean"
    if a.speaker.startswith(("el:", "rec:")):
        return "same, voice vendor or recorded sample"
    return "same, clean"


def _bands(x: np.ndarray) -> dict:
    """How many of these scores would pass, go to review, or not pass."""
    return {"n": int(x.size), "pass": int((x >= consent.PASS_AT).sum()),
            "review": int(((x >= consent.REVIEW_FROM) & (x < consent.PASS_AT)).sum()),
            "fail": int((x < consent.REVIEW_FROM).sum())}


def summary(pairs: list[dict], thresholds: list[float]) -> dict:
    same = np.array([p["sim"] for p in pairs if p["same"]])
    diff = np.array([p["sim"] for p in pairs if not p["same"]])
    like = np.array([p["sim"] for p in pairs if p["kind"] in ("same, clean", "same, phone vs clean")])

    def dist(x: np.ndarray) -> dict:
        return {"n": int(x.size), "min": round(float(x.min()), 4), "p05": round(float(np.percentile(x, 5)), 4),
                "median": round(float(np.median(x)), 4), "p95": round(float(np.percentile(x, 95)), 4),
                "max": round(float(x.max()), 4)}

    kinds = sorted({p["kind"] for p in pairs})
    return {
        "same": dist(same), "different": dist(diff),
        "by_kind": {k: dist(np.array([p["sim"] for p in pairs if p["kind"] == k])) for k in kinds},
        "at": [{"threshold": t, "false_accept": round(float((diff >= t).mean()), 4),
                "false_reject": round(float((same < t).mean()), 4),
                "false_reject_consent_like": round(float((like < t).mean()), 4)} for t in thresholds],
        "bands": {"pass_at": consent.PASS_AT, "review_from": consent.REVIEW_FROM,
                  **{name: _bands(np.array([p["sim"] for p in pairs if pick(p)])) for name, pick in (
                      ("same, consent-like (clean, phone vs clean)", lambda p: p["kind"] in ("same, clean", "same, phone vs clean")),
                      ("same, voice vendor or recorded sample", lambda p: p["kind"] == "same, voice vendor or recorded sample"),
                      ("different", lambda p: not p["same"]))}},
        "hardest_different": sorted((p for p in pairs if not p["same"]), key=lambda p: -p["sim"])[:10],
        "hardest_same": sorted((p for p in pairs if p["same"]), key=lambda p: p["sim"])[:10],
    }


def by_speakers(clips: list[Clip], pairs: list[dict]) -> list[dict]:
    """Each pair of speakers (or a speaker with itself): how many pairs, the median and the highest score."""
    who = {c.clip_id: c.speaker for c in clips}
    groups: dict[tuple[str, str], list[float]] = {}
    for p in pairs:
        groups.setdefault(tuple(sorted((who[p["a"]], who[p["b"]]))), []).append(p["sim"])
    rows = [{"a": a, "b": b, "same": a == b, "n": len(v), "median": round(float(np.median(v)), 4), "max": round(max(v), 4)}
            for (a, b), v in groups.items()]
    return sorted(rows, key=lambda r: -r["median"])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, required=True, help="where the clips are written (a scratch dir)")
    ap.add_argument("--media", type=Path, help="the dev database copy's artifacts dir (read only)")
    ap.add_argument("--public", type=Path, help="frontend/public")
    ap.add_argument("--manifest", type=Path, help="write the test set and its scores here")
    args = ap.parse_args(argv)
    clips = build(args.out, args.media, args.public)
    pairs = score(args.out, clips)
    result = summary(pairs, [round(t, 2) for t in np.arange(0.60, 0.97, 0.02)])
    result["model"] = similarity.SPEAKER_MODEL
    print(json.dumps({k: result[k] for k in ("same", "different", "by_kind", "at", "bands")}, indent=1))
    if args.manifest:
        args.manifest.write_text(json.dumps({"model": similarity.SPEAKER_MODEL, "clips": [asdict(c) for c in clips],
                                             "summary": result, "by_speakers": by_speakers(clips, pairs)},
                                            indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
