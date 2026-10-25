"""One edit at a time per video (2026-10-25), Part 1: the video lock at the API.

Every route that changes a video takes its lock, so while anything changes it
(a Voltage turn, also while it waits for the go; an Add until its render
lands) the others answer 409 `video_busy` with what holds it. The first test
walks the router: a new write route fails it until it is classified."""
import threading

import pytest
from fastapi.routing import APIRoute

from tests.api.test_endpoints import _agent_on, add, client, project, reset_state, send, take, voiced  # noqa: F401
from tests.api.test_jobs import wait_job
from tests.agent.conftest import reply, text as said

WRITES = {"POST", "PUT", "PATCH", "DELETE"}

# Routes that change a video but take its lock inside, for a reason the door
# cannot know (the body says which video, or whether the video's sound changes).
INSIDE = {
    "update_settings": "a mix change takes the lock; autonomy, the turn cap and effort are Voltage's instructions",
    "add_all_batch": "many videos: each video's Add takes that video's lock",
    "fix_check_issue": "the body names the video; its turn takes that video's lock",
    "fix_check_issue_everywhere": "one turn per video, each takes its own video's lock",
    "go_batch": "a batch's children are turns, each takes its own video's lock",
    "answer_batch_video": "an ordinary turn in that video, which takes its lock",
    "start_brief_update": "Bring up to date: one turn per video, each takes its own video's lock",
    "make_languages": "new language versions, each made by a turn that takes its own lock",
}

# Write routes on a video that leave its edit set as it is, so they stay open while it works.
OPEN = {
    "export_project": "export of the last finished render; it says which version it is",
    "start_render": "a render reads the edit set and never changes it",
    "stop_jobs": "Stop",
    "grant_consent": "consent", "start_liveness": "consent", "check_liveness": "consent", "withdraw_consent": "consent",
    "add_member_comment": "comments", "reply_review_comment": "comments", "resolve_review_comment": "comments",
    "create_review_link": "sharing for review", "revoke_review_link": "sharing for review",
    "put_feedback": "thumbs on a take or a reply", "chip_event": "what happened to a chip (analytics)",
    "give_decision_reason": "a note on why a line was discarded",
    "move_stage": "the review stage (Draft, Approved), not the edit set",
    "move_video": "which project folder the video is filed in",
    "create_variant": "a new video copied from this one; this one is only read",
    "read_project": "the first read, once at open: what Voltage sees, not the edit set",
    "confirm_sight": "the place Voltage guessed, confirmed: what it knows, not the edit set",
    "set_style": "the video's style line: what Voltage knows, not the edit set",
    "correct_understanding": "a correction to what Voltage understood, not the edit set",
}

# Project folder routes: they change the folder's own record (its brief, rules, files, shares), no one video's edit set.
FOLDER = {
    "accept_learned", "accept_suggestion", "add_export_preset", "add_folder_file", "add_project_rule", "add_word_audio",
    "archive_project", "cancel_batch", "change_export_preset", "change_project_rule", "create_share", "delete_folder",
    "delete_folder_file", "delete_project_rule", "delete_word_audio", "dismiss_learned", "dismiss_suggestion",
    "ignore_check_issue", "plan_batch", "remove_export_preset", "remove_learned", "revoke_share", "save_template",
    "share_batch_export", "share_voice", "start_batch_export", "start_project_check", "unarchive_project",
    "unshare_voice", "update_folder",
}


def _walk(routes, prefix=""):
    for r in routes:
        if isinstance(r, APIRoute):
            yield prefix + r.path, r
        elif hasattr(r, "original_router"):          # an included router (app/*_api.py)
            yield from _walk(r.original_router.routes, prefix + (r.include_context.prefix or ""))


def _lock_of(route) -> str | None:
    return next((d.call.video_lock for d in route.dependant.dependencies if getattr(d.call, "video_lock", None)), None)


def _write_routes():
    import app.api.main as main
    return [(path, route, sorted(route.methods & WRITES)) for path, route in _walk(main.app.routes) if route.methods & WRITES]


def test_every_write_route_on_a_video_takes_its_lock_or_says_why_not():
    unclassified, twice = [], []
    for path, route, _ in _write_routes():
        name = route.endpoint.__name__
        on_a_video = "{project_id}" in path or "{video_id}" in path
        classes = [bool(_lock_of(route)), name in INSIDE, name in OPEN, name in FOLDER]
        if not on_a_video:
            continue              # auth, billing, admin, the account, new videos: no one video's edit set
        if sum(classes) == 0:
            unclassified.append(f"{path} ({name})")
        elif sum(classes) > 1:
            twice.append(f"{path} ({name})")
    assert unclassified == [], "classify these write routes: lock them with locked(...) or add them here with why"
    assert twice == []


def _fill(path: str) -> str:
    out = path
    for key in ("{video_id}", "{project_id}"):
        if key in out:
            out = out.replace(key, "p1" if key == "{video_id}" or "{video_id}" not in path else "x")
    import re
    return re.sub(r"\{[^}]+\}", "x", out)


def test_while_the_video_is_locked_every_locking_route_answers_video_busy(client, project):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding 'Fresh every morning'", started_by="google:ann", started_by_name="Ann")
    checked = 0
    for path, route, methods in _write_routes():
        if not _lock_of(route):
            continue
        for method in methods:
            resp = client.request(method, _fill(path), json={})
            assert resp.status_code == 409, f"{method} {path}: {resp.status_code} {resp.text[:200]}"
            body = resp.json()["detail"]
            assert body["code"] == "video_busy" and body["holder"] == "J999", path
            assert body["action"] == "Adding 'Fresh every morning'" and body["started_by"] == "Ann" and body["queue"] == []
            checked += 1
    assert checked >= 30                                      # both the /videos routes and their old /projects names
    assert main.locks.get("p1").holder == "J999"              # a refused request never takes or drops it


def test_a_mix_change_waits_for_the_lock_and_the_autonomy_does_not(client, project):
    import app.api.main as main
    main.locks.take("p1", "J999", "Adding")
    assert client.put("/videos/p1/settings", json={"mix": {"bed_under_db": 14}}).status_code == 409
    assert client.put("/videos/p1/settings", json={"autonomy": "draft"}).status_code == 200


def test_a_run_turn_on_a_busy_video_is_refused_saying_why(client, project, monkeypatch):
    import app.api.main as main
    from fastapi import HTTPException
    main.locks.take("p1", "J999", "Adding")
    _agent_on(monkeypatch, main, [reply(said("Nothing."))])
    with pytest.raises(HTTPException) as refused:
        main._start_turn("p1", main.repo.get("p1"), "Fix this from the project check", "local")
    assert refused.value.status_code == 409 and refused.value.detail["code"] == "video_busy"


def _held_render(monkeypatch):
    import app.api.main as main
    gate = threading.Event()
    real = main._render_now

    def held(*a, **kw):
        assert gate.wait(30), "the render was never let go"
        return real(*a, **kw)
    monkeypatch.setattr(main, "_render_now", held)
    return gate


def test_two_tabs_the_second_sees_the_lock_and_its_writes_get_409(client, project, monkeypatch):
    done = voiced(client, monkeypatch, text="Fresh every morning.")
    plan_id = done["plan"]["plan_id"]
    gate = _held_render(monkeypatch)
    first = client.post(f"/videos/p1/plans/{plan_id}/approve", json={}, headers={"X-Voltage-Tab": "tab-a"}).json()

    seen = client.get("/videos/p1/lock", headers={"X-Voltage-Tab": "tab-b"}).json()["lock"]
    assert seen["holder"] == first["render_job"]["job_id"] and seen["action"] == "Adding 'Fresh every morning'"
    assert seen["tab"] == "tab-a" and seen["started_by_name"] == "You" and seen["waiting"] is False
    assert client.get("/videos/p1/jobs?active=1").json()["lock"]["holder"] == seen["holder"]   # a reload restores it

    refused = client.post("/videos/p1/edits/e1/revert", headers={"X-Voltage-Tab": "tab-b"})
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert {"code", "holder", "action", "started_by", "queue", "message"} <= set(detail)
    assert detail["message"] == "Busy with adding 'Fresh every morning'. Queue this change, or Stop."

    gate.set()
    wait_job(client, first["render_job"]["job_id"])
    assert client.get("/videos/p1/lock").json()["lock"] is None     # it landed: Ready
    assert client.post("/videos/p1/edits/e1/revert", headers={"X-Voltage-Tab": "tab-b"}).status_code == 200


def test_a_short_action_holds_the_lock_while_it_runs_and_lets_go_after(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch)
    seen = []
    real = main._log_decision

    def spy(*a, **kw):
        seen.append(main.locks.get("p1"))
        return real(*a, **kw)
    monkeypatch.setattr(main, "_log_decision", spy)
    assert client.post(f"/videos/p1/plans/{done['plan']['plan_id']}/items/i1/dismiss").status_code == 200
    assert seen[0].action == "Discarding" and seen[0].holder.startswith("req-")
    assert main.locks.get("p1") is None


def test_a_turn_holds_the_lock_while_it_runs_and_while_it_waits_for_the_go(client, project, monkeypatch):
    import app.api.main as main
    seen = []
    real = main._close_turn

    def spy(*a, **kw):
        seen.append(main.locks.get("p1"))
        return real(*a, **kw)
    monkeypatch.setattr(main, "_close_turn", spy)
    _agent_on(monkeypatch, main, [reply(take("c"), stop="tool_use")])      # a paid step under Check with me: a go
    client.put("/videos/p1/settings", json={"autonomy": "ask"})
    out = send(client, "make it 30% off")
    assert seen[0].holder.startswith("turn:") and seen[0].action == "Voltage is planning"
    assert out["question"]["gate"]
    waiting = client.get("/videos/p1/lock").json()["lock"]
    assert waiting["waiting"] is True and waiting["action"] == "Waiting for your go"
    assert client.post("/videos/p1/lines/remove", json={"start": 0.4, "end": 1.3}).status_code == 409

    _agent_on(monkeypatch, main, [reply(said("All right, not now."))])
    send(client, "Not yet")                                    # the answer takes the lock over, and lands
    assert client.get("/videos/p1/lock").json()["lock"] is None


def test_an_add_holds_the_lock_until_its_render_lands(client, project, monkeypatch):
    import app.api.main as main
    done = voiced(client, monkeypatch)
    out = add(client, done["plan"]["plan_id"])
    assert out["export"] is not None and main.locks.get("p1") is None
