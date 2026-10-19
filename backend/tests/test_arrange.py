"""The arrangement as a pure function, against the cases the front end's port runs too."""
import json
from pathlib import Path

import pytest

from app import arrange
from app.domain.models import Statement

CASES = json.loads((Path(__file__).parent / "fixtures" / "arrange-cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_place_matches_the_shared_cases(case):
    sts = [Statement(f"line {i}", a, b) for i, (a, b) in enumerate(case["statements"])]
    lines = arrange.specs(sts, case["lengths"])
    placed = arrange.place(lines, arrange.Arrangement.from_dict(case["arrangement"]))
    assert [{"key": p.key, "start": p.start, "end": p.end, "pinned": p.pinned, "pushed_after": p.pushed_after,
             "moved": p.moved} for p in placed] == case["placed"]
    assert arrange.overrun(placed, case["duration"]) == case["overrun"]


def test_nothing_changed_is_the_original_timing():
    sts = [Statement("a", 0.4, 2.0), Statement("b", 2.5, 4.0)]
    lines = arrange.specs(sts)
    assert arrange.Arrangement().is_default([ln.key for ln in lines])
    assert [(p.start, p.end, p.moved) for p in arrange.place(lines, arrange.Arrangement())] == [(0.4, 2.0, False), (2.5, 4.0, False)]


def test_two_pins_that_would_play_at_once_are_named():
    lines = arrange.specs([Statement("a", 0.0, 1.0), Statement("b", 2.0, 3.0)])
    assert arrange.pin_conflict(lines, {"L0": 0.0, "L1": 0.5}).startswith("Those two pinned lines would play at once")
    assert arrange.pin_conflict(lines, {"L0": 0.0, "L1": 1.0}) is None
