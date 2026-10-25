"""One edit at a time per video (2026-10-25), Part 2: Stop.

POST /videos/{id}/stop cancels queued work, lets a vendor call already
running finish (and never tries it again), marks the turn or job stopped,
lets go of the lock and says what was spent. An Add or a turn stopped before
it lands leaves the edit set exactly as it was before the click."""
import threading

from tests.api.test_endpoints import _agent_on, client, project, reset_state, send, take, voiced  # noqa: F401
from tests.api.test_jobs import wait_job
from tests.agent.conftest import reply, text as said, use


def _edit_set(main, video_id="p1"):
    """The edit set as stored: every edit row, every plan, the arrangement."""
    return main._edit_snapshot(video_id)


def test_stop_during_an_add_puts_the_edit_set_back_exactly(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch, text="Fresh every morning.")
    plan_id = done["plan"]["plan_id"]
    client.put("/videos/p1/arrangement", json={"order": [], "pins": {}, "min_gap": 0.25, "end": "extend"})
    before = _edit_set(main)
    gate = threading.Event()
    real = main._render_now

    def held(*a, **kw):
        assert gate.wait(30)
        return real(*a, **kw)
    monkeypatch.setattr(main, "_render_now", held)

    added = client.post(f"/videos/p1/plans/{plan_id}/approve", json={}).json()
    assert [a["edit_id"] for a in added["approved"]] == ["e1"] and _edit_set(main) != before
    stopped = client.post("/videos/p1/stop").json()
    assert stopped["stopped"] is True and stopped["spent_usd"] == 0.0
    assert stopped["message"] == "Stopped. Nothing in your video changed. $0.00 spent."
    assert _edit_set(main) == before                                  # the edit set equals the snapshot before the click
    assert client.get("/videos/p1/lock").json()["lock"] is None
    job = wait_job(client, added["render_job"]["job_id"])
    assert job["status"] == "cancelled" and job["step_label"] == "Stopped"

    gate.set()
    import time
    deadline = time.time() + 30
    while main._rendering.get("p1") and time.time() < deadline:
        time.sleep(0.05)
    time.sleep(0.2)
    assert _edit_set(main) == before                                  # the render that finished late changed nothing
    latest = client.get("/videos/p1/renders/latest?mode=final").json()["latest"]
    assert latest is None or "e1" not in (latest["includes"] or {}).get("edit_ids", [])
    said_last = client.get("/videos/p1/messages").json()[-1]
    assert said_last["role"] == "assistant" and said_last["text"] == stopped["message"]


def test_stop_during_a_turn_adds_nothing_keeps_the_takes_and_says_the_spend(client, project, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    before = _edit_set(main)
    real = main._ship

    def shipping(*a, **kw):
        out = real(*a, **kw)
        main.stop_video("p1", "local")                                # Stop just after the turn put a line in the video
        return out
    monkeypatch.setattr(main, "_ship", shipping)
    _agent_on(monkeypatch, main, [
        reply(take("c1", text="Get 30% off today only."), stop="tool_use"),
        reply(use("ship", "s1", item_ids=[], anyway=False), stop="tool_use"),
        reply(take("c2", text="Fresh every morning.", line=None, start=1.4, end=2.2), stop="tool_use"),
        reply(said("All done, both lines are in.")),
    ])
    out = send(client, "make it 30% off and add a line")
    assert out["reply"].startswith("Stopped. Nothing in your video changed. $") and out["reply"].endswith(" spent.")
    assert out["turn_usd"] > 0 and f"${out['turn_usd']:.2f}" in out["reply"]
    assert client.get("/videos/p1").json()["edits"] == []
    now = _edit_set(main)
    assert now["edits"] == before["edits"] and now["arrangement"] == before["arrangement"]   # nothing added to the video
    items = client.get(f"/videos/p1/plans/{out['plan']['plan_id']}").json()["items"]
    assert [i["status"] for i in items] == ["ready"]                                        # the finished take stays as a proposal
    assert all(i["candidate"] and i["edit_id"] is None for i in items)
    assert client.get("/videos/p1/lock").json()["lock"] is None
    assert any(m["text"] == out["reply"] for m in client.get("/videos/p1/messages").json())


def test_a_stopped_turn_is_not_tried_again():
    from app.adapters.base import VendorError
    from app.jobs.runner import with_retries
    tries = []

    def flaky():
        tries.append(1)
        raise VendorError("down")
    try:
        with_retries(flaky, attempts=3, base_delay=0.0, sleep=lambda s: None, stopped=lambda: True)
    except VendorError:
        pass
    assert len(tries) == 1


def test_stop_at_the_go_drops_the_question_and_frees_the_video(client, project, monkeypatch):
    import app.api.main as main
    _agent_on(monkeypatch, main, [reply(take("c"), stop="tool_use")])
    client.put("/videos/p1/settings", json={"autonomy": "ask"})
    out = send(client, "make it 30% off")
    assert out["question"]["gate"] and client.get("/videos/p1/lock").json()["lock"]["waiting"]
    stopped = client.post("/videos/p1/stop").json()
    assert stopped["stopped"] and stopped["message"] == "Stopped. Nothing in your video changed. $0.00 spent."
    assert client.get("/videos/p1/lock").json()["lock"] is None
    plan = client.get(f"/videos/p1/plans/{out['plan']['plan_id']}").json()
    assert plan["status"] != "clarifying" and plan["question"]["resolved"]["why"] == "you stopped"


def test_an_undo_is_atomic_once_it_started(client, project):
    import app.api.main as main
    main.locks.take("p1", "req-undo", "Undoing", stoppable=False)
    refused = client.post("/videos/p1/stop")
    assert refused.status_code == 409 and "cannot be stopped once it starts" in refused.json()["detail"]
    assert main.locks.get("p1").holder == "req-undo"


def test_stop_on_a_ready_video_changes_nothing(client, project):
    out = client.post("/videos/p1/stop").json()
    assert out == {"stopped": False, "cancelled": 0, "spent_usd": 0.0, "message": None, "lock": None}
