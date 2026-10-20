"""A2 through the API: a seeded project with known conflicts returns exactly
those issues as one Activity job (kind "check"); an ignored issue stays
ignored until the text it was found in changes; Rules only spends nothing;
the text pass is charged to the project and shown before it runs; a brief
change runs the free checks again; Fix in this video starts a normal turn."""
import time
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, flags, jobs, ledger, repo
from app.domain.models import Statement, Transcript, Word
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    import app.api.main as main
    repo.reset()
    jobs.reset()
    monkeypatch.setattr(main, "settings", replace(main.settings, anthropic_api_key=None))
    monkeypatch.setattr(main, "_check_reader", None)
    yield
    flags.clear("projects.consistency", "local")


@pytest.fixture()
def client():
    return TestClient(app)


class FakeReader:
    """The Claude text pass, scripted: what it returns and what it would have cost."""
    def __init__(self, issues):
        self.issues, self.calls = issues, []

    def read(self, text, meter=None):
        self.calls.append(text)
        if meter is not None:
            meter("claude-haiku-4-5", 1200, 150)
        return self.issues


def says(video_id, *lines):
    words, statements, t = [], [], 0.0
    for line in lines:
        start = t
        for w in line.split():
            words.append(Word(w, t, t + 0.3))
            t += 0.35
        statements.append(Statement(line, start, t))
        t += 0.5
    repo.update_transcript(video_id, Transcript(words=tuple(words), statements=tuple(statements)))


def seeded(client, sample_video):
    """Three videos: p2 says 30% where the others say 20%, says a banned word
    and lacks the required line; p1 is rendered loud, p2 quiet, p3 not at all."""
    client.post("/projects", json={"name": "Diwali", "brief": "Get 20% off."})
    client.post("/projects/f1/rules", json={"kind": "banned", "data": {"word": "cheap"}})
    client.post("/projects/f1/rules", json={"kind": "required_line", "data": {"text": "T&C apply"}})
    for name in ("first.mp4", "second.mp4", "third.mp4"):
        upload_into(client, sample_video, "f1", name)
    says("p1", "Get 20% off the Diwali Dhamaka sale.", "T&C apply.")
    says("p2", "Get 30% off the Diwali Bonanza sale.", "It is cheap.")
    says("p3", "Only now, 20 percent off.", "T&C apply.")
    repo.set_settings("p1", mix_report={"loudness_lufs": -14.0})
    repo.set_settings("p2", mix_report={"loudness_lufs": -18.0})


def run(client, mode="rules", timeout=30.0):
    resp = client.post("/projects/f1/check", json={"mode": mode})
    assert resp.status_code == 202, resp.text
    deadline = time.time() + timeout
    while time.time() < deadline:
        page = client.get("/projects/f1/check").json()
        if page["check"]["status"] != "running":
            return page
        time.sleep(0.05)
    raise AssertionError("the check never finished")


def live(page):
    return [i for i in page["issues"] if not i["ignored"]]


def test_a_seeded_project_returns_exactly_its_issues_and_rules_only_spends_nothing(client, sample_video):
    seeded(client, sample_video)
    before = ledger.spent_usd_by_folder("f1")
    page = run(client)
    check = page["check"]
    assert check["status"] == "done" and check["mode"] == "rules" and check["cost_usd"] == 0
    assert check["job"]["kind"] == "check" and check["job"]["status"] == "done" and check["job"]["step_label"] == "4 issues found"
    issues = live(page)
    assert [i["kind"] for i in issues] == ["fact", "banned", "required_line", "loudness"]
    fact = issues[0]
    assert fact["message"] == "The videos give different percentages: 20% in first.mp4 and third.mp4; 30% in second.mp4."
    assert {p["video_id"] for p in fact["places"]} == {"p1", "p2", "p3"}
    assert [p["video_id"] for p in issues[1]["places"]] == ["p2"] and issues[1]["places"][0]["t"] > 0
    assert [p["video_id"] for p in issues[2]["places"]] == ["p2"]
    assert issues[3]["message"].startswith("first.mp4 is 4.0 LU louder than second.mp4")
    assert check["notes"] == ["Loudness not checked for third.mp4: no render measured yet."]
    assert ledger.spent_usd_by_folder("f1") == before                  # rules only: nothing spent
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert "check.started" in verbs and "check.finished" in verbs


def test_an_ignored_issue_stays_ignored_until_its_text_changes(client, sample_video):
    seeded(client, sample_video)
    page = run(client)
    banned = next(i for i in page["issues"] if i["kind"] == "banned")
    after = client.post(f"/projects/f1/check/issues/{banned['issue_id']}/ignore").json()
    assert next(i for i in after["issues"] if i["issue_id"] == banned["issue_id"])["ignored"] is True
    again = run(client)
    assert [i["kind"] for i in live(again)] == ["fact", "required_line", "loudness"]
    assert [i["kind"] for i in again["issues"] if i["ignored"]] == ["banned"]
    assert again["check"]["job"]["step_label"] == "3 issues found"
    says("p2", "Get 30% off the Diwali Bonanza sale.", "It is so cheap.")    # the text it was found in changed
    changed = run(client)
    assert "banned" in [i["kind"] for i in live(changed)]
    assert client.post("/projects/f1/check/issues/9999/ignore").status_code == 404


def test_the_text_pass_shows_its_price_first_and_is_charged_to_the_project(client, sample_video, monkeypatch):
    import app.api.main as main
    seeded(client, sample_video)
    page = client.get("/projects/f1/check").json()
    assert page["check"] is None and page["issues"] == [] and page["videos"] == 3
    assert page["estimate"]["available"] is False and "only the rule checks" in page["estimate"]["why"]
    assert client.post("/projects/f1/check", json={"mode": "full"}).status_code == 409   # no key: Rules only
    reader = FakeReader([{"message": "One video calls the sale Diwali Dhamaka, another Diwali Bonanza.",
                          "places": [{"video_id": "p1", "quote": "Diwali Dhamaka sale"}, {"video_id": "p2", "quote": "Diwali Bonanza sale"}]}])
    monkeypatch.setattr(main, "_check_reader", reader)
    est = client.get("/projects/f1/check").json()["estimate"]
    assert est["available"] and est["label"] == "about $0.01" and est["model"] == "claude-haiku-4-5"
    page = run(client, "full")
    assert len(reader.calls) == 1 and "Video p2" in reader.calls[0]
    assert [i["kind"] for i in live(page)][-1] == "offer"
    spent = page["check"]["cost_usd"]
    assert spent == pytest.approx((1200 * 1.0 + 150 * 5.0) / 1_000_000, abs=1e-6)
    lines = ledger.project_level_lines("f1")
    assert [(ln.vendor, ln.what) for ln in lines] == [("anthropic", "project check")]
    assert page["check"]["job"]["cost_usd"] == round(spent, 4)
    # A project at its ceiling refuses the paid pass and still runs Rules only.
    client.patch("/projects/f1", json={"ceiling_usd": 0.001})
    refused = client.post("/projects/f1/check", json={"mode": "full"})
    assert refused.status_code == 409 and "Rules only" not in refused.text and "rule checks only" in refused.json()["detail"]
    assert run(client, "rules")["check"]["cost_usd"] == 0 and len(reader.calls) == 1


def test_a_brief_change_runs_the_free_checks_again(client, sample_video, monkeypatch):
    import app.api.main as main
    seeded(client, sample_video)
    reader = FakeReader([])
    monkeypatch.setattr(main, "_check_reader", reader)
    client.patch("/projects/f1", json={"brief": "Get 30% off."})
    page = client.get("/projects/f1/check").json()
    assert page["check"]["trigger"] == "brief" and page["check"]["mode"] == "rules" and page["check"]["status"] == "done"
    assert reader.calls == [] and page["check"]["cost_usd"] == 0
    assert main.project_check_warnings("f1")[0]["kind"] == "fact"         # what B3 reads before a batch export


def test_fix_in_this_video_starts_a_normal_turn_with_the_issue_as_its_goal(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    seeded(client, sample_video)
    page = run(client)
    fact = next(i for i in page["issues"] if i["kind"] == "fact")
    assert client.post(f"/projects/f1/check/issues/{fact['issue_id']}/fix", json={"video_id": "p2"}).status_code == 409   # no Voltage
    scripted = _agent_on(monkeypatch, main, [reply(text("Changed it to 20% to match the others."))])
    resp = client.post(f"/projects/f1/check/issues/{fact['issue_id']}/fix", json={"video_id": "p2"})
    assert resp.status_code == 202, resp.text
    assert resp.json()["video_id"] == "p2" and resp.json()["t"] == 0.0
    deadline = time.time() + 30
    while not jobs.get(resp.json()["job_id"]).done and time.time() < deadline:
        time.sleep(0.05)
    told = str(scripted.calls[0]["messages"])
    assert "Fix this from the project check: The videos give different percentages" in told
    assert client.post(f"/projects/f1/check/issues/{fact['issue_id']}/fix", json={"video_id": "p9"}).status_code == 422


def test_the_routes_are_behind_the_consistency_flag(client):
    client.post("/projects", json={"name": "Spring", "brief": "Bright."})
    assert client.get("/projects/f1/check").status_code == 200
    flags.set("projects.consistency", "local", False)
    assert client.get("/projects/f1/check").status_code == 404
    assert client.post("/projects/f1/check", json={"mode": "rules"}).status_code == 404
    assert client.post("/projects/f1/check/issues/1/ignore").status_code == 404


def test_fix_in_all_runs_each_named_video_in_turn(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    seeded(client, sample_video)
    page = run(client)
    required = next(i for i in page["issues"] if i["kind"] == "required_line")
    scripted = _agent_on(monkeypatch, main, [reply(text("Nothing here can carry it; it is right as it is."))])
    resp = client.post(f"/projects/f1/check/issues/{required['issue_id']}/fix-all")
    assert resp.status_code == 202, resp.text
    assert [v["video_id"] for v in resp.json()["fix_run"]["videos"]] == ["p2"]
    deadline = time.time() + 30
    while time.time() < deadline:
        fix = client.get("/projects/f1/check").json()["fix_run"]
        if fix["status"] == "finished" and fix.get("finished_at"):
            break
        time.sleep(0.05)
    assert fix["videos"][0]["status"] == "done" and fix["videos"][0]["outcome"] == "current"
    assert "required line" in str(scripted.calls[0]["messages"])
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert "check.fix_all_started" in verbs and "check.fix_all_finished" in verbs
