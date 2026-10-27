"""B3's export engine on its own: one parent and one child per file, two
at a time, a failed render tried once more then Failed with its reason, a
video handed on once all its files are made, the parent's summary."""
import threading
import time

import pytest

from app.failures import OUR_END
from app.jobs.activity import ActivityJobs
from app.jobs.exports import ExportEngine, ExportError
from app.store.db import Database


def item(video, preset):
    return {"video_id": video, "filename": f"{video}.mp4", "stage": "approved", "approved": True,
            "preset": {"name": preset, "platform": "feed"}}


@pytest.fixture()
def world():
    activity = ActivityJobs(Database(":memory:"))
    meta: dict[str, str] = {}
    state = {"inside": 0, "most": 0, "calls": [], "done": [], "closed": []}
    lock = threading.Lock()

    def render(record, it):
        with lock:
            state["inside"] += 1
            state["most"] = max(state["most"], state["inside"])
            state["calls"].append((it["video_id"], it["preset"]["name"], it["attempts"]))
        time.sleep(0.03)
        with lock:
            state["inside"] -= 1
        if it["video_id"] == "bad" or (it["video_id"] == "flaky" and it["attempts"] == 1):
            raise RuntimeError("encoder fell over")
        return {"name": f"{it['video_id']}-{it['preset']['name']}.mp4", "size": 10}

    engine = ExportEngine(activity, meta.get, meta.__setitem__, render,
                          on_video_done=lambda record, video: state["done"].append(video),
                          on_close=lambda record: state["closed"].append(record["summary"]))
    return engine, activity, state


def test_files_render_two_at_a_time_with_one_retry(world):
    engine, activity, state = world
    made = engine.start("f1", "local", [item("a", "Reels"), item("a", "Feed"), item("flaky", "Feed"), item("bad", "Feed")])
    engine.wait(made["export_id"], 10)
    record = engine.get(made["export_id"])
    assert state["most"] == 2
    rows = {(i["video_id"], i["preset"]["name"]): i for i in record["items"]}
    assert rows[("flaky", "Feed")]["file"] and rows[("flaky", "Feed")]["attempts"] == 2
    bad = rows[("bad", "Feed")]
    assert bad["file"] is None and bad["error"] == "The render failed twice. " + OUR_END    # run 5 item 1: never the encoder's words
    assert bad["job"]["status"] == "failed" and bad["job"]["error_code"] == "render_failed"
    assert [c for c in state["calls"] if c[0] == "bad"] == [("bad", "Feed", 1), ("bad", "Feed", 2)]
    assert sorted(state["done"]) == ["a", "flaky"]                      # once each, never "bad"
    assert state["closed"] == [{"ready": 3, "failed": 1}]
    parent = activity.get(made["export_id"])
    assert parent.status == "done" and parent.step_label == "3 of 4 files ready, 1 failed" and parent.progress == 1.0
    assert parent.video_id == "f1" and all(activity.get(i["job_id"]).detail["parent_id"] == parent.job_id for i in record["items"])
    assert engine.of_project("f1") == [made["export_id"]] and engine.get(made["export_id"], "f2") is None


def test_nothing_to_export_is_refused(world):
    engine, _, _ = world
    with pytest.raises(ExportError):
        engine.start("f1", "local", [])


def test_batch_export_jobs_stay_out_of_a_single_exports_eta(world):
    engine, activity, _ = world
    made = engine.start("f1", "local", [item("a", "Feed")])
    engine.wait(made["export_id"], 10)
    assert activity.estimate("export") is None
