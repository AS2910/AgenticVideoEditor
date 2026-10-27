"""Run 5 item 7: delivery measured, the neighbours' range, distance and steering."""
import numpy as np
import pytest

from app.continuity import prosody as P
from app.continuity import signals
from app.continuity.measured import loop_room
from app.domain.models import Selection, Transcript, Word

RATE = signals.RATE


def speech(seconds=2.0, f0=(180.0, 180.0), syllables=4.0, level=0.2):
    """A voiced 'line': harmonics on a pitch glide from f0[0] to f0[1],
    pulsed into `syllables` a second."""
    t = np.arange(int(RATE * seconds)) / RATE
    hz = np.linspace(f0[0], f0[1], t.size)
    phase = 2 * np.pi * np.cumsum(hz) / RATE
    x = sum(np.sin(k * phase) / k for k in range(1, 6))
    pulse = np.sin(np.pi * syllables * t) ** 2
    return (level * x * pulse / np.max(np.abs(x))).astype(np.float32)


def test_register_span_and_rate_are_read_from_the_audio():
    flat = P.measure(speech(f0=(200, 200), syllables=4))
    assert flat.register == pytest.approx(12 * np.log2(2.0), abs=0.3)   # 200 Hz is 12 st above 100
    assert flat.span < 1.0
    assert flat.rate == pytest.approx(4.0 / 0.75, rel=0.35)              # pulses a second of speaking time
    glide = P.measure(speech(f0=(150, 300), syllables=4))
    assert glide.span > 8.0
    fast = P.measure(speech(syllables=7))
    assert fast.rate > flat.rate * 1.4


def test_silence_measures_nothing_and_blocks_nothing():
    quiet = P.measure(np.zeros(RATE, dtype=np.float32))
    assert quiet.register is None and quiet.span is None and quiet.rate is None and quiet.contour is None
    verdict = P.judge(quiet, None, [quiet, quiet])
    assert verdict.outside == () and verdict.distance is None


def test_the_same_line_is_no_distance_and_a_rising_one_is_some():
    line = P.measure(speech(f0=(220, 160)))
    assert P.distance(line, line, []) == pytest.approx(0.0, abs=1e-6)
    rising = P.measure(speech(f0=(160, 220)))
    assert P.distance(rising, line, []) > 0.5
    assert P.score(0.0) == 1.0 and P.score(1.0) == pytest.approx(0.8) and P.score(None) is None


def test_a_take_outside_the_neighbours_range_is_refused_and_says_why():
    neighbours = [P.measure(speech(f0=(150, 260), syllables=4)), P.measure(speech(f0=(160, 250), syllables=4.5))]
    inside = P.judge(P.measure(speech(f0=(155, 255), syllables=4.2)), None, neighbours)
    assert inside.outside == ()
    flat_fast = P.judge(P.measure(speech(f0=(200, 205), syllables=9)), None, neighbours)
    assert any("faster" in w for w in flat_fast.outside)
    assert any("Flatter" in w for w in flat_fast.outside)
    assert flat_fast.faster > 1 and flat_fast.flatter > 1


def test_one_neighbour_is_no_range():
    b = P.bounds([P.measure(speech())])
    assert b.rate is None and b.span is None and b.register is None


def test_steering_moves_a_retake_back_toward_the_speaker():
    fast_flat = P.Verdict(1.2, ("x",), faster=1.4, flatter=2.0)
    out = P.steer({"stability": 0.5}, fast_flat)
    assert out["speed"] == pytest.approx(0.85)          # one step at most
    assert out["stability"] == pytest.approx(0.35) and out["style"] == pytest.approx(0.1)
    sing_song = P.steer(None, P.Verdict(1.0, ("x",), flatter=0.5))
    assert sing_song == {"stability": 0.65}
    assert P.steer({"speed": 1.0}, P.Verdict(0.2, ())) is None


def test_the_first_take_follows_an_animated_or_flat_speaker_and_leaves_a_neutral_one():
    animated = P.Delivery(14.0, 11.0, 5.0, -18.0, None, 2.0)
    flat = P.Delivery(14.0, 2.5, 5.0, -18.0, None, 2.0)
    neutral = P.Delivery(14.0, 6.2, 5.0, -18.0, None, 2.0)
    assert P.reference_settings(animated, []) == {"stability": 0.35, "style": 0.2}
    assert P.reference_settings(flat, []) == {"stability": 0.7}
    assert P.reference_settings(neutral, []) is None
    # No line to read: the neighbours' median span stands in.
    assert P.reference_settings(None, [animated, animated]) == {"stability": 0.35, "style": 0.2}
    assert P.reference_settings(None, []) is None


def test_neighbours_are_the_speakers_lines_either_side_never_the_selection():
    t = Transcript(words=(
        Word("one", 0.0, 0.3, "A"), Word("two", 0.35, 0.8, "A"),          # a line, 0.0-0.8
        Word("other", 1.0, 1.8, "B"),                                      # another speaker
        Word("edit", 2.0, 2.6, "A"),                                       # the selection
        Word("three", 3.0, 3.3, "A"), Word("four", 3.35, 3.7, "A"),        # a line, 3.0-3.7
        Word("hi", 4.5, 4.6, "A"),                                         # too short
    ))
    assert P.lines_near(t, Selection(2.0, 2.6), "A") == [(0.0, 0.8), (3.0, 3.7)]


def test_same_words_means_a_new_voice_for_the_line_as_said():
    t = Transcript(words=(Word("Get", 0.0, 0.24), Word("20%", 0.24, 0.56), Word("off", 0.96, 1.2)))
    assert P.same_words(t, Selection(0.24, 1.2), "20% off.")
    assert not P.same_words(t, Selection(0.24, 1.2), "30% off")
    assert not P.same_words(None, Selection(0.24, 1.2), "20% off")


def test_room_tone_loops_without_a_click_at_the_join():
    rate = 24000
    room = (np.random.default_rng(1).standard_normal(rate // 5) * 0.01).astype(np.float32)
    room[-50:] = 0.2     # a loud tail: a hard join would jump from 0.2 to the noise
    looped = loop_room(room, rate, rate)
    assert looped.size == rate
    hard = np.resize(room, rate)
    step = room.size - int(0.03 * rate)
    # Around each join the crossfade keeps the jump far below the hard tile's.
    jump = lambda x, at: float(np.max(np.abs(np.diff(x[at - 5:at + 5]))))   # noqa: E731
    assert jump(looped, step) < jump(hard, room.size) / 2
    rms = float(np.sqrt(np.mean(looped ** 2)))
    assert 0.005 < rms < 0.1
