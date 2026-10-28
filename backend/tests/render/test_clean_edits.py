"""Run 5 addendum 3, item 1: clean edits. The joins (zero crossings, 10 to 30 ms
crossfades, room tone under gaps, the bed kept), and the check after every
render (overlap, clipped words, loudness jumps, clicks, new silence, the words
heard), each on synthetic audio."""
import numpy as np
import pytest

from app.domain.models import ApprovedEdit, EditPlan, MediaArtifact, Selection
from app.media import ffmpeg
from app.render import check, clean, compose
from app.render.renderer import render
from tests.factories import make_source

RATE = compose.OUT_RATE
rng = np.random.default_rng(7)


def noise(seconds, db):
    return (rng.standard_normal(int(seconds * RATE)) * 10 ** (db / 20)).astype(np.float32)


def tone(seconds, hz, amp=0.3, phase=0.0):
    t = np.arange(int(seconds * RATE)) / RATE
    return (amp * np.sin(2 * np.pi * hz * t + phase)).astype(np.float32)


def stereo(x):
    return np.stack([x, x], axis=1)


def speechy(seconds, spans, room_db=-55.0):
    """A room at `room_db` with "words" (bursts of a warbling tone) over `spans`."""
    x = noise(seconds, room_db)
    for a, b in spans:
        i0, i1 = int(a * RATE), int(b * RATE)
        t = np.arange(i1 - i0) / RATE
        x[i0:i1] += (0.2 * np.sin(2 * np.pi * (180 + 40 * np.sin(2 * np.pi * 3 * t)) * t)).astype(np.float32)
    return x


# ── the joins ─────────────────────────────────────────────────────────────────

def test_a_join_moves_inward_to_a_shared_zero_crossing_and_never_outside_its_span():
    old = tone(0.05, 440)
    new = tone(0.05, 300, phase=1.0)
    at = clean.snap(old, new, 0, +1, int(clean.SNAP * RATE))
    assert 0 <= at <= int(clean.SNAP * RATE)
    assert abs(old[at]) + abs(new[at]) <= abs(old[0]) + abs(new[0]) + 1e-6
    end = clean.snap(old, new, len(old) - 1, -1, int(clean.SNAP * RATE))
    assert len(old) - 1 - int(clean.SNAP * RATE) <= end <= len(old) - 1


def test_crossfades_are_10_to_30_ms():
    quiet, loud = noise(0.03, -70), tone(0.03, 300)
    assert clean.fade_length(quiet, quiet, RATE) == int(0.010 * RATE)
    assert clean.fade_length(quiet, loud, RATE) == int(0.030 * RATE)
    assert clean.fade_length(loud, tone(0.03, 200), RATE) == int(0.020 * RATE)
    env = compose._join_envelope(tone(1.0, 440), tone(1.0, 300))
    ramp_in = np.flatnonzero((env > 0) & (env < 1))
    first = ramp_in[ramp_in < RATE // 2]
    assert int(0.010 * RATE) - 2 <= len(first) <= int(0.030 * RATE) + 1


def test_room_tone_plays_under_a_gap_in_the_take():
    """A take shorter than its span is centred in digital silence; the room's own tone fills it."""
    base = stereo(noise(4.0, -45))
    take = np.concatenate([tone(0.4, 300), np.zeros(int(0.6 * RATE), dtype=np.float32), tone(0.4, 300)])
    room_level = np.sqrt(np.mean(base[:, 0] ** 2))
    out = _splice_one(base, take, 1.0, 2.4)
    gap = out[int(1.5 * RATE):int(1.9 * RATE), 0]
    level = np.sqrt(np.mean(gap ** 2))
    assert level == pytest.approx(room_level, rel=0.5)          # the room, not a hole
    assert np.array_equal(out[: RATE], base[: RATE])             # outside the span: untouched


def test_the_music_under_a_replaced_line_stays_continuous(tmp_path):
    """With stems the bed plays straight through the span: no dip or jump at either join."""
    bed = noise(6.0, -30)
    voice = speechy(6.0, [(0.5, 1.8), (2.0, 4.0), (4.3, 5.5)], room_db=-90)
    base = stereo(bed + voice)
    room = compose.Room(stereo(bed), None, voice)
    take = speechy(2.0, [(0.0, 2.0)], room_db=-90)     # a new line as loud as the old one
    out = _splice_one(base, take, 2.0, 4.0, room=room)
    placed = [check.Placed("e1", "replace", "a new line", 2.0, 4.0, take)]
    report = check.run(out, base, placed)
    assert not [f for f in report.findings if f.rule in ("jump", "click")], report.findings
    # Under the new line's pauses it is the bed itself, at its own level, that plays.
    hushed = _splice_one(base, np.zeros(2 * RATE, dtype=np.float32), 2.0, 4.0, room=room)
    bed_level = check.window_lufs(stereo(bed), 2.2, 3.8)
    assert check.window_lufs(hushed, 2.2, 3.8) == pytest.approx(bed_level, abs=0.5)


def _splice_one(base, take, start, end, room=None, tmp=None):
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "t.wav"
        compose._write(path, stereo(take))
        art = MediaArtifact("audio", "t" * 64, str(path), len(take) / RATE, "wav")
        edit = ApprovedEdit("e1", "c1", EditPlan(Selection(start, end), "x", "v"), art,
                            MediaArtifact("video", "f" * 64, "/x", 1.0, "mp4"))
        source = make_source(duration=len(base) / RATE)
        return compose.splice(base, render(source, [edit]).segments, room)


# ── the check ─────────────────────────────────────────────────────────────────

def test_overlap_an_added_voice_over_a_line_still_heard_is_two_voices_at_once():
    original = stereo(speechy(5.0, [(0.5, 1.5), (2.0, 3.0)]))
    take = tone(1.0, 300)
    over = check.Placed("e1", "layer", "over the words", 1.2, 2.2, take)
    in_pause = check.Placed("e2", "layer", "in the pause", 3.2, 4.2, take)
    words = [("hello", 0.5, 1.5), ("there", 2.0, 3.0)]
    found = check.run(original, original, [over], words).findings
    assert [f.rule for f in found] == ["overlap"] and "Two voices at once" in found[0].reason
    assert not check.run(original, original, [in_pause], words).findings
    # A bed under the words is the point of a bed: never an overlap.
    bed = check.Placed("e3", "layer", "[music]", 1.2, 2.2, take, voice=False)
    assert not check.run(original, original, [bed], words).findings


def test_clipped_a_take_cut_short_by_its_span_and_a_join_through_a_word(tmp_path):
    # A 1.5 s take in a 1.0 s span: half a second of it never plays.
    take = tone(1.5, 300)
    path = tmp_path / "t.wav"
    compose._write(path, stereo(take))
    art = MediaArtifact("audio", "t" * 64, str(path), 1.5, "wav")
    edit = ApprovedEdit("e1", "c1", EditPlan(Selection(1.0, 2.0), "x", "v"), art, MediaArtifact("video", "f" * 64, "/x", 1.0, "mp4"))
    segs = render(make_source(duration=4.0), [edit]).segments
    [p] = compose.placed_edits(segs, (), None, lambda e: compose.decode(e.audio.path, channels=2))
    assert p.lost_tail == pytest.approx(0.5, abs=0.03)
    original = stereo(speechy(4.0, [(0.2, 0.9), (1.0, 2.0)]))
    found = check.run(original, original, [p]).findings
    assert any(f.rule == "clipped" and "end of the new line is cut off" in f.reason for f in found)
    # A replaced span that ends in the middle of "today" cuts it in two.
    cut = check.Placed("e2", "replace", "x", 1.0, 1.55, tone(0.55, 300))
    found = check.run(original, original, [cut], [("today", 1.3, 1.8)]).findings
    assert any(f.rule == "clipped" and "“today”" in f.reason for f in found)


def test_jump_the_sound_dipping_under_a_replaced_line_is_caught():
    original = stereo(noise(8.0, -25))
    dipped = original.copy()
    dipped[int(3.0 * RATE):int(5.0 * RATE)] *= 0.5           # 6 dB down inside the span
    placed = [check.Placed("e1", "replace", "x", 3.0, 5.0, None)]
    found = check.run(dipped, original, placed).findings
    assert any(f.rule == "jump" and f.value > check.JUMP_LU for f in found)
    slight = original.copy()
    slight[int(3.0 * RATE):int(5.0 * RATE)] *= 10 ** (-1.0 / 20)   # 1 dB: under the bar
    assert not [f for f in check.run(slight, original, placed).findings if f.rule == "jump"]


def test_click_a_hard_cut_at_a_join_is_caught_and_a_crossfaded_one_is_not():
    original = stereo(tone(3.0, 220))
    hard = original.copy()
    hard[int(1.0 * RATE):int(2.0 * RATE)] = stereo(tone(1.0, 300, phase=np.pi / 2))
    placed = [check.Placed("e1", "replace", "x", 1.0, 2.0, tone(1.0, 300))]
    assert any(f.rule == "click" for f in check.run(hard, original, placed).findings)
    smooth = _splice_one(original, tone(1.0, 300, phase=np.pi / 2), 1.0, 2.0)
    assert not [f for f in check.run(smooth, original, placed).findings if f.rule == "click"]


def test_silence_a_new_pause_over_400_ms_is_caught():
    original = stereo(speechy(5.0, [(0.5, 4.5)]))
    holed = original.copy()
    holed[int(2.0 * RATE):int(2.6 * RATE)] *= 0.001           # 0.6 s of nothing inside the line
    placed = [check.Placed("e1", "replace", "x", 1.5, 3.0, None)]
    found = check.run(holed, original, placed).findings
    assert any(f.rule == "silence" and f.value == pytest.approx(0.6, abs=0.05) for f in found)
    short = original.copy()
    short[int(2.0 * RATE):int(2.25 * RATE)] *= 0.001
    assert not [f for f in check.run(short, original, placed).findings if f.rule == "silence"]


def test_words_whisper_must_hear_the_new_line_first_and_last_word_included():
    original = stereo(speechy(4.0, [(1.0, 2.5)]))
    placed = [check.Placed("e1", "replace", "Get 30% off today", 1.0, 2.5, tone(1.5, 300))]
    sent = []

    def hears(words):
        def hear(mono, rate, edit_id):
            sent.append(len(mono) / rate)
            return words
        return hear

    clipped = check.run(original, original, placed, hear=hears(["Get", "30%", "off"])).findings
    assert [f.rule for f in clipped] == ["words"] and "“today”" in clipped[0].reason
    assert sent[-1] == pytest.approx(1.5 + 2 * check.HEAR_MARGIN, abs=0.01)
    assert not check.run(original, original, placed, hear=hears(["Get", "30", "percent", "off", "today."])).findings
    wrong = check.run(original, original, placed, hear=hears(["Get", "something", "else", "entirely", "today"])).findings
    assert any("Heard" in f.reason for f in wrong)
    # Whisper's inventions are screened out; not heard at all (the flag off, a failed call) judges nothing.
    assert not check.run(original, original, placed, hear=hears(["Thanks", "for", "watching!"])).findings
    assert not check.run(original, original, placed, hear=hears(None)).findings


def test_a_clean_splice_passes_every_rule(tmp_path):
    """The whole path: a take spliced by compose, checked, nothing found."""
    base = stereo(speechy(6.0, [(0.5, 1.8), (2.0, 4.0), (4.3, 5.5)]))
    take = speechy(2.0, [(0.05, 1.95)], room_db=-90)
    out = _splice_one(base, take, 2.0, 4.0)
    placed = [check.Placed("e1", "replace", "new words", 2.0, 4.0, take)]
    words = [("one", 0.5, 1.8), ("two", 2.0, 4.0), ("three", 4.3, 5.5)]
    report = check.run(out, base, placed, words, hear=lambda m, r, e: ["new", "words"])
    assert report.findings == [] and report.needs_fix() == {}


def test_needs_fix_keeps_the_reasons_plain_and_short():
    r = check.Report([check.Finding("e1", "click", "There is a click where the new line starts."),
                      check.Finding("e1", "silence", "There is a 0.6 s silence that was not there before."),
                      check.Finding("e1", "jump", "The sound jumps 2.0 LU where the new line ends.")])
    assert r.needs_fix() == {"e1": "There is a click where the new line starts. There is a 0.6 s silence that was not there before."}
    assert chr(0x2014) not in r.needs_fix()["e1"]


pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


def test_a_line_the_check_failed_is_never_in_your_video():
    from app.domain.line_state import IN_YOUR_VIDEO, NEEDS_FIX, RENDERING, ADDED, kept_line_state
    video = {"edit_ids": ["e1", "e2"], "candidate_ids": ["c1", "c2"], "item_ids": [],
             "needs_fix": {"e2": "There is a click where the new line starts."}}
    assert kept_line_state(["e1", "c1"], video) == (IN_YOUR_VIDEO, None)
    assert kept_line_state(["e2", "c2"], video) == (NEEDS_FIX, "There is a click where the new line starts.")
    assert kept_line_state(["e3"], video, {"edit_ids": ["e3"]}) == (RENDERING, None)
    assert kept_line_state(["e4"], video) == (ADDED, None)
