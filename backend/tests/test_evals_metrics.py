"""The cost evals' own scoring (backend/evals): WER, plan quality, the compare flag."""
import json

from evals import compare, metrics


def test_wer_normalises_case_punctuation_and_percent():
    assert metrics.wer("Get 30% off today only", "get 30 percent off, today only.") == 0.0
    assert metrics.wer("Get thirty percent off", "Get 30% off") == 0.0
    assert metrics.wer("a b c d", "a x c") == 0.5
    assert metrics.wer("आज ही लो।", "आज ही लो") == 0.0
    # A delivery tag steers the voice; nobody says it (run 5 addendum 0a).
    assert metrics.wer("[excited] And the sweets too?", "And the sweets too?") == 0.0


LINES = [{"start": 0.0, "end": 2.0, "text": "one"}, {"start": 2.5, "end": 4.0, "text": "two"}]


def _item(start, end, mix="replace", status="approved"):
    return {"selection": {"start": start, "end": end}, "mix": mix, "status": status, "kind": "planned"}


def test_plan_quality_counts_only_the_asked_lines():
    assert metrics.plan_quality([_item(0.1, 1.9)], LINES, [0], 0, False)["score"] == 1.0
    # The asked line and one it was not asked to touch.
    q = metrics.plan_quality([_item(0.1, 1.9), _item(2.5, 4.0)], LINES, [0], 0, False)
    assert q["score"] == 0.5 and q["outside"] == 1
    # An added line where none was asked for, and a dropped proposal that does not count.
    assert metrics.plan_quality([_item(4.2, 5.0, mix="layer"), _item(0, 2, status="dismissed")], LINES, [], 1, False)["score"] == 1.0
    assert metrics.plan_quality([], LINES, [0, 1], 0, False)["missed"] == 2
    assert metrics.plan_quality([], LINES, [], 0, True)["score"] == 1.0
    assert metrics.plan_quality([_item(0, 2)], LINES, [], 0, True)["score"] == 0.0


def test_compare_flags_a_score_more_than_five_percent_worse(tmp_path):
    def run(cost, utmos, wer):
        return {"runs": [{"scenario": "s", "status": "succeeded", "cost": {"turn_usd": cost}, "requests": [],
                          "scores": {"utmos": utmos, "wer": wer, "plan_quality": 1.0}}]}
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    a.write_text(json.dumps(run(0.10, 3.0, 0.10)))
    b.write_text(json.dumps(run(0.05, 2.5, 0.11)))
    text, flags = compare.table(a, b)
    assert "-50%" in text
    assert flags == ["s: utmos 3.000 -> 2.500"]


def test_the_mock_transcriber_knows_the_eval_clips():
    from pathlib import Path
    from types import SimpleNamespace

    from app.adapters.mock import MockTranscriptionAdapter
    known = json.loads((Path(__file__).resolve().parents[1] / "evals" / "clips" / "transcripts.json").read_text())
    sha = next(k for k, v in known.items() if v["clip"] == "chai.mp4")
    t = MockTranscriptionAdapter(known).transcribe(SimpleNamespace(media=SimpleNamespace(sha256=sha)))
    assert len(t.statements) == 5 and {w.speaker for w in t.words} == {"A", "B"}
    # Any other clip still gets the canned words.
    assert MockTranscriptionAdapter(known).transcribe(SimpleNamespace(media=SimpleNamespace(sha256="x"))).words[1].text == "20%"


def test_compare_counts_a_cold_shared_prefix_as_read(tmp_path):
    warm = {"scenario": "w", "status": "succeeded", "cost": {"turn_usd": 0.05}, "scores": {},
            "requests": [{"input": 4, "cache_read": 10000, "cache_write": 400, "output": 100}]}
    cold = {"scenario": "c", "status": "succeeded", "cost": {"turn_usd": 0.12}, "scores": {},
            "requests": [{"input": 4, "cache_read": 0, "cache_write": 10400, "output": 100}]}
    p = tmp_path / "r.json"
    p.write_text(json.dumps({"runs": [warm, cold]}))
    runs = compare.load(p)
    assert runs["w"][0]["cost"]["warm_usd"] == 0.05
    assert runs["c"][0]["cost"]["warm_usd"] == round(0.12 - 10000 * 5e-6 * 1.15, 5)


def _runs(*rows):
    return {"runs": [{"scenario": "s", "status": "succeeded", "cost": {"turn_usd": c}, "requests": [],
                      "scores": {"utmos": u, "wer": w, "plan_quality": 1.0}} for c, u, w in rows]}


def test_compare_uses_the_mean_and_flags_only_outside_the_spread(tmp_path):
    a, b = tmp_path / "a.json", tmp_path / "b.json"
    # Three runs each: B's UTMOS mean is 7% lower but inside A's spread, so it is noise.
    a.write_text(json.dumps(_runs((0.10, 4.4, 0.0), (0.12, 3.7, 0.0), (0.08, 4.2, 0.0))))
    b.write_text(json.dumps(_runs((0.10, 3.8, 0.0), (0.10, 3.9, 0.0), (0.10, 3.8, 0.0))))
    text, flags = compare.table(a, b)
    assert flags == [] and "| s | 3 / 3 |" in text and "4.100 (3.700-4.400)" in text
    # Past the spread as well: flagged.
    b.write_text(json.dumps(_runs((0.10, 3.5, 0.0), (0.10, 3.6, 0.0), (0.10, 3.5, 0.0))))
    assert compare.table(a, b)[1] == ["s: utmos 4.100 (3.700-4.400) -> 3.533 (3.500-3.600)"]


def test_the_runner_summarises_each_scenario_with_mean_and_spread():
    from evals import runner
    rows = _runs((0.10, 4.0, 0.0), (0.20, 3.0, 0.2))["runs"] + [{"scenario": "s", "status": "error"}]
    out = runner.summary(rows)["s"]
    assert out["n"] == 2 and out["utmos"] == {"mean": 3.5, "min": 3.0, "max": 4.0}
    assert out["turn_usd"]["mean"] == 0.15 and runner.RUNS == 3
