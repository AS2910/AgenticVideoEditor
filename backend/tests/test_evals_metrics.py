"""The cost evals' own scoring (backend/evals): WER, plan quality, the compare flag."""
import json

from evals import compare, metrics


def test_wer_normalises_case_punctuation_and_percent():
    assert metrics.wer("Get 30% off today only", "get 30 percent off, today only.") == 0.0
    assert metrics.wer("Get thirty percent off", "Get 30% off") == 0.0
    assert metrics.wer("a b c d", "a x c") == 0.5
    assert metrics.wer("आज ही लो।", "आज ही लो") == 0.0


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
    assert runs["w"]["cost"]["warm_usd"] == 0.05
    assert runs["c"]["cost"]["warm_usd"] == round(0.12 - 10000 * 5e-6 * 1.15, 5)
