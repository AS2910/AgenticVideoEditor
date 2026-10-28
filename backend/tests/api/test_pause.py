"""Run 5 addendum 3, item 5: Pause and Stop.

Pause lets the step running now finish (its vendor call is paid for), then
holds: nothing new starts, the lock stays held, Up next waits, and the strip
reads "Paused after <step>". Resume carries on from the next step and does
nothing twice. Stop puts the edit set back, keeps finished takes as
proposals and lets go. Both say what was spent and that it is still charged,
Usage lists them as Paused or Stopped turns at their real cost, and a pause
nobody ends stops itself after 30 minutes, across a restart too."""
import threading
import time

import pytest

from tests.api.test_endpoints import _agent_on, await_job, client, project, reset_state, take, voiced  # noqa: F401
from tests.agent.conftest import reply, text as said, use

PAUSED = "Paused. $0.06 spent so far is still charged. Resume to finish."
STOPPED = "Stopped. Nothing in your video changed. $0.06 spent is still charged."


def _until(check, timeout=90.0):
    """A loaded machine (the full suite beside other work) can take a while to voice a take."""
    end = time.time() + timeout
    while time.time() < end:
        if check():
            return True
        time.sleep(0.05)
    return False


class Takes:
    """Counts every take voiced (a paid vendor call, charged $0.06 as the voice vendor would); the
    first one waits for `go` once it has started."""

    def __init__(self, main, monkeypatch, hold_first=True):
        self.calls = 0
        self.entered, self.go = threading.Event(), threading.Event()
        if not hold_first:
            self.go.set()
        real = main._generate

        def generate(*a, **kw):
            self.calls += 1
            if self.calls == 1:
                self.entered.set()
                assert self.go.wait(90)
            main.ledger.record(a[0], "elevenlabs", "speech", 30, "characters", 0.06)
            return real(*a, **kw)
        monkeypatch.setattr(main, "_generate", generate)


@pytest.fixture()
def priced(client, project, monkeypatch):
    """Just do it; a take costs $0.06 (`Takes`), Voltage's own thinking a tenth of a cent a request."""
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    client.get("/videos/p1/arrangement")                 # the arrangement's one-time write, before any snapshot
    yield main
    # A test that failed mid pause must not leave a turn holding (the next test would wait on it).
    with main.pauses._cv:
        held = set(main.pauses._asked) | set(main.pauses._holding)
    main._stops.update(held)
    main.pauses.wake()
    main.pauses.clock = time.time


def _two_takes():
    return [
        reply(take("c1", text="Get 30% off today only."), stop="tool_use"),
        reply(take("c2", text="Fresh bread.", line=None, start=1.4, end=2.2), stop="tool_use"),
        reply(said("Both lines are ready to hear.")),
    ]


def _start(client, text="make it 30% off and add a line"):
    r = client.post("/videos/p1/turns", json={"text": text})
    assert r.status_code == 202, r.text
    return r.json()["job_id"]


def _lock(client, tab=None):
    return client.get("/videos/p1/lock", headers={"X-Voltage-Tab": tab} if tab else {}).json()


def _paused_mid_take(client, main, monkeypatch, script=None):
    """A turn paused while its first take was being voiced: Pause pressed mid call, then the call finishes."""
    takes = Takes(main, monkeypatch)
    scripted = _agent_on(monkeypatch, main, script or _two_takes())
    job_id = _start(client)
    assert takes.entered.wait(90)
    pressed = client.post("/videos/p1/pause")
    assert pressed.status_code == 200, pressed.text
    assert pressed.json()["pausing"] is True and pressed.json()["paused"] is False
    assert _lock(client)["video_state"] == "working"        # still finishing the step it is on
    takes.go.set()
    assert _until(lambda: (_lock(client)["lock"] or {}).get("paused"), timeout=90), (
        _lock(client), main._turn_view("p1"), takes.calls, len(scripted.calls))
    return takes, scripted, job_id


def test_pause_mid_step_finishes_that_step_then_starts_nothing(client, priced, monkeypatch):
    main = priced
    takes, scripted, _ = _paused_mid_take(client, main, monkeypatch)
    state = _lock(client)
    assert state["video_state"] == "paused"
    assert state["lock"]["action"] == "Paused after voicing line 1" and state["lock"]["holder"].startswith("pause:")
    assert state["lock"]["spent_usd"] == pytest.approx(0.061, abs=0.0015)
    items = client.get(f"/videos/p1/plans/{main.repo.latest_plan('p1').plan_id}").json()["items"]
    assert [i["status"] for i in items] == ["ready"]                         # the step that was running finished
    time.sleep(0.6)
    assert takes.calls == 1 and len(scripted.calls) == 1                     # and nothing new started
    said_now = [m["text"] for m in client.get("/videos/p1/messages").json()]
    assert said_now[-1] == PAUSED
    turn = client.get("/videos/p1/jobs?active=1").json()["turn"]
    assert turn["status"] == "paused" and turn["step"] == "Paused after voicing line 1" and turn["paused_until"]
    main.pauses.resume(turn["turn_id"])                                        # let the worker go
    assert _until(lambda: _lock(client)["lock"] is None)


def test_resume_carries_on_from_the_next_step_and_repeats_nothing(client, priced, monkeypatch):
    main = priced
    takes, scripted, job_id = _paused_mid_take(client, main, monkeypatch)
    resumed = client.post("/videos/p1/resume")
    assert resumed.status_code == 200 and resumed.json()["resumed"] is True
    job = await_job(client, job_id)
    assert job["status"] == "succeeded"
    # One take each, and three Claude requests in all: the first take was not voiced again.
    assert takes.calls == 2 and len(scripted.calls) == 3
    items = client.get(f"/videos/p1/plans/{job['result']['plan']['plan_id']}").json()["items"]
    assert sorted(i["new_text"] for i in items) == ["Fresh bread.", "Get 30% off today only."]
    assert all(i["status"] == "ready" for i in items)
    assert job["result"]["render"] is not None                               # the turn ended as any turn does
    assert _lock(client)["lock"] is None
    usage = client.get("/usage").json()["ended_early"]
    assert usage == []                                                         # resumed and finished: an ordinary turn


def test_stop_while_paused_puts_the_edit_set_back_keeps_the_takes_and_lets_go(client, priced, monkeypatch):
    main = priced
    before = main._edit_snapshot("p1")
    script = [reply(take("c1", text="Get 30% off today only."), use("ship", "s1", item_ids=[], anyway=False),
                    stop="tool_use"),
              reply(said("It is in."))]
    takes, scripted, job_id = _paused_mid_take(client, main, monkeypatch, script)
    # Paused before the ship: the take is a proposal, nothing is in the video.
    stopped = client.post("/videos/p1/stop").json()
    assert stopped["stopped"] is True
    job = await_job(client, job_id)
    assert job["result"]["reply"] == STOPPED
    assert takes.calls == 1 and len(scripted.calls) == 1                     # the ship never ran, no request after
    now = main._edit_snapshot("p1")
    assert now["edits"] == before["edits"] and now["arrangement"] == before["arrangement"]
    items = client.get(f"/videos/p1/plans/{job['result']['plan']['plan_id']}").json()["items"]
    assert [i["status"] for i in items] == ["ready"] and items[0]["edit_id"] is None
    assert _lock(client)["lock"] is None and _lock(client)["video_state"] == "ready"
    assert [m["text"] for m in client.get("/videos/p1/messages").json() if m["kind"] != "step"][-1] == STOPPED


def test_stop_after_a_line_went_in_takes_it_back_out(client, priced, monkeypatch):
    main = priced
    before = main._edit_snapshot("p1")
    script = [reply(take("c1", text="Get 30% off today only."), stop="tool_use"),
              reply(use("ship", "s1", item_ids=[], anyway=False), stop="tool_use"),
              reply(said("It is in."))]
    takes = Takes(main, monkeypatch, hold_first=False)
    shipped = threading.Event()
    real = main._ship

    def ship(*a, **kw):
        out = real(*a, **kw)
        main.pauses.ask(main._turn_view("p1")["turn_id"])        # Pause pressed while the ship ran
        shipped.set()
        return out
    monkeypatch.setattr(main, "_ship", ship)
    _agent_on(monkeypatch, main, script)
    job_id = _start(client)
    assert _until(lambda: (_lock(client)["lock"] or {}).get("paused"))
    assert _lock(client)["lock"]["action"] == "Paused after putting lines in the video"
    assert client.get("/videos/p1").json()["edits"]                          # the line is in, for now
    client.post("/videos/p1/stop")
    job = await_job(client, job_id)
    assert job["result"]["reply"] == STOPPED                                  # Stop took it back out: nothing changed
    assert main._edit_snapshot("p1")["edits"] == before["edits"] and takes.calls == 1


def test_the_buttons_and_the_words_say_the_spend_and_that_it_is_still_charged(client, priced, monkeypatch):
    main = priced
    from app.jobs import pause
    assert pause.SPENT_SO_FAR.format(0.06) == "Spent so far: $0.06"
    assert pause.PAUSED_WORDS.format(0.06) == PAUSED
    assert pause.STOPPED_WORDS.format(0.06) == STOPPED
    assert "—" not in pause.STOPPED_LANDED_WORDS and "Undo" in pause.STOPPED_LANDED_WORDS
    takes, _, _ = _paused_mid_take(client, main, monkeypatch)
    pressed_again = client.post("/videos/p1/pause").json()                    # Pause on a paused video: as it is
    assert pressed_again["paused"] is True and f"${pressed_again['spent_usd']:.2f}" == "$0.06"
    stopped = client.post("/videos/p1/stop").json()
    assert stopped["message"] == STOPPED and f"${stopped['spent_usd']:.2f}" == "$0.06"
    assert _until(lambda: _lock(client)["lock"] is None)


def test_usage_lists_paused_and_stopped_turns_at_their_real_cost(client, priced, monkeypatch):
    main = priced
    _paused_mid_take(client, main, monkeypatch)
    turn_id = main._turn_view("p1")["turn_id"]
    [row] = client.get("/usage").json()["ended_early"]
    real = main.ledger.spent_usd_by_turn("p1", turn_id)
    assert row["label"] == "Paused" and row["state"] == "paused" and row["video_id"] == "p1"
    assert row["spent_usd"] == pytest.approx(real) and f"${row['spent_usd']:.2f}" == "$0.06"
    assert row["filename"]
    client.post("/videos/p1/stop")
    assert _until(lambda: _lock(client)["lock"] is None)
    [row] = client.get("/usage").json()["ended_early"]
    assert row["label"] == "Stopped" and row["spent_usd"] == pytest.approx(main.ledger.spent_usd_by_turn("p1", turn_id))


def test_a_pause_nobody_ends_stops_itself_after_30_minutes(client, priced, monkeypatch):
    main = priced
    now = [time.time()]
    main.pauses.clock = lambda: now[0]
    takes, scripted, job_id = _paused_mid_take(client, main, monkeypatch)
    now[0] += 29 * 60
    time.sleep(0.5)
    assert _lock(client)["video_state"] == "paused"
    now[0] += 61
    job = await_job(client, job_id)
    assert job["result"]["reply"] == STOPPED                                  # the same words as Stop
    assert _lock(client)["lock"] is None and takes.calls == 1 and len(scripted.calls) == 1
    assert client.get("/usage").json()["ended_early"][0]["label"] == "Stopped"


def _left_by_a_restart(main, turn_id="t77", minutes_left=30.0, landed=None):
    """What a server that died while a turn was paused leaves: the pause lock (with the snapshot from
    before the turn), the settings' deadline, the turn view; then the new server starts up.
    `landed()` puts something in the video after the snapshot, as the turn did before it paused."""
    before = main._edit_snapshot("p1")
    hash_before = main._final_hash("p1")
    if landed is not None:
        landed()
    lock = main.locks.take("p1", f"pause:{turn_id}", "Paused after voicing line 1", lease=3 * 3600, snapshot=before)
    until = main.pauses.clock() + minutes_left * 60
    main.repo.set_settings("p1", paused={"turn_id": turn_id, "holder": "turn:j1", "after": "voicing line 1",
                                         "until": until, "since": lock.started_at, "hash_before": hash_before})
    main._set_turn("p1", turn_id=turn_id, status="paused", step="Paused after voicing line 1", started_at=lock.started_at)
    gone = main.locks.clear_leftovers()                                       # the new server's startup
    main._recover_queue()
    return before, gone


def test_a_restart_while_paused_keeps_it_paused_until_resume_stop_or_its_deadline(client, priced, monkeypatch):
    main = priced
    plan_id = voiced(client, monkeypatch, text="Fresh every morning.")["plan"]["plan_id"]

    def landed():
        # The turn had put its line in the video before the server died.
        assert client.post(f"/videos/p1/plans/{plan_id}/approve", json={}).status_code == 200
        assert _until(lambda: _lock(client)["lock"] is None)
        assert client.get("/videos/p1").json()["edits"]
    before, gone = _left_by_a_restart(main, landed=landed)
    assert gone == []                                                         # startup kept the pause
    state = _lock(client)
    assert state["video_state"] == "paused" and state["lock"]["paused_after"] == "voicing line 1"
    assert client.get("/videos/p1/jobs?active=1").json()["turn"]["status"] == "paused"
    stopped = client.post("/videos/p1/stop").json()
    assert stopped["message"].startswith("Stopped. Nothing in your video changed. $")
    assert _lock(client)["lock"] is None and main._edit_snapshot("p1")["edits"] == before["edits"]
    assert client.get("/videos/p1/jobs?active=1").json()["turn"]["step"] == "Stopped"


def test_a_restart_while_paused_still_stops_itself_at_the_persisted_deadline(client, priced):
    main = priced
    now = [time.time()]
    main.pauses.clock = lambda: now[0]
    _left_by_a_restart(main, minutes_left=5)
    assert _lock(client)["video_state"] == "paused"
    now[0] += 5 * 60 + 1
    assert main._auto_stop_due() == 1                                         # the watcher's tick, or any read of the lock
    assert _lock(client)["lock"] is None
    assert [m["text"] for m in client.get("/videos/p1/messages").json()][-1].startswith("Stopped. Nothing in your video changed.")


def test_resume_after_a_restart_carries_the_same_turn_on_without_voicing_again(client, priced, monkeypatch):
    main = priced
    _left_by_a_restart(main, turn_id="t77")
    takes = Takes(main, monkeypatch, hold_first=False)
    scripted = _agent_on(monkeypatch, main, [reply(said("Carried on. Nothing else was needed."))])
    out = client.post("/videos/p1/resume")
    assert out.status_code == 200, out.text
    job = await_job(client, out.json()["turn"]["job_id"])
    assert job["status"] == "succeeded" and takes.calls == 0 and len(scripted.calls) == 1
    asked = scripted.calls[0]["messages"][-1]["content"]
    assert any("pressed Resume after the server restarted" in b.get("text", "") for b in asked)
    assert main._turn_view("p1")["turn_id"] == "t77"                          # the same turn, carried on
    assert _lock(client)["lock"] is None


def test_up_next_waits_while_paused_and_its_card_reads_paused(client, priced, monkeypatch):
    main = priced
    takes = Takes(main, monkeypatch)
    _agent_on(monkeypatch, main, _two_takes() + [reply(said("Warmer now."))])
    first = client.post("/videos/p1/queue", json={"kind": "goal", "payload": {"text": "make it 30% off and add a line"}}).json()
    assert takes.entered.wait(90)
    client.post("/videos/p1/pause")
    takes.go.set()
    assert _until(lambda: (_lock(client)["lock"] or {}).get("paused"))
    second = client.post("/videos/p1/queue", json={"kind": "goal", "payload": {"text": "make the opening warmer"}}).json()
    time.sleep(0.6)
    queue = {i["id"]: i["status"] for i in client.get("/videos/p1/queue").json()["items"]}
    assert queue == {first["id"]: "paused", second["id"]: "queued"}            # the second waits
    from app.jobs.queue import CARD_STATES
    assert "paused" in CARD_STATES
    client.post("/videos/p1/resume")
    assert _until(lambda: not client.get("/videos/p1/queue").json()["items"], timeout=60)
    ended = {i["id"]: i["status"] for i in client.get("/videos/p1/queue").json()["recent"]}
    assert ended == {first["id"]: "done", second["id"]: "done"}


def test_another_tab_sees_paused(client, priced, monkeypatch):
    main = priced
    _paused_mid_take(client, main, monkeypatch)
    other = _lock(client, tab="tab-two")
    assert other["video_state"] == "paused" and other["lock"]["paused"] is True
    assert other["lock"]["action"] == "Paused after voicing line 1"
    assert client.get("/videos/p1/jobs?active=1", headers={"X-Voltage-Tab": "tab-two"}).json()["turn"]["status"] == "paused"
    busy = client.post("/videos/p1/turns", json={"text": "and make it louder"}, headers={"X-Voltage-Tab": "tab-two"})
    assert busy.status_code == 409                                            # the lock stays held while paused
    client.post("/videos/p1/stop")
    assert _until(lambda: _lock(client)["lock"] is None)


def test_only_a_turn_pauses(client, priced):
    refused = client.post("/videos/p1/pause")
    assert refused.status_code == 409 and refused.json()["detail"] == "Nothing is running, so there is nothing to pause."
    priced.locks.take("p1", "req-undo", "Undoing", stoppable=False)
    refused = client.post("/videos/p1/pause")
    assert refused.status_code == 409 and refused.json()["detail"] == "Undoing is one step, so it cannot be paused. Stop it instead."
    assert client.post("/videos/p1/resume").json()["detail"] == "Nothing is paused."
    priced.locks.release("p1", "req-undo")


def test_the_fast_path_pauses_after_its_take_and_finishes_on_resume(client, priced, monkeypatch):
    main = priced
    takes = Takes(main, monkeypatch)
    scripted = _agent_on(monkeypatch, main, [])
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    line = main._lines(main.repo.get("p1"))[0]
    r = client.post("/videos/p1/lines/quick", json={"start": line.start, "end": line.end, "text": "Get 30% off today only.",
                                                    "before": line.text})
    assert r.status_code == 202 and r.json()["route"] == "fast", r.text
    assert takes.entered.wait(90)
    client.post("/videos/p1/pause")
    takes.go.set()
    assert _until(lambda: (_lock(client)["lock"] or {}).get("paused")), (_lock(client), main._turn_view("p1"))
    assert _lock(client)["lock"]["action"] == f"Paused after voicing line {line.index}"
    client.post("/videos/p1/resume")
    job = await_job(client, r.json()["job_id"])
    assert job["status"] == "succeeded" and job["result"]["reply"].startswith(f"Voiced line {line.index} straight away")
    assert takes.calls == 1 and scripted.calls == []


def test_the_state_names_are_shared_with_the_front_end():
    """One list of names each side: a card's states and a video's (item 4 reads them)."""
    import re
    from pathlib import Path
    from app.jobs.pause import VIDEO_STATES
    from app.jobs.queue import CARD_STATES
    src = Path(__file__).resolve().parents[3] / "frontend" / "src" / "lib"
    cards = re.search(r"QUEUE_CARD_STATES: readonly QueueCardState\[\] = \[([^\]]*)\]", (src / "queueState.ts").read_text())
    videos = re.search(r"VIDEO_STATES: readonly VideoState\[\] = \[([^\]]*)\]", (src / "videoState.ts").read_text())
    assert tuple(re.findall(r"'(\w+)'", cards.group(1))) == CARD_STATES
    assert tuple(re.findall(r"'(\w+)'", videos.group(1))) == VIDEO_STATES
