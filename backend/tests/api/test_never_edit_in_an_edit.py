"""Run 5 addendum 3, item 2: never edit in the middle of another edit.

Two edits fired at the same moment from two tabs (two sessions, real threads
and real asyncio against the app): exactly one runs, the other is refused
with 409 `video_busy` and a plain sentence (a chat's words then wait in Up
next, which the editor does on that 409). The lock is held until the render
is in the video: the fast path's take, Render now, an export that renders, a
batch export's file and the render after a short change (an undo, a mix
change) all hold it. The route test in test_video_lock.py walks every write
route; this file proves the race."""
import asyncio
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from tests.api.test_endpoints import _agent_on, client, project, reset_state, settle_renders, take, voiced  # noqa: F401
from tests.agent.conftest import reply, text as said

LINE = {"start": 0.0, "end": 2.3}
pytestmark = pytest.mark.landing         # the render after a short change holds the lock here, as in the app


class Gate:
    """Holds whatever runs first inside its edit until both answers are in."""

    def __init__(self) -> None:
        self.open = threading.Event()
        self.entered = threading.Event()

    def wait(self) -> None:
        self.entered.set()
        assert self.open.wait(30), "the gate was never opened"


@pytest.fixture()
def gate(monkeypatch):
    """Every kind of edit, held inside once it has the lock: a turn's agent, the
    fast path's take, a render (an Add's, a short change's, Render now's)."""
    import app.api.main as main
    from app.agent import fastpath
    from app.agent.loop import Agent
    g = Gate()
    real_run, real_voice, real_export, real_remove = Agent.run, fastpath.voice, main._export, main._remove_words

    def run(self, *a, **kw):
        g.wait()
        return real_run(self, *a, **kw)

    def voice(*a, **kw):
        g.wait()
        return real_voice(*a, **kw)

    def export(*a, **kw):
        g.wait()
        return real_export(*a, **kw)
    monkeypatch.setattr(Agent, "run", run)
    monkeypatch.setattr(fastpath, "voice", voice)
    def remove(*a, **kw):
        g.wait()
        return real_remove(*a, **kw)
    monkeypatch.setattr(main, "_export", export)
    monkeypatch.setattr(main, "_remove_words", remove)
    yield g
    g.open.set()


def _edits(main):
    """The edits, by name: (method, path, body). Each one changes the video."""
    return {
        "turn": ("POST", "/videos/p1/turns", {"text": "Make it 30% off"}),
        "chat": ("POST", "/videos/p1/turns", {"text": "Add a line at the end"}),
        "quick": ("POST", "/videos/p1/lines/quick", {**LINE, "text": "Get 30% off this weekend only.",
                                                     "before": "Get 20% off today only."}),
        "remove": ("POST", "/videos/p1/lines/remove", {"start": 0.4, "end": 1.3}),
        "render": ("POST", "/videos/p1/renders", {"mode": "final"}),
        "mix": ("PUT", "/videos/p1/settings", {"mix": {"bed_under_db": 14}}),
    }


def _ready(monkeypatch, main):
    """Voltage on (a scripted Claude with enough answers for either turn), Just do it, spending under the limit."""
    _agent_on(monkeypatch, main, [reply(said("On it.")) for _ in range(4)])
    TestClient(main.app).put("/videos/p1/settings", json={"autonomy": "draft"})


def _settle(main, gate):
    gate.open.set()
    deadline = time.time() + 60
    while time.time() < deadline and (main.locks.get("p1") is not None or any(not j.done for j in main.jobs.all())):
        time.sleep(0.05)
    settle_renders()
    assert main.locks.get("p1") is None


def _until(answers, refused: int, gate) -> None:
    """Wait for the refusals, and for the winner to be inside its edit (its own answer may wait on the gate)."""
    deadline = time.time() + 30
    while time.time() < deadline:
        n = sum(a is not None for a in answers)
        if n == len(answers) or (n >= refused and gate.entered.is_set()):
            return
        time.sleep(0.01)
    raise AssertionError(f"only {sum(a is not None for a in answers)} answers came")


def _one_ran_one_refused(answers):
    codes = sorted(r.status_code for r in answers)
    assert len([c for c in codes if c in (200, 201, 202)]) == 1, [(r.status_code, r.text[:200]) for r in answers]
    [refused] = [r for r in answers if r.status_code == 409]
    detail = refused.json()["detail"]
    assert detail["code"] == "video_busy" and detail["message"].endswith((". Queue this change, or Stop.", "or wait."))
    assert "—" not in detail["message"]
    return detail


PAIRS = [("turn", "chat"), ("turn", "remove"), ("quick", "turn"), ("remove", "remove"), ("render", "turn"),
         ("mix", "quick"), ("chat", "render")]


@pytest.mark.parametrize("first,second", PAIRS)
def test_two_tabs_fire_two_edits_at_the_same_moment_exactly_one_runs(project, gate, monkeypatch, first, second):
    """Two sessions (two clients, two tab ids), two threads let go together by a barrier."""
    import app.api.main as main
    _ready(monkeypatch, main)
    edits = _edits(main)
    tabs = [TestClient(main.app, headers={"X-Voltage-Tab": "tab-a"}), TestClient(main.app, headers={"X-Voltage-Tab": "tab-b"})]
    start = threading.Barrier(2)
    answers: list = [None, None]

    def fire(i: int, name: str) -> None:
        method, path, body = edits[name]
        start.wait()
        answers[i] = tabs[i].request(method, path, json=body)
    threads = [threading.Thread(target=fire, args=(i, name)) for i, name in enumerate((first, second))]
    for t in threads:
        t.start()
    # The one that won is held inside its edit while the other is answered.
    _until(answers, 1, gate)
    held = main.locks.get("p1")
    gate.open.set()
    for t in threads:
        t.join(30)
    detail = _one_ran_one_refused(answers)
    assert held is not None and detail["holder"].startswith(("req-", "turn:", "J"))   # what held it at that moment
    _settle(main, gate)


def test_ten_tabs_at_once_still_only_one_edit_runs(project, gate, monkeypatch):
    import app.api.main as main
    _ready(monkeypatch, main)
    edits = _edits(main)
    names = ["turn", "chat", "quick", "remove", "render", "mix", "turn", "remove", "quick", "chat"]
    start = threading.Barrier(len(names))
    answers: list = [None] * len(names)

    def fire(i: int, name: str) -> None:
        method, path, body = edits[name]
        tab = TestClient(main.app, headers={"X-Voltage-Tab": f"tab-{i}"})
        start.wait()
        answers[i] = tab.request(method, path, json=body)
    threads = [threading.Thread(target=fire, args=(i, n)) for i, n in enumerate(names)]
    for t in threads:
        t.start()
    _until(answers, len(names) - 1, gate)
    gate.open.set()
    for t in threads:
        t.join(30)
    ok = [a for a in answers if a.status_code in (200, 201, 202)]
    busy = [a for a in answers if a.status_code == 409]
    assert len(ok) == 1 and len(busy) == len(names) - 1, [(a.status_code, a.text[:120]) for a in answers]
    assert all(a.json()["detail"]["code"] == "video_busy" for a in busy)
    _settle(main, gate)


def test_two_edits_at_once_over_asyncio_one_runs_the_other_gets_409(project, gate, monkeypatch):
    """The same race through the ASGI app on one event loop: the sync routes run on its thread pool, for real."""
    import app.api.main as main
    _ready(monkeypatch, main)
    edits = _edits(main)

    async def both():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-Voltage-Tab": "tab-a"}) as a, \
                httpx.AsyncClient(transport=transport, base_url="http://test", headers={"X-Voltage-Tab": "tab-b"}) as b:
            m1, p1, b1 = edits["turn"]
            m2, p2, b2 = edits["quick"]
            return await asyncio.gather(a.request(m1, p1, json=b1), b.request(m2, p2, json=b2))
    answers = asyncio.run(both())
    _one_ran_one_refused(answers)
    _settle(main, gate)


def test_the_fast_path_holds_the_lock_until_its_take_is_a_proposal(client, project, gate, monkeypatch):
    import app.api.main as main
    _ready(monkeypatch, main)
    resp = client.post("/videos/p1/lines/quick", json={**LINE, "text": "Get 30% off this weekend only.",
                                                      "before": "Get 20% off today only."})
    assert resp.status_code == 202 and resp.json()["route"] == "fast"
    assert gate.entered.wait(10)
    held = main.locks.get("p1")
    assert held.holder == f"turn:{resp.json()['job_id']}" and held.action == "Voicing the line"
    assert client.post("/videos/p1/turns", json={"text": "and line 2"}).status_code == 409
    _settle(main, gate)


def test_render_now_holds_the_lock_until_the_render_is_in_the_video(client, project, gate):
    import app.api.main as main
    job = client.post("/videos/p1/renders", json={"mode": "final"}).json()
    assert gate.entered.wait(10)
    held = main.locks.get("p1")
    assert held.holder == job["job_id"] and held.action == "Updating your video"
    refused = client.post("/videos/p1/lines/remove", json={"start": 0.4, "end": 1.3})
    assert refused.status_code == 409 and refused.json()["detail"]["message"] == "Busy with updating your video. Queue this change, or Stop."
    _settle(main, gate)


def test_a_short_change_holds_the_lock_until_its_render_is_in_the_video(client, project, gate):
    """A change to the mix is made at once; the video stays Working until the render with it lands."""
    import app.api.main as main
    assert client.put("/videos/p1/settings", json={"mix": {"bed_under_db": 14}}).status_code == 200
    held = main.locks.get("p1")
    assert held is not None and held.action == "Changing the mix" and not held.holder.startswith("req-")
    assert main.activity.get(held.holder).kind == "render_preview"
    assert client.post("/videos/p1/turns", json={"text": "Make it 30% off"}).status_code == 409
    # The editor's own fetch of the render finds the same job (no second render, no 409).
    out = client.post("/videos/p1/export", json={"with_proposals": False})
    assert out.status_code == 202 and out.json()["render_job"]["job_id"] == held.holder
    _settle(main, gate)
    assert client.get("/videos/p1/renders").json()["final"]["render"] is not None


def test_an_export_that_must_render_holds_the_lock_and_one_on_a_busy_video_is_refused(client, project, gate):
    import app.api.main as main
    out = client.post("/videos/p1/export", json={"purpose": "export"})
    assert out.status_code == 202
    held = main.locks.get("p1")
    assert held.holder == out.json()["render_job"]["job_id"] and held.action == "Making your file"
    assert client.post("/videos/p1/lines/remove", json={"start": 0.4, "end": 1.3}).status_code == 409
    _settle(main, gate)
    # A file already made for the edits as they are is handed over even while the video is busy (it is that file).
    main.locks.take("p1", "J999", "Adding 'Fresh every morning'")
    assert client.post("/videos/p1/export", json={"purpose": "export"}).status_code == 200
    main.locks.release("p1", "J999")
    # One that has to render on a busy video says so and how to go on (it cannot wait in Up next).
    assert client.put("/videos/p1/settings", json={"mix": {"bed_under_db": 14}}).status_code == 200
    _settle(main, gate)
    repo_settings = main.repo.settings("p1")
    main.repo.set_settings("p1", renders={})        # its render is not made for the export's edit set any more
    assert repo_settings.get("renders")
    main.locks.take("p1", "J999", "Adding 'Fresh every morning'")
    busy = client.post("/videos/p1/export", json={"purpose": "export"})
    assert busy.status_code == 409
    assert busy.json()["detail"]["message"] == "Busy with adding 'Fresh every morning'. Export again when it is Ready."
    main.locks.release("p1", "J999")


def test_a_batch_export_waits_for_the_video_and_holds_it_while_it_renders(project, monkeypatch):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding 'Fresh every morning'")
    seen, real = [], main._export

    def export(*a, **kw):
        seen.append(main.locks.get("p1"))
        return real(*a, **kw)
    monkeypatch.setattr(main, "_export", export)
    done = threading.Event()

    def deliver():
        with main._waiting_lock("p1", "Making your file", wait_s=20):
            main._export(main.repo.get("p1"), purpose="export")
        done.set()
    t = threading.Thread(target=deliver)
    t.start()
    time.sleep(0.6)
    assert not done.is_set() and seen == []                  # it waits while the Add holds the video
    main.locks.release("p1", "J999")
    t.join(60)
    assert done.is_set() and seen[0].action == "Making your file"
    assert main.locks.get("p1") is None
    # Busy past its wait: the plain sentence, from the classifier, never a 500.
    main.locks.take("p1", "J999", "Adding 'Fresh every morning'")
    from app import failures
    from app.jobs.locks import VideoBusy
    with pytest.raises(VideoBusy) as busy:
        with main._waiting_lock("p1", "Making your file", wait_s=0.2):
            pass
    assert failures.say(busy.value, where="export") == "Busy with adding 'Fresh every morning'. Queue this change, or Stop."
    main.locks.release("p1", "J999")


def test_the_classifier_reads_a_busy_409_as_the_person_s_timing_not_our_failure():
    from fastapi import HTTPException
    from app import failures
    busy = HTTPException(status_code=409, detail={"code": "video_busy", "message": "Busy with undoing. Queue this change, or Stop."})
    found = failures.classify(busy)
    assert found.kind == failures.USER_INPUT and found.text == "Busy with undoing. Queue this change, or Stop."


def test_a_lost_race_on_the_lock_row_is_busy_never_an_error(project, monkeypatch):
    """Two servers (Postgres, several workers) both read no row; the primary key lets one in."""
    import sqlite3
    import app.api.main as main
    from app.jobs.locks import VideoBusy
    main.locks.take("p1", "J1", "Voltage is planning")

    def lost(*a, **kw):
        raise sqlite3.IntegrityError("UNIQUE constraint failed: video_locks.video_id")
    monkeypatch.setattr(main.locks, "take_in", lost)
    with pytest.raises(VideoBusy) as busy:
        main.locks.take("p1", "J2", "Removing a line")
    assert busy.value.lock.holder == "J1"
    main.locks.release("p1", "J1")
