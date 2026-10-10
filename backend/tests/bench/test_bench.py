"""The bench (Phase 19): the corpus runs, labels hold, the gate closes on a
regression, and the ladder reads the rungs table."""
import json
from dataclasses import replace

import pytest

from app.bench import corpus, gate, rungs
from app.bench.__main__ import main
from app.bench.runner import Result, from_json, run, table, to_json
from app.continuity.seam import discontinuity, seam_jumps, worst
from app.media import ffmpeg, fit

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="needs ffmpeg")


@pytest.fixture(scope="module")
def results(tmp_path_factory):
    work = tmp_path_factory.mktemp("bench")
    return run(corpus.build(work), work)


def test_every_case_meets_its_label(results):
    unmet = [(r.name, r.label, r.rung, r.passed, r.warnings) for r in results if not r.ok]
    assert unmet == []
    labels = {r.label for r in results}
    assert labels == {"good", "bad", "ask"}


def test_a_take_that_cannot_fit_is_asked_about_not_stretched(results):
    asked = [r for r in results if r.label == "ask"]
    assert asked and all(r.rung == "ask" and r.passed is None for r in asked)


def test_long_and_short_takes_are_fitted_by_the_ladder(results):
    long = next(r for r in results if "runs 12% long" in r.name)
    short = next(r for r in results if "runs 12% short" in r.name)
    assert long.rung != "none" and long.rung != "ask" and long.ratio == pytest.approx(1.12, abs=0.03)
    assert short.rung != "none" and short.rung != "ask" and short.ratio == pytest.approx(0.88, abs=0.03)


def test_seams_are_measured_on_the_render_and_no_frame_is_frozen(results):
    fitted = [r for r in results if r.rung != "ask"]
    assert all(r.seam_level_db is not None and r.seam_colour_st is not None for r in fitted)
    inserts = [r for r in results if r.mix == "concatenate"]
    assert len(inserts) >= 2
    # Phase 16: an added line stretches the pause after it, or the tail of the line when
    # there is no pause; the export never freezes a frame on the corpus.
    assert all(r.frozen_seconds == 0.0 for r in results)


def test_long_and_short_takes_flex_the_picture_before_the_speech(results):
    long = next(r for r in results if "runs 12% long" in r.name)
    short = next(r for r in results if "runs 12% short" in r.name)
    assert "flex" in long.rung and "tempo" not in long.rung
    assert short.rung == "flex"


def test_results_round_trip_through_json_and_the_table_has_a_row_per_case(results):
    again = from_json(json.loads(json.dumps(to_json(results))))
    assert again == results
    assert table(results).count("\n") == len(results) + 1


def test_the_gate_is_open_against_itself_and_closes_on_a_regression(results):
    assert gate.check(results, results) == []
    worse = [replace(r, prosody=(r.prosody or 1.0) - 0.1) if r.label == "good" and r.prosody else r for r in results]
    failures = gate.check(worse, results)
    assert failures and all("prosody" in f for f in failures)
    frozen = [replace(r, frozen_seconds=r.frozen_seconds + 0.5) for r in results]
    assert any("frozen_seconds" in f for f in gate.check(frozen, results))
    flipped = [replace(r, passed=False, ok=False) if r.label == "good" and r.rung != "ask" else r for r in results]
    assert any("should have passed" in f for f in gate.check(flipped))


def test_the_rungs_table_scores_each_rung_per_band(results):
    t = rungs.build(results)
    assert "bands" in t
    reached = {fit.band(r.ratio) for r in results if rungs.rungs_used(r.rung)}
    assert set(t["bands"]) == reached
    for b in t["bands"].values():
        for v in b.values():
            assert v["n"] >= 1 and 0.0 <= v["score"] <= 1.0


def test_the_ladder_puts_the_better_rung_first_once_the_bench_has_enough(tmp_path):
    table = {"1.05-1.25": {"gaps": {"n": 5, "score": 0.7}, "flex": {"n": 4, "score": 0.95}, "tempo": {"n": 5, "score": 0.9}}}
    assert fit.ladder(1.1, table) == ("flex", "tempo", "gaps")
    # Every rung needs enough measurements before the order changes.
    assert fit.ladder(1.1, {"1.05-1.25": {"gaps": {"n": 1, "score": 0.1}, "flex": {"n": 5, "score": 0.9}, "tempo": {"n": 5, "score": 0.9}}}) == fit.DEFAULT_LADDER
    assert fit.ladder(1.1, {"1.05-1.25": {"gaps": {"n": 5, "score": 0.7}, "tempo": {"n": 5, "score": 0.9}}}) == fit.DEFAULT_LADDER
    assert fit.ladder(0.5, table) == fit.DEFAULT_LADDER
    assert fit.ladder(1.1, {}) == fit.DEFAULT_LADDER
    # From a file, too, and re-read when it changes.
    path = tmp_path / "rungs.json"
    path.write_text(json.dumps({"bands": table}))
    assert fit.ladder(1.1, fit.rungs_table(path)) == ("flex", "tempo", "gaps")


def test_when_tempo_leads_the_pauses_are_left_alone(tmp_path, monkeypatch):
    # A 1.5 s take with a 0.5 s pause into a 1.36 s slot: by default the pause
    # is trimmed; with tempo first in this band the speech is sped up instead.
    import numpy as np
    from app.media.fit import _write
    rate = 24000
    t = np.arange(int(0.5 * rate)) / rate
    tone = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    x = np.concatenate([tone, np.zeros(int(0.5 * rate), np.float32), tone])
    take = tmp_path / "take.wav"
    _write(take, x, rate)
    target = 1.36
    _, _, default_notes, _ = fit.fit_elastically(take, tmp_path / "a.wav", target)
    assert any(n.startswith("trimmed") for n in default_notes)
    monkeypatch.setattr(fit, "rungs_table", lambda path=None: {fit.band(1.5 / target): {
        "gaps": {"n": 9, "score": 0.5}, "flex": {"n": 9, "score": 0.6}, "tempo": {"n": 9, "score": 0.9}}})
    _, duration, notes, _ = fit.fit_elastically(take, tmp_path / "b.wav", target)
    assert not any(n.startswith("trimmed") for n in notes)
    assert any(n.startswith("speech at") for n in notes)
    assert duration == pytest.approx(target, abs=0.02)


def test_seam_jumps_read_a_level_step_and_nothing_across_a_steady_tone():
    import numpy as np
    rate = 48000
    t = np.arange(rate) / rate
    steady = np.sin(2 * np.pi * 440 * t).astype(np.float32)
    level, colour = worst(seam_jumps(steady, rate, [0.5]))
    assert level < 0.2 and colour < 0.2
    stepped = steady.copy()
    stepped[rate // 2:] *= 0.25     # −12 dB from the seam on
    level, _ = worst(seam_jumps(stepped, rate, [0.5]))
    assert level == pytest.approx(12.0, abs=0.5)
    brighter = np.concatenate([steady[: rate // 2], np.sin(2 * np.pi * 880 * t[rate // 2:]).astype(np.float32)])
    _, colour = worst(seam_jumps(brighter, rate, [0.5]))
    assert colour == pytest.approx(12.0, abs=1.0)
    assert worst([]) == (0.0, 0.0)
    # Relative to the original, a render that steps exactly as the original does adds nothing.
    assert worst(discontinuity(stepped, stepped, rate, [0.5])) == (0.0, 0.0)
    level, _ = worst(discontinuity(stepped, steady, rate, [0.5]))
    assert level == pytest.approx(12.0, abs=0.5)


def test_the_cli_runs_gates_and_accepts(tmp_path, capsys):
    out = tmp_path / "r.json"
    rungs_path = tmp_path / "rungs.json"
    assert main(["run", "--out", str(out), "--rungs", str(rungs_path), "--clips", str(tmp_path / "none")]) == 0
    assert out.exists() and rungs_path.exists()
    assert main(["gate", "--results", str(out), "--baseline", str(tmp_path / "missing.json")]) == 0
    assert "no baseline yet" in capsys.readouterr().out
    assert main(["accept", "--results", str(out), "--baseline", str(tmp_path / "base.json")]) == 0
    assert main(["gate", "--results", str(out), "--baseline", str(tmp_path / "base.json")]) == 0
    assert "The gate is open" in capsys.readouterr().out
    # A regression closes it.
    data = json.loads(out.read_text())
    for c in data["cases"]:
        if c["label"] == "good" and c["prosody"] is not None:
            c["prosody"] -= 0.2
    worse = tmp_path / "worse.json"
    worse.write_text(json.dumps(data))
    assert main(["gate", "--results", str(worse), "--baseline", str(tmp_path / "base.json")]) == 1
    assert "The gate is closed" in capsys.readouterr().out


def test_a_manifest_turns_a_real_clip_into_cases(tmp_path):
    (tmp_path / "take.wav").write_bytes(b"")
    (tmp_path / "clip.json").write_text(json.dumps({
        "clip": "clip.mp4", "words": [["hi", 0.0, 0.5, "A"]],
        "edits": [{"name": "hello", "start": 0.0, "end": 0.5, "take": "take.wav", "label": "good"}],
    }))
    cases = corpus.load_manifest(tmp_path / "clip.json")
    assert [c.name for c in cases] == ["clip · hello"]
    assert cases[0].take(tmp_path) == tmp_path / "take.wav"
    assert cases[0].transcript.words[0].speaker == "A"
