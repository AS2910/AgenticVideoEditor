"""Run 4 item 2: consent-verified cloning (replaces the stand-in liveness check
for an owner with `voices.cloning_verified` on).

The speaker reads a random phrase of 8 to 12 plain words shown on screen. The
phrase is made on the server, belongs to one attempt, and is used once. The
recording passes only when all three hold:

    length      at least MIN_SECONDS of audio
    words       Whisper's transcript matches the phrase: word error rate under
                MAX_WER, after normalising case, punctuation and spacing
    voice       speaker similarity (SIM-o, WavLM, app.continuity.similarity)
                between the recording and the clone's source audio is at or
                above PASS_AT

A similarity in [REVIEW_FROM, PASS_AT), or one that could not be measured
(no model, too little source speech) or words that could not be heard (no
real transcriber), goes to the admin review queue instead of passing or
failing. The bands come from the study in docs/cloning-consent.md.

    phrase(rng=None) -> str
    normalise(text) -> [words]
    wer(expected, heard) -> float
    decide(phrase, seconds=, heard=, similarity=) -> Check       the rules, pure
    ConsentVerifier(...).verify(recording, phrase, reference, video_id) -> Check
"""
from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

MIN_SECONDS = 4.0
MAX_WER = 0.20
# SIM-o bands (docs/cloning-consent.md): at or above PASS_AT passes, from
# REVIEW_FROM up to PASS_AT a person listens, below REVIEW_FROM does not pass.
PASS_AT = 0.92
REVIEW_FROM = 0.84
PHRASE_WORDS = (8, 12)
ATTEMPT_MINUTES = 10      # a phrase not read within this is spent (no replay of an old one)

# Plain, common words that sound like nothing else in the list and have no
# common homophone (no "two", "right", "sea", "blue", "one"), so a careful
# reading is heard as written. No numbers and no names.
WORDS = (
    "apple", "basket", "bottle", "bridge", "button", "camera", "candle", "carpet", "castle", "chair",
    "cherry", "circle", "clock", "cloud", "coffee", "corner", "cotton", "dinner", "doctor", "dragon",
    "drawer", "engine", "factory", "farmer", "feather", "finger", "forest", "garden", "glass", "guitar",
    "hammer", "garlic", "helmet", "honey", "island", "jacket", "kettle", "kitchen", "ladder", "lemon",
    "letter", "library", "lizard", "market", "meadow", "mirror", "monkey", "morning", "mountain", "needle",
    "orange", "packet", "paper", "parrot", "pencil", "pepper", "picture", "pillow", "planet", "pocket",
    "potato", "puzzle", "rabbit", "river", "rocket", "saddle", "salad", "school", "silver", "spider",
    "spoon", "station", "summer", "table", "teacher", "ticket", "tiger", "tomato", "towel", "tractor",
    "travel", "turtle", "umbrella", "valley", "village", "wagon", "window", "winter", "yellow", "zebra",
    "bright", "gentle", "quiet", "happy", "simple", "early", "little", "purple", "golden", "frozen",
    "sleepy", "busy", "empty", "heavy", "lucky", "narrow", "noisy", "rapid", "smooth", "sunny",
    "careful", "friendly", "hungry", "modern", "ordinary", "pretty", "silent", "tidy", "warm", "wild",
    "carry", "climb", "dance", "follow", "gather", "listen", "open", "paint", "remember", "pumpkin",
    "whistle", "wonder", "borrow", "collect", "measure", "promise", "settle", "shiver", "stumble", "visit",
)


@dataclass(frozen=True)
class Check:
    status: str                       # passed | review | failed
    reason: str                       # one plain sentence for the person
    tip: str = ""                     # what to try next, when it did not pass
    seconds: float | None = None
    heard: str | None = None
    wer: float | None = None
    similarity: float | None = None
    rule: str = ""                    # which rule decided: length | words | voice | unmeasured

    @property
    def passed(self) -> bool:
        return self.status == "passed"


def phrase(rng: random.Random | None = None) -> str:
    """A fresh phrase: 8 to 12 different words from WORDS, as a sentence."""
    rng = rng or random.SystemRandom()
    words = rng.sample(WORDS, rng.randint(*PHRASE_WORDS))
    return " ".join(words).capitalize() + "."


_PUNCT = re.compile(r"[^\w\s']|_", re.UNICODE)


def normalise(text: str) -> list[str]:
    """Lower case, NFKC, punctuation and hyphens to spaces, apostrophes dropped, spaces collapsed."""
    text = unicodedata.normalize("NFKC", text or "").lower().replace("’", "'")
    text = _PUNCT.sub(" ", text).replace("'", "")
    return text.split()


def wer(expected: str, heard: str) -> float:
    """Word error rate of `heard` against `expected`: (substitutions + deletions + insertions) / len(expected)."""
    ref, hyp = normalise(expected), normalise(heard)
    if not ref:
        return 0.0 if not hyp else 1.0
    prev = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        cur = [i] + [0] * len(hyp)
        for j, h in enumerate(hyp, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (r != h))
        prev = cur
    return prev[-1] / len(ref)


TIP_LENGTH = "Read the whole phrase at an easy pace. It takes about five seconds."
TIP_WORDS = "Read every word on screen, in order, in a quiet room, close to the microphone."
TIP_VOICE = "The person whose voice is in the video reads the phrase themselves. Try a quiet room, with no music or other voices."


def decide(text: str, *, seconds: float | None, heard: str | None, similarity: float | None,
           pass_at: float = PASS_AT, review_from: float = REVIEW_FROM) -> Check:
    """The gate's rules in order: length, words, voice. Pure, so each rule is tested on its own."""
    if seconds is None:
        return Check("failed", "That recording could not be read.", "Record the phrase again, or upload another file.", rule="length")
    if seconds < MIN_SECONDS:
        return Check("failed", f"That recording is {seconds:.1f} s; it needs at least {MIN_SECONDS:.0f} s.", TIP_LENGTH,
                     seconds=seconds, rule="length")
    score = wer(text, heard) if heard is not None else None
    if score is not None and score >= MAX_WER:
        return Check("failed", "The words heard did not match the phrase.", TIP_WORDS,
                     seconds=seconds, heard=heard, wer=score, similarity=similarity, rule="words")
    if score is None or similarity is None:
        what = "the words" if score is None else "the voice"
        return Check("review", f"We could not check {what} automatically, so a person will listen to the recording.",
                     seconds=seconds, heard=heard, wer=score, similarity=similarity, rule="unmeasured")
    if similarity >= pass_at:
        return Check("passed", "The words and the voice match the speaker in the video.",
                     seconds=seconds, heard=heard, wer=score, similarity=similarity, rule="voice")
    if similarity >= review_from:
        return Check("review", "The voice is close but not a clear match, so a person will listen to the recording.",
                     seconds=seconds, heard=heard, wer=score, similarity=similarity, rule="voice")
    return Check("failed", "The voice in the recording does not match the speaker in the video.", TIP_VOICE,
                 seconds=seconds, heard=heard, wer=score, similarity=similarity, rule="voice")


@dataclass
class ConsentVerifier:
    """The real gate. Every part is injected: `transcribe(path, video_id) -> text | None`
    (None: no real transcriber here), `similarity(reference, recording) -> float | None`,
    `seconds_of(path) -> float`. Model names are stored with each attempt."""

    transcribe: Callable[[Path, str], str | None]
    similarity: Callable[[Path, Path], float | None]
    seconds_of: Callable[[Path], float]
    asr_model: str = ""
    speaker_model: str = ""
    pass_at: float = PASS_AT
    review_from: float = REVIEW_FROM
    name: str = field(default="verified")
    test_mode: bool = False

    def verify(self, recording: Path, text: str, reference: Path | None, video_id: str = "") -> Check:
        try:
            seconds = float(self.seconds_of(recording))
        except Exception:  # noqa: BLE001 - a file we cannot read is a failed attempt, said plainly
            seconds = None
        if seconds is None or seconds < MIN_SECONDS:
            return decide(text, seconds=seconds, heard=None, similarity=None)
        heard = self.transcribe(recording, video_id)
        sim = self.similarity(reference, recording) if reference is not None else None
        return decide(text, seconds=seconds, heard=heard, similarity=sim,
                      pass_at=self.pass_at, review_from=self.review_from)
