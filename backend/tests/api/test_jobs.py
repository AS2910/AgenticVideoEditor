"""One processing model (2026-10-20): every line voiced and every render is a
Job the editor can show, restore after a reload, stop and retry."""
import time

from tests.api.test_endpoints import _agent_on, client, project, reset_state, send, take, voiced  # noqa: F401
from tests.agent.conftest import reply, text as said, use


def active(client):
    return client.get("/videos/p1/jobs?active=1").json()


def wait_job(client, job_id, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        found = next((j for j in client.get("/videos/p1/jobs").json()["jobs"] if j["job_id"] == job_id), None)
        if found and found["status"] in ("done", "failed", "cancelled"):
            return found
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} never finished")


def test_a_voiced_turn_leaves_a_done_line_job_a_preview_render_and_the_turn_view(client, project, monkeypatch):
    result = voiced(client, monkeypatch)
    assert result["render"]["version"] == 1 and result["render"]["mode"] == "proposals"
    assert result["turn_usd"] >= 0
    state = active(client)                                  # what a reload right after reads
    assert state["turn"]["status"] == "done" and state["turn"]["lines_voiced"] == 1
    assert state["turn"]["render"] == result["render"]
    line = next(j for j in state["jobs"] if j["kind"] == "voice_line")
    assert line["status"] == "done" and line["line_ids"] == ["i1"] and line["turn_id"] == state["turn"]["turn_id"]
    assert line["step_label"] == "Ready to hear" and line["eta_s"] is None and line["detail"]["text"]
    render = next(j for j in state["jobs"] if j["kind"] == "render_preview")
    assert render["status"] == "done" and render["step_label"] == "v1 ready" and render["turn_id"] == line["turn_id"]
    assert render["detail"]["includes"]["item_ids"] == ["i1"]
    # Newest first.
    assert [j["job_id"] for j in state["jobs"]] == sorted((j["job_id"] for j in state["jobs"]), key=lambda i: int(i[1:]), reverse=True)


def test_the_latest_render_says_its_version_what_it_carries_and_whether_it_is_stale(client, project, monkeypatch):
    voiced(client, monkeypatch)
    latest = client.get("/videos/p1/renders/latest?mode=proposals").json()
    assert latest["latest"]["version"] == 1 and latest["latest"]["includes"]["item_ids"] == ["i1"]
    assert latest["in_progress"] is None and latest["stale"] is False
    # The same edit set again is the same version; nothing new is rendered.
    again = client.post("/videos/p1/export", json={"with_proposals": True}).json()
    assert again["version"] == 1 and again["cached"] is True and again["includes"]["item_ids"] == ["i1"]
    # Nothing is kept yet: the final edit set is empty and was never rendered, and nothing says it is stale.
    final = client.get("/videos/p1/renders/latest?mode=final").json()
    assert final["latest"] is None and final["stale"] is False


def test_a_version_number_is_new_only_for_a_new_edit_set(client, project):
    import app.api.main as main
    assert main._version_for("p1", "aaa") == 1
    assert main._version_for("p1", "bbb") == 2
    assert main._version_for("p1", "aaa") == 1
    assert main._version_for("p1", "ccc") == 3


def test_go_queues_every_planned_line_at_once_and_each_is_claimed_when_voiced(client, project, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "ask"})
    plan_call = use("plan_lines", "pl", voice_id="", speed=1, commentary=False,
                    lines=[{"start": 0.0, "end": 1.1, "text": "Hi."}, {"start": 1.2, "end": 2.3, "text": "Bye."}])
    _agent_on(monkeypatch, main, [reply(plan_call, stop="tool_use"),
                                  reply(take("t1", text="Hi.", line=None, start=0.0, end=1.1), stop="tool_use"),
                                  reply(said("Voice both?"))])
    first = send(client, "add two lines")
    assert [i["status"] for i in first["plan"]["items"]] == ["planned", "planned"]
    assert first["question"]["gate"]

    seen = []
    real = main._generate

    def watching(*a, **kw):
        seen.append(sorted((j.line_ids[0], j.status) for j in main.activity.list("p1", active=True) if j.kind == "voice_line"))
        return real(*a, **kw)
    monkeypatch.setattr(main, "_generate", watching)
    _agent_on(monkeypatch, main, [reply(take("t2", text="Hi.", line=None, start=0.0, end=1.1),
                                        take("t3", text="Bye.", line=None, start=1.2, end=2.3), stop="tool_use"),
                                  reply(said("Both voiced."))])
    send(client, "go")
    # When the first take started, both lines were already queued (and the first one running).
    assert seen[0] == [("i1", "running"), ("i2", "queued")]
    lines = [j for j in active(client)["jobs"] if j["kind"] == "voice_line"]
    assert sorted((j["line_ids"][0], j["status"]) for j in lines) == [("i1", "done"), ("i2", "done")]
    assert len({j["turn_id"] for j in lines}) == 1


def test_a_failed_vendor_call_fails_the_line_with_its_reason_and_retry_voices_it(client, project, monkeypatch):
    import app.api.main as main
    from app.adapters.base import VendorError
    real = main._generate

    def down(*a, **kw):
        raise VendorError("The voice service did not answer.")
    monkeypatch.setattr(main, "_generate", down)
    voiced(client, monkeypatch)
    failed = next(j for j in client.get("/videos/p1/jobs").json()["jobs"] if j["kind"] == "voice_line")
    assert failed["status"] == "failed" and failed["error_code"] == "vendor_failed"
    assert failed["error_text"] == "The voice service did not answer." and failed["retryable"]
    assert client.post("/videos/p1/jobs/J999/retry").status_code == 404

    monkeypatch.setattr(main, "_generate", real)
    fresh = client.post(f"/videos/p1/jobs/{failed['job_id']}/retry")
    assert fresh.status_code == 202, fresh.text
    body = fresh.json()
    assert body["detail"]["manual"] is True and body["line_ids"] == failed["line_ids"]
    done = wait_job(client, body["job_id"])
    assert done["status"] == "done" and done["step_label"] == "Ready to hear", done
    item = client.get("/videos/p1").json()["plan"]["items"][0]
    assert item["status"] == "ready" and item["candidate"]
    # A job that did not fail cannot be retried.
    assert client.post(f"/videos/p1/jobs/{body['job_id']}/retry").status_code == 409


def test_stop_cancels_the_queued_jobs_and_leaves_running_ones(client, project):
    import app.api.main as main
    queued = main.activity.create("p1", "voice_line", line_ids=["i1"])
    running = main.activity.create("p1", "voice_line", line_ids=["i2"])
    main.activity.start(running.job_id)
    out = client.post("/videos/p1/jobs/stop").json()
    assert out == {"cancelled": 1}
    assert main.activity.get(queued.job_id).status == "cancelled"
    assert main.activity.get(running.job_id).status == "running"


def test_the_events_stream_opens_with_the_state_as_it_is_now(client, project):
    import json
    import app.api.main as main
    a = main.activity.create("p1", "voice_line", line_ids=["i1"])
    b = main.activity.create("p1", "render_preview")
    main.activity.start(b.job_id, "Rendering preview v1")
    with client.stream("GET", "/videos/p1/events?limit=2") as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        body = "".join(resp.iter_text())
    blocks = [blk for blk in body.split("\n\n") if blk.strip()]
    assert [blk.splitlines()[0] for blk in blocks] == ["event: job.updated", "event: job.updated"]
    sent = [json.loads(blk.splitlines()[1].removeprefix("data: ")) for blk in blocks]
    assert [s["job_id"] for s in sent] == [a.job_id, b.job_id]                    # oldest first, as they happened
    assert sent[1]["step_label"] == "Rendering preview v1" and sent[0]["eta_s"] is None   # no history yet: no time shown


def test_a_render_in_the_background_is_a_job_from_the_start(client, project, monkeypatch):
    voiced(client, monkeypatch)
    started = client.post("/videos/p1/renders", json={"mode": "proposals"})
    assert started.status_code == 202
    job = started.json()
    assert job["kind"] == "render_preview" and job["status"] in ("queued", "running")
    done = wait_job(client, job["job_id"])
    assert done["status"] == "done" and done["detail"]["version"] == 1        # same edit set: same version


def test_stop_mid_turn_lets_the_running_line_finish_and_runs_nothing_after_it(client, project, monkeypatch):
    import app.api.main as main
    real = main._generate
    calls = []

    def first_then_stop(*a, **kw):
        calls.append(a[4])
        if len(calls) == 1:
            assert client.post("/videos/p1/jobs/stop").status_code == 200
            assert main._turn_view("p1")["status"] == "stopping"
        return real(*a, **kw)
    monkeypatch.setattr(main, "_generate", first_then_stop)
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(take("t1", text="Hi.", line=None, start=0.0, end=1.1),
                                        take("t2", text="Bye.", line=None, start=1.2, end=2.3), stop="tool_use"),
                                  reply(said("never reached"))])
    result = send(client, "add two lines")
    assert calls == ["Hi."]
    assert result["reply"] == "Stopped. 1 line voiced."
    turn = active(client)["turn"]
    assert turn["status"] == "done" and turn["lines_voiced"] == 1


def test_a_clone_and_a_mix_change_are_jobs_too(client, project):
    import app.api.main as main
    track = main.CloneTrack("p1", "Priya")
    assert main.activity.get(track.job_id).step_label == "Cloning Priya's voice"
    track.done()
    cloned = main.activity.get(track.job_id)
    assert cloned.kind == "clone" and cloned.status == "done" and cloned.step_label == "Priya's voice is ready"
    failed = main.CloneTrack("p1", "the speaker")
    failed.fail("Stock voice: could not clone the speaker's voice.")
    assert main.activity.get(failed.job_id).error_code == "vendor_failed"
    mix = main.activity.instant("p1", "mix", "Mix changed")
    assert mix.status == "done" and mix.started_at and mix.finished_at


def test_the_export_page_render_is_an_export_job(client, project):
    out = client.post("/videos/p1/export", json={"purpose": "export"}).json()
    assert out["version"] == 1 and out["render_id"] == "r1"
    job = next(j for j in client.get("/videos/p1/jobs").json()["jobs"] if j["kind"] == "export")
    assert job["status"] == "done" and job["step_label"] == "v1 ready" and job["detail"]["render_id"] == "r1"
