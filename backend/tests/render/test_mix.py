"""Role-based, relative mixing (2026-10-20), on synthetic sound with known loudness."""
from types import SimpleNamespace

import numpy as np
import pytest

from app.domain.models import Selection
from app.media import loudness as L
from app.render import mix

RATE = 48000
S = mix.MixSettings()


def _speech(seconds, level=0.3, seed=0):
    """Words: 400 ms bursts of a voiced tone, 200 ms gaps."""
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * RATE)) / RATE
    on = (t % 0.6) < 0.4
    x = (np.sin(2 * np.pi * 180 * t) + 0.5 * np.sin(2 * np.pi * 360 * t) + 0.05 * rng.standard_normal(len(t))) * on * level
    return np.stack([x, x], axis=1), [(k * 0.6, k * 0.6 + 0.4) for k in range(int(seconds / 0.6) + 1) if k * 0.6 < seconds]


def _noise(seconds, level=0.3, seed=1):
    x = np.random.default_rng(seed).standard_normal(int(seconds * RATE)) * level
    return np.stack([x, x], axis=1)


def _edit(eid, start, end, role, text="", offset=None):
    return SimpleNamespace(edit_id=eid, candidate_id=f"c-{eid}",
                           plan=SimpleNamespace(selection=Selection(start, end), role=role, offset_db=offset, new_text=text, mix="layer"))


def _run(base, layers, takes, words, bed=None, settings=S, lines=()):
    return mix.mix(base, layers, lambda e: takes[e.edit_id], words, settings, bed=bed, lines=lines)


def test_a_bed_under_speech_sits_15_db_lower_and_ducks_during_words():
    base, words = _speech(6.0)
    cheers = _noise(4.0, 0.5)
    out = _run(base, [_edit("e1", 1.0, 5.0, "bed", "cheers")], {"e1": cheers}, words)
    rep = out.reports[0]
    speech = L.loudness(base, mask=mix._mask(words, len(base), RATE))
    assert rep.role == "bed" and not rep.alone and rep.ducks
    assert speech - rep.level_lufs == pytest.approx(15.0, abs=1.0)
    assert rep.under_db == pytest.approx(15.0, abs=1.0)
    # During a word the bed plays a further 6 dB down; in a long pause it comes back.
    bed_alone = out.audio.astype(np.float64) - base
    in_word = slice(int(3.05 * RATE), int(3.35 * RATE))          # 3.0 to 3.4 is a word
    level_at = lambda sl: 20 * np.log10(np.sqrt((bed_alone[sl] ** 2).mean()))   # noqa: E731
    undipped = 20 * np.log10(np.sqrt((cheers[int(2.05 * RATE):int(2.35 * RATE)] ** 2).mean())) + rep.gain_db
    assert level_at(in_word) == pytest.approx(undipped - 6.0, abs=1.5)


def test_a_bed_alone_plays_nearly_full_and_says_so():
    base = np.zeros((6 * RATE, 2))
    out = _run(base, [_edit("e1", 1.0, 5.0, "bed", "rain")], {"e1": _noise(4.0, 0.05)}, [])
    rep = out.reports[0]
    assert rep.alone and not rep.ducks and rep.under_db is None
    assert rep.level_lufs == pytest.approx(S.voice_default_lufs - S.bed_alone_db, abs=0.5)


def test_a_bed_fades_in_and_out_over_300_ms():
    base = np.zeros((6 * RATE, 2))
    out = _run(base, [_edit("e1", 1.0, 5.0, "bed")], {"e1": _noise(4.0, 0.2)}, [])
    a = np.abs(out.audio[:, 0])
    first = a[RATE:RATE + int(0.02 * RATE)].max()
    settled = a[RATE + int(0.5 * RATE):RATE + int(0.6 * RATE)].max()
    assert first < settled * 0.1


def test_a_voice_and_an_effect_sit_at_the_clips_speech_level_then_the_fine_tune():
    base, words = _speech(6.0)
    speech = L.loudness(base, mask=mix._mask(words, len(base), RATE))
    takes = {"v": _speech(2.0, 0.02, seed=3)[0], "fx": _noise(1.0, 0.9)}
    out = _run(base, [_edit("v", 0.5, 2.5, "voice", offset=-3.0), _edit("fx", 3.0, 4.0, "effect")], takes, words)
    by = {r.edit_id: r for r in out.reports}
    assert by["v"].level_lufs == pytest.approx(speech - 3.0, abs=0.5)
    assert by["fx"].level_lufs == pytest.approx(speech, abs=0.5)


def test_a_clip_with_no_speech_uses_the_project_default():
    base = np.zeros((4 * RATE, 2))
    out = _run(base, [_edit("v", 0.5, 2.5, "voice")], {"v": _speech(2.0, 0.5)[0]}, [], settings=mix.MixSettings(voice_default_lufs=-20.0))
    assert out.voice_lufs == -20.0 and out.reports[0].level_lufs == pytest.approx(-20.0, abs=0.5)


@pytest.mark.parametrize("with_stems", [False, True])
def test_a_voice_over_the_originals_music_ducks_it(with_stems):
    music = _noise(6.0, 0.3)
    base = music.copy()
    voice = _speech(2.0, 0.05, seed=4)[0]
    out = _run(base, [_edit("v", 2.0, 4.0, "voice", "narration")], {"v": voice}, [], bed=music if with_stems else None)
    remaining = out.audio.astype(np.float64)
    remaining[2 * RATE:4 * RATE] -= voice * L.gain(out.reports[0].gain_db)
    before = L.loudness(remaining[int(0.5 * RATE):int(1.5 * RATE)])
    during = L.loudness(remaining[int(2.6 * RATE):int(2.9 * RATE)])
    assert before - during > 5.0
    assert before - during <= (S.stem_duck_max_db if with_stems else S.source_duck_max_db) + 0.5
    assert out.reports[0].ratio_db is not None


def test_loud_cheers_over_a_voice_are_named_on_its_row():
    base = np.zeros((6 * RATE, 2))
    takes = {"v": _speech(3.0, 0.1)[0], "c": _noise(3.0, 0.5)}
    loud = _edit("c", 1.0, 4.0, "effect", "[cheers]", offset=6.0)
    out = _run(base, [_edit("v", 1.0, 4.0, "voice", "Welcome"), loud], takes, [])
    rep = next(r for r in out.reports if r.edit_id == "v")
    assert rep.ratio_db < S.clear_db and rep.covered_by == "c"
    assert rep.flag == "“cheers” covers this line at 0:01; lower it or make it a Bed."
    # As a bed the same cheers sit under it and the line is heard.
    out = _run(base, [_edit("v", 1.0, 4.0, "voice", "Welcome"), _edit("c", 1.0, 4.0, "bed", "[cheers]")], takes, [])
    assert next(r for r in out.reports if r.edit_id == "v").flag is None


def test_a_moved_original_line_keeps_its_recorded_level():
    base = np.zeros((4 * RATE, 2))
    quiet = _speech(1.0, 0.01)[0]
    out = _run(base, [_edit("arr-L1-in", 1.0, 2.0, None)], {"arr-L1-in": quiet}, [])
    assert out.reports[0].gain_db == 0.0
