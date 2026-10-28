"""Run 5 addendum 3, item 3: messages queue clearly.

Anything typed while the video is Working waits in Up next, in order, and
shows as a card. The cards run one at a time, never merged: each starts only
after the one before it let the video go (its render in the video), and plans
against the video as that one left it. A waiting card can be reworded or
removed until it starts; after that the server refuses with a plain sentence.
Up next is in the database, so a reload or a server restart keeps it. A card
whose turn ends on a question (the one approval over the spending limit) stops
the queue there; the rest wait until it is answered."""
import time

import pytest

from tests.api.test_endpoints import _agent_on, client, project, reset_state, settle_renders, take, voiced  # noqa: F401
from tests.agent.conftest import reply, text as said, use

pytestmark = pytest.mark.landing         # the render after a change holds the lock, as in the app


def _until(check, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


def _queue(client):
    return client.get("/videos/p1/queue").json()


def _type(client, words):
    """What the composer does with words typed while Working."""
    r = client.post("/videos/p1/queue", json={"kind": "goal", "payload": {"text": words}})
    assert r.status_code == 201, r.text
    return r.json()


def _watch(scripted):
    """Each call to Claude, with what held the video and what Up next was running at that moment."""
    import app.api.main as main
    seen: list[dict] = []
    real = scripted._create

    def create(**params):
        lock = main.locks.get("p1")
        running = [i for i in main.up_next.items("p1") if i.status == "running"]
        last = params["messages"][-1]["content"] if params.get("messages") else []
        words = " ".join(b.get("text", "") for b in last if isinstance(b, dict)) if isinstance(last, list) else str(last)
        live = [e for e in main.repo.list_edits("p1") if not getattr(e, "reverted", False)]
        seen.append({"holder": lock.holder if lock else None, "running": [i.label for i in running], "words": words,
                     "edits": len(live)})
        return real(**params)
    scripted.beta.messages.create = create
    return seen


def test_two_messages_typed_while_working_run_in_order_one_at_a_time_never_merged(client, project, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [reply(said("Warmer now.")), reply(said("Shorter now."))])
    seen = _watch(scripted)
    main.locks.take("p1", "J999", "Adding")                    # Working
    a, b = _type(client, "Make the opening warmer"), _type(client, "Then make the ending shorter")
    q = _queue(client)
    assert [(i["label"], i["status"], i["position"]) for i in q["items"]] == [
        ("Make the opening warmer", "queued", a["position"]), ("Then make the ending shorter", "queued", b["position"])]
    assert a["position"] < b["position"] and scripted.calls == []

    main.locks.release("p1", "J999", "done")
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    # In order, one at a time: each call had exactly its own card running, under a turn's lock.
    assert [s["running"] for s in seen] == [["Make the opening warmer"], ["Then make the ending shorter"]]
    assert all(s["holder"] and s["holder"].startswith("turn:") for s in seen)
    # Never merged: each turn heard its own words and only those.
    assert "warmer" in seen[0]["words"] and "shorter" not in seen[0]["words"]
    assert "shorter" in seen[1]["words"] and "warmer" not in seen[1]["words"]
    # Two turns in the thread, each your words carrying its card; both cards end Done.
    said_by_you = [m for m in client.get("/videos/p1/messages").json() if m["role"] == "user"]
    assert [(m["text"], (m.get("data") or {}).get("queued")) for m in said_by_you] == [
        ("Make the opening warmer", a["id"]), ("Then make the ending shorter", b["id"])]
    assert [(i["id"], i["status"]) for i in _queue(client)["recent"]] == [(a["id"], "done"), (b["id"], "done")]


def test_the_next_starts_after_the_one_before_let_go_and_plans_against_what_it_left(client, project, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [
        reply(take("c1", text="Get 30% off today only."), stop="tool_use"), reply(said("Done.")),
        reply(said("Looked again.")),
    ])
    at_start: list[tuple] = []
    real_run = main._run_next

    def run_next(video_id):
        # The moment the next card starts: the one before let the video go (its render was in
        # the video before it did), and what it proposed is there.
        if main.up_next.waiting(video_id):
            plan = main.repo.latest_plan(video_id)
            at_start.append((main.locks.get(video_id) is None, len(plan.items) if plan else 0))
        return real_run(video_id)
    monkeypatch.setattr(main, "_run_next", run_next)
    main.locks.take("p1", "J999", "Adding")
    _type(client, "Make it 30% off")
    _type(client, "Now check the new line")
    # Typed while the video had no line voiced: a snapshot taken now would have no plan in it.
    main.locks.release("p1", "J999", "done")
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    settle_renders()
    assert at_start == [(True, 0), (True, 1)]
    # The second turn's own opening, read when it started, names the line the first one voiced.
    opening = " ".join(b.get("text", "") for b in scripted.calls[-1]["messages"][-1]["content"])
    assert "The plan so far" in opening and "Get 30% off today only." in opening and "Now check the new line" in opening


def test_a_waiting_card_can_be_edited_or_removed_and_not_once_it_started(client, project, monkeypatch):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    a, b = _type(client, "Make it warmer"), _type(client, "Make it louder")
    edited = client.patch(f"/videos/p1/queue/{a['id']}", json={"payload": {"text": "Make the first line warmer"}})
    assert edited.status_code == 200
    assert (edited.json()["label"], edited.json()["payload"]["text"]) == ("Make the first line warmer", "Make the first line warmer")
    assert client.delete(f"/videos/p1/queue/{b['id']}").status_code == 200
    assert [i["id"] for i in _queue(client)["items"]] == [a["id"]]
    assert client.patch(f"/videos/p1/queue/{a['id']}", json={"payload": {"text": "  "}}).status_code == 422

    # It starts: from now on it cannot be changed, and the answer says why in one plain sentence.
    with main.database.tx() as c:
        c.execute("UPDATE video_queue SET status = 'running' WHERE id = ?", (a["id"],))
    late = client.patch(f"/videos/p1/queue/{a['id']}", json={"payload": {"text": "Something else"}})
    assert late.status_code == 409 and late.json()["detail"] == "That one has already started, so it can no longer be edited."
    gone = client.delete(f"/videos/p1/queue/{a['id']}")
    assert gone.status_code == 409 and gone.json()["detail"] == "That one has already started, so it can no longer be removed. Stop it instead."
    assert main.up_next.get(a["id"]).payload["text"] == "Make the first line warmer"
    main.up_next.finish(a["id"], "done")
    after = client.patch(f"/videos/p1/queue/{a['id']}", json={"label": "x"})
    assert after.status_code == 409 and after.json()["detail"] == "That one already ran, so it can no longer be edited."


def test_a_stop_marks_the_running_card_stopped_and_the_rest_wait(client, project, monkeypatch):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    a, b = _type(client, "one"), _type(client, "two")
    main.up_next.claim_next("p1")                               # the first is running
    main.locks.release("p1", "J999", "stopped")
    q = _queue(client)
    assert [(i["id"], i["status"]) for i in q["recent"]] == [(a["id"], "stopped")]
    assert q["paused"] and [(i["id"], i["status"]) for i in q["items"]] == [(b["id"], "queued")]


def test_the_queue_survives_a_restart(client, project, monkeypatch):
    import app.api.main as main
    from app.jobs.queue import VideoQueue
    main.locks.take("p1", "J999", "Adding")
    a, b, c = _type(client, "one"), _type(client, "two"), _type(client, "three")
    main.up_next.claim_next("p1")                               # "one" was running when the server stopped
    # A new server: the same database, its locks cleared, then Up next recovered.
    main.locks.clear_leftovers()
    main._recover_queue()
    fresh = VideoQueue(main.database)
    assert [(i.id, i.status) for i in fresh.items("p1")] == [(b["id"], "queued"), (c["id"], "queued")]
    ended = fresh.get(a["id"])
    assert (ended.status, ended.error) == ("failed", "The server restarted while it ran.")
    q = _queue(client)
    assert q["paused"] and [i["label"] for i in q["items"]] == ["two", "three"]
    assert client.get("/videos/p1/messages").json()[-1]["text"] == "Up next is paused. Run next, or Clear queue?"
    # Nothing paid starts by itself after a restart; Run next goes on in order.
    _agent_on(monkeypatch, main, [reply(said("Two.")), reply(said("Three."))])
    client.post("/videos/p1/queue/run-next")
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    assert [(i["label"], i["status"]) for i in _queue(client)["recent"]] == [("one", "failed"), ("two", "done"), ("three", "done")]


def test_a_card_waiting_on_its_go_is_left_running_by_a_restart(client, project, monkeypatch):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    a, _b = _type(client, "one"), _type(client, "two")
    main.up_next.claim_next("p1")
    main.locks.hand("p1", "J999", "gate:T1", action="Waiting for your go")
    main.locks.clear_leftovers()
    main._recover_queue()
    assert main.up_next.get(a["id"]).status == "running" and not _queue(client)["paused"]


def test_a_card_that_needs_approval_stops_the_queue_there_until_it_is_answered(client, project, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "ask"})
    client.put("/me/settings", json={"ask_over_usd": 0})       # over the spending limit: Voltage asks once
    take_ = use("synthesize_take", "c", text="Get 30% off today only.", voice_id="mock", line=1, start=None, end=None,
                direction=None, mix=None, item_id=None)
    scripted = _agent_on(monkeypatch, main, [
        reply(take_, stop="tool_use"),                         # the first card: asks before paying
        reply(said("Voicing it now."), use("synthesize_take", "d", text="Get 30% off today only.", voice_id="mock", line=1,
                                           start=None, end=None, direction=None, mix=None, item_id=None), stop="tool_use"),
        reply(said("Done. Hear it below.")),
        reply(said("Second done.")),                           # the second card, once the first is answered
    ])
    main.locks.take("p1", "J999", "Adding")
    a, b = _type(client, "make it 30% off"), _type(client, "and check it")
    main.locks.release("p1", "J999", "done")
    assert _until(lambda: getattr(main.repo.latest_plan("p1"), "status", None) == "clarifying"
                  and (main.locks.get("p1") is None or main.locks.get("p1").gate), 30)
    time.sleep(0.3)
    q = _queue(client)
    # Stopped at that card: it is still running (waiting for your answer), the next one still waits.
    assert [(i["id"], i["status"]) for i in q["items"]] == [(a["id"], "running"), (b["id"], "queued")]
    assert len(scripted.calls) == 1

    answer = client.post("/videos/p1/turns", json={"text": "go"})
    assert answer.status_code == 202, answer.text
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    assert [(i["id"], i["status"]) for i in _queue(client)["recent"]] == [(a["id"], "done"), (b["id"], "done")]
    assert "check it" in str(scripted.calls[-1]["messages"][-1])


def test_a_card_whose_turn_asks_which_one_holds_the_rest_until_it_is_answered(client, project, monkeypatch):
    import app.api.main as main
    ask = {"question": "Should the offer say 30% or 25%?",
           "options": [{"label": "30%", "detail": ""}, {"label": "25%", "detail": ""}], "guess": "30%"}
    scripted = _agent_on(monkeypatch, main, [
        reply(use("ask", "a1", **ask), stop="tool_use"),       # the first card asks a question about meaning
        reply(said("30% it is.")),                             # your answer's turn
        reply(said("Second done.")),                           # then the second card
    ])
    main.locks.take("p1", "J999", "Adding")
    a, b = _type(client, "change the offer"), _type(client, "then tidy up")
    main.locks.release("p1", "J999", "done")
    assert _until(lambda: getattr(main.repo.latest_plan("p1"), "status", None) == "clarifying" and main.locks.get("p1") is None)
    time.sleep(0.3)
    # The video is Ready for your answer; the queue does not run past the question.
    assert [(i["id"], i["status"]) for i in _queue(client)["items"]] == [(a["id"], "running"), (b["id"], "queued")]
    assert len(scripted.calls) == 1
    assert client.post("/videos/p1/turns", json={"text": "30%"}).status_code == 202
    assert _until(lambda: _queue(client)["items"] == [] and main.locks.get("p1") is None)
    assert [(i["id"], i["status"]) for i in _queue(client)["recent"]] == [(a["id"], "done"), (b["id"], "done")]
    assert "then tidy up" in str(scripted.calls[-1]["messages"][-1])
