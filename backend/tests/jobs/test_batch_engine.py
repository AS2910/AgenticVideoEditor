"""F4's engine on its own: the gate's totals, three at a time, a child
reserving inside the parent's cap (and stopped by a ceiling with the
reason), the parent's cost as the sum of its children, cancel."""
import threading
import time

import pytest

from app.jobs.activity import ActivityJobs
from app.jobs.batch import BatchEngine, BatchError, Child, batch_seconds
from app.store.db import Database


@pytest.fixture()
def world():
    db = Database(":memory:")
    meta: dict[str, str] = {}
    activity = ActivityJobs(db)
    state = {"inside": 0, "most": 0, "ran": [], "closed": []}
    lock = threading.Lock()

    def run_child(record, child):
        with lock:
            state["inside"] += 1
            state["most"] = max(state["most"], state["inside"])
            state["ran"].append(child["video_id"])
        time.sleep(0.05)
        with lock:
            state["inside"] -= 1
        if child["video_id"] == "bad":
            activity.fail(child["job_id"], "turn_failed", "It broke.", cost_usd=0.02)
        else:
            activity.finish(child["job_id"], cost_usd=0.1, detail={"outcome": "current", "spent_usd": 0.1})

    refusals: dict[str, str] = {}
    engine = BatchEngine(activity, meta.get, meta.__setitem__, run_child,
                         lambda child, held: refusals.get(child["video_id"]), lambda video_id: None,
                         on_close=lambda record: state["closed"].append(record["phase"]))
    return engine, activity, state, refusals


def kids(*ids, cap=0.5, est=0.1, lines=2):
    return [Child(video_id=v, filename=f"{v}.mp4", goal="g", cap_usd=cap, est_usd=est, lines=lines) for v in ids]


def test_the_gate_totals_add_up_and_unknowns_stay_unknown(world):
    engine, activity, _, _ = world
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a", "b", "c"), est_s=59.2)
    assert rec["totals"] == {"videos": 3, "lines": 6, "est_usd": 0.3, "est_s": 60, "cap_usd": 1.5}
    assert activity.get(rec["batch_id"]).status == "queued"
    unknown = kids("a") + [Child(video_id="b", filename="b", goal="g", cap_usd=0.5)]
    rec = engine.open_gate("f1", "local", "ask", "g", unknown)
    assert rec["totals"]["lines"] is None and rec["totals"]["est_usd"] is None and rec["totals"]["est_s"] is None
    with pytest.raises(BatchError):
        engine.open_gate("f1", "local", "ask", "g", [])


def test_three_at_a_time_and_the_parent_costs_what_its_children_did(world):
    engine, activity, state, _ = world
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a", "b", "bad", "d", "e", "f"))
    engine.go(rec["batch_id"])
    engine.wait(rec["batch_id"], 10)
    parent = activity.get(rec["batch_id"])
    assert state["most"] == 3 and sorted(state["ran"]) == ["a", "b", "bad", "d", "e", "f"]
    assert parent.status == "done" and parent.step_label == "5 of 6 videos finished"
    assert parent.cost_usd == pytest.approx(0.52)                  # five at $0.10 and the failed one's $0.02
    assert engine.get(rec["batch_id"])["summary"]["failed"] == ["bad"]
    assert state["closed"] == ["finished"]


def test_a_child_a_ceiling_refuses_stops_with_the_reason_and_the_rest_carry_on(world):
    engine, activity, state, refusals = world
    refusals["b"] = "Stopped before starting: this video's turn could take Spring past its $1.00 project ceiling."
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a", "b", "c"))
    engine.go(rec["batch_id"])
    engine.wait(rec["batch_id"], 10)
    got = engine.get(rec["batch_id"])
    b = next(c for c in got["children"] if c["video_id"] == "b")
    assert b["job"]["status"] == "failed" and b["job"]["error_code"] == "ceiling" and "project ceiling" in b["job"]["error_text"]
    assert "b" not in state["ran"] and got["summary"]["finished"] == ["a", "c"]


def test_a_child_reserves_inside_the_parents_cap(world):
    engine, activity, state, _ = world
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a", "b", cap=0.5))
    # Someone else's charge counted against the batch (a child spent more than planned): b no longer fits.
    engine.update(rec["batch_id"], lambda r: r["children"][0].update(answers=[{"spent_usd": 0.6}]))
    engine.go(rec["batch_id"])
    engine.wait(rec["batch_id"], 10)
    got = engine.get(rec["batch_id"])
    assert [c["job"]["status"] for c in got["children"]].count("failed") >= 1
    assert any("left of its $1.00 cap" in (c["job"]["error_text"] or "") for c in got["children"])


def test_cancel_at_the_gate_and_after_go(world):
    engine, activity, state, _ = world
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a"))
    assert engine.cancel(rec["batch_id"])["status"] == "cancelled"
    with pytest.raises(BatchError):
        engine.go(rec["batch_id"])
    rec = engine.open_gate("f1", "local", "ask", "g", kids("a", "b", "c", "d", "e"))
    engine.go(rec["batch_id"])
    engine.cancel(rec["batch_id"])
    engine.wait(rec["batch_id"], 10)
    got = engine.get(rec["batch_id"])
    assert got["status"] == "cancelled" and got["phase"] == "cancelled"
    assert len(state["ran"]) + len(got["summary"]["cancelled"]) == 5


def test_time_is_rounds_of_three():
    assert batch_seconds(40.0, 5) == 80.0 and batch_seconds(None, 5) is None and batch_seconds(40.0, 0) is None
