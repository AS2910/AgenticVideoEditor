"""One edit at a time per video (2026-10-25), Part 3: Up next.

A change asked for while the video is Working waits (at most three); after a
success the next starts by itself against the video as it is then; after a
failure or a Stop the queue pauses until Run next or Clear queue."""
import threading
import time

import pytest

from tests.api.test_endpoints import _agent_on, client, project, reset_state, settle_renders, take, voiced  # noqa: F401
from tests.api.test_jobs import wait_job
from tests.agent.conftest import reply, text as said, use


def _held_render(monkeypatch):
    import app.api.main as main
    gate = threading.Event()
    real = main._render_now

    def held(*a, **kw):
        assert gate.wait(30), "the render was never let go"
        return real(*a, **kw)
    monkeypatch.setattr(main, "_render_now", held)
    return gate


def _until(check, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def _queue(client):
    return client.get("/videos/p1/queue").json()


def _two_proposals(client, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [
        reply(take("c1", text="Hi.", line=None, start=0.0, end=1.1), take("c2", text="Bye.", line=None, start=1.2, end=2.3), stop="tool_use"),
        reply(said("Two lines to hear.")),
    ])
    from tests.api.test_endpoints import send
    return send(client, "two lines")["plan"]


def test_two_quick_adds_the_first_runs_the_second_waits_and_both_land_in_order(client, project, monkeypatch):
    import app.api.main as main
    plan = _two_proposals(client, monkeypatch)
    assert [i["status"] for i in plan["items"]] == ["ready", "ready"]
    gate = _held_render(monkeypatch)
    first = client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i1"]})
    assert first.status_code == 200
    second = client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i2"]})
    assert second.status_code == 409 and second.json()["detail"]["code"] == "video_busy"
    queued = client.post("/videos/p1/queue", json={"kind": "action", "label": "Add line 2", "payload": {"op": "add", "item_ids": ["i2"]}})
    assert queued.status_code == 201 and queued.json()["status"] == "queued"
    assert [i["label"] for i in _queue(client)["items"]] == ["Add line 2"]

    gate.set()                                                   # the first lands; the second starts by itself
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    settle_renders()
    edits = [e for e in client.get("/videos/p1").json()["edits"] if not e.get("reverted")]
    assert [e["edit_id"] for e in edits] == ["e1", "e2"]                          # both landed, in order
    items = client.get(f"/videos/p1/plans/{plan['plan_id']}").json()["items"]
    assert [(i["item_id"], i["edit_id"]) for i in items] == [("i1", "e1"), ("i2", "e2")]


def test_three_queued_run_in_order_and_a_failure_pauses_the_queue(client, project, monkeypatch):
    import app.api.main as main
    plan = _two_proposals(client, monkeypatch)
    main.locks.take("p1", "J999", "Adding")                    # someone else is Working on it
    add = lambda label, payload: client.post("/videos/p1/queue", json={"kind": "action", "label": label, "payload": payload})
    assert add("Add line 1", {"op": "add", "item_ids": ["i1"]}).status_code == 201
    assert add("Add a gone line", {"op": "add", "item_ids": ["i9"]}).status_code == 201
    assert add("Add line 2", {"op": "add", "item_ids": ["i2"]}).status_code == 201
    full = add("One more", {"op": "add_all"})
    assert full.status_code == 409 and full.json()["detail"] == "Up next holds 3 changes. Remove one first."

    main.locks.release("p1", "J999", "done")                   # the work lands: the queue runs, in order
    assert _until(lambda: _queue(client)["paused"])
    settle_renders()
    edits = [e["edit_id"] for e in client.get("/videos/p1").json()["edits"] if not e.get("reverted")]
    assert edits == ["e1"]                                      # the first ran; the second failed; the third waits
    q = _queue(client)
    assert q["paused"] and [i["label"] for i in q["items"]] == ["Add line 2"]
    assert client.get("/videos/p1/messages").json()[-1]["text"] == "Up next is paused. Run next, or Clear queue?"

    client.post("/videos/p1/queue/run-next")
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    settle_renders()
    assert [e["edit_id"] for e in client.get("/videos/p1").json()["edits"] if not e.get("reverted")] == ["e1", "e2"]


def test_a_stop_pauses_the_queue_and_clear_empties_it(client, project, monkeypatch):
    import app.api.main as main
    plan = _two_proposals(client, monkeypatch)
    gate = _held_render(monkeypatch)
    client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i1"]})
    client.post("/videos/p1/queue", json={"kind": "action", "payload": {"op": "add", "item_ids": ["i2"]}})
    assert client.post("/videos/p1/stop").json()["stopped"]
    assert _queue(client)["paused"] and [i["label"] for i in _queue(client)["items"]] == ["Add a line"]
    gate.set()
    assert client.post("/videos/p1/queue/clear").json() == {"items": [], "paused": False}
    settle_renders()
    assert [e for e in client.get("/videos/p1").json()["edits"] if not e.get("reverted")] == []


def test_a_queued_goal_is_planned_against_the_video_as_it_is_then(client, project, monkeypatch):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    scripted = _agent_on(monkeypatch, main, [reply(said("Done, warmer now."))])
    client.post("/videos/p1/queue", json={"kind": "goal", "payload": {"text": "Make it warmer"}})
    assert scripted.calls == []                                 # nothing runs while the video is Working
    main.locks.release("p1", "J999", "done")
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    assert any("Make it warmer" in (c.get("text") or "") for c in scripted.calls[0]["messages"][-1]["content"])


def test_waiting_changes_can_be_reworded_removed_and_reordered(client, project):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    ids = [client.post("/videos/p1/queue", json={"kind": "goal", "payload": {"text": t}}).json()["id"] for t in ("one", "two", "three")]
    assert client.patch(f"/videos/p1/queue/{ids[0]}", json={"label": "First", "payload": {"text": "one, warmer"}}).json()["label"] == "First"
    assert [i["id"] for i in client.put("/videos/p1/queue/order", json={"ids": [ids[2], ids[0]]}).json()["items"]] == [ids[2], ids[0], ids[1]]
    assert [i["id"] for i in client.delete(f"/videos/p1/queue/{ids[0]}").json()["items"]] == [ids[2], ids[1]]
    assert client.delete(f"/videos/p1/queue/{ids[0]}").status_code == 409
    assert client.post("/videos/p1/queue", json={"kind": "action", "payload": {"op": "voice_everything"}}).status_code == 422
    main.locks.release("p1", "J999", "stopped")                 # nothing ran: a Stop leaves them waiting, paused
    assert _queue(client)["paused"] and len(_queue(client)["items"]) == 2
