"""D2 through the API: decisions on proposals are logged (added, rejected
with a reason, edited before adding with the difference); the pattern pass
runs at the 10th and 20th decision in a project and not in between, with
its cost in Usage under the project; a suggestion never applies without
Accept; removing a learned item takes it out of the next turn's opening
view; no Claude key skips the pass silently; the flag off hides it."""
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, database, flags, jobs, ledger, repo
from app.domain.plan import PlanItem
from app.domain.models import Selection
from app.media import ffmpeg
from app.store import briefs, learned, rules
from tests.api.test_endpoints import _agent_on, await_job, voiced
from tests.api.test_folders import upload_into

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state(monkeypatch):
    repo.reset()
    jobs.reset()
    monkeypatch.setattr(main, "LEARN_IN_BACKGROUND", False)
    yield
    flags.clear("projects.reuse", "local")


@pytest.fixture()
def client():
    return TestClient(app)


class FakeReader:
    """The pass, mocked: records what it read, charges a little through the meter, suggests."""
    def __init__(self, answer=None):
        self.calls: list[str] = []
        self.answer = answer if answer is not None else {"kind": "rule", "text": "Keep lines under eight words.",
                                                         "why": "You shortened 4 of the last 10 lines before adding them."}

    def suggest(self, text, meter=None):
        self.calls.append(text)
        if meter:
            meter("claude-haiku-4-5", 1200, 80)
        return self.answer


@pytest.fixture()
def in_project(client, sample_video):
    client.post("/projects", json={"name": "Diwali", "brief": "Warm and bright."})
    assert upload_into(client, sample_video, "f1").status_code == 200
    return "p1"


def item(n: int, text: str = "Get 30% off today.", first: str | None = None) -> PlanItem:
    history = ({"attempt": 1, "outcome": "ready", "text": first if first is not None else text},)
    return PlanItem(item_id=f"i{n}", selection=Selection(0.0, 1.0), old_text="Get it", new_text=text,
                    status="ready", attempt=1, history=history)


def test_adding_and_discarding_proposals_are_logged_with_a_reason(client, in_project, monkeypatch):
    plan = voiced(client, monkeypatch)["plan"]
    assert client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i1"]}).status_code == 200
    plan = voiced(client, monkeypatch, text="Thirty percent off, today.")["plan"]
    gone = client.post(f"/videos/p1/plans/{plan['plan_id']}/items/i1/dismiss", json={"reason": "Too long"})
    assert gone.status_code == 200, gone.text
    added, rejected = learned.decisions(database, "f1")[::-1]
    assert (added["decision"], added["proposed_text"], added["final_text"]) == ("added", "Get 30% off today only.", "Get 30% off today only.")
    assert (rejected["decision"], rejected["reason"]) == ("rejected", "Too long")
    # A dismiss without a body still works; a reason can come after it.
    plan = voiced(client, monkeypatch, text="Another try.")["plan"]
    later = client.post(f"/videos/p1/plans/{plan['plan_id']}/items/i1/dismiss", headers={"Content-Type": "application/json"})
    assert later.status_code == 200
    why = client.post(f"/videos/p1/decisions/{later.json()['decision_id']}/reason", json={"reason": "Wrong voice"})
    assert why.status_code == 200 and why.json()["reason"] == "Wrong voice"
    assert client.post("/videos/p1/decisions/999/reason", json={"reason": "x"}).status_code == 404


def test_an_add_after_rewording_is_an_edit_with_the_difference(client, in_project):
    main._decided_add("p1", "plan1", item(1, text="Thirty percent off today.", first="Get 30% off today."))
    [d] = learned.decisions(database, "f1")
    assert d["decision"] == "edited" and d["proposed_text"] == "Get 30% off today." and d["final_text"] == "Thirty percent off today."
    added = " ".join(r["text"] for r in d["diff"] if r["op"] == "added")
    removed = " ".join(r["text"] for r in d["diff"] if r["op"] == "removed")
    assert "Thirty" in added and "percent" in added and "Get" in removed and "30%" in removed


def test_the_pass_runs_at_10_and_20_decisions_and_not_between_with_its_cost_in_usage(client, in_project, monkeypatch):
    reader = FakeReader()
    monkeypatch.setattr(main, "_learn_reader", reader)
    seen = []
    for n in range(1, 26):
        main._log_decision("p1", "plan1", item(n), "rejected" if n % 3 else "added", final=None)
        seen.append(len(reader.calls))
    assert [i + 1 for i in range(25) if seen[i] != (seen[i - 1] if i else 0)] == [10, 20]
    assert len(reader.calls) == 2 and "Brief: Warm and bright." in reader.calls[0]
    assert ledger.spent_usd_by_folder("f1") > 0                     # the pass is charged to the project
    page = client.get("/projects/f1/learned").json()
    assert page["decisions"] == 25 and page["pending"]["at_count"] == 20 and page["learned"] == []


def test_a_suggestion_never_applies_without_accept(client, in_project, monkeypatch):
    monkeypatch.setattr(main, "_learn_reader", FakeReader({"kind": "brief", "text": "Always say the store opens at 10.", "why": "x"}))
    before = (briefs.current(database, "f1").version, rules.rules_version(database, "f1"))
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    page = client.get("/projects/f1/learned").json()
    assert page["pending"]["text"] == "Always say the store opens at 10."
    assert (briefs.current(database, "f1").version, rules.rules_version(database, "f1")) == before
    assert "store opens" not in repo.get_project("f1").brief
    sid = page["pending"]["item_id"]
    dismissed = client.post(f"/projects/f1/learned/{sid}/dismiss").json()
    assert dismissed["pending"] is None and dismissed["learned"] == []
    assert (briefs.current(database, "f1").version, rules.rules_version(database, "f1")) == before
    assert client.post(f"/projects/f1/learned/{sid}/accept").status_code == 409   # not waiting any more
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    sid = client.get("/projects/f1/learned").json()["pending"]["item_id"]
    took = client.post(f"/projects/f1/learned/{sid}/accept").json()
    assert took["project"]["brief"] == "Warm and bright.\nAlways say the store opens at 10."
    assert took["project"]["brief_version"] == before[0] + 1 and [i["text"] for i in took["learned"]] == ["Always say the store opens at 10."]


def opening_view(client, monkeypatch) -> str:
    from tests.agent.conftest import reply, text
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(text("Hello."))])
    job = await_job(client, client.post("/videos/p1/turns", json={"text": "hi"}).json()["job_id"])
    assert job["status"] == "succeeded"
    opened = [m for m in main.repo.turns("p1") if m["role"] == "user" and isinstance(m["content"], list)
              and m["content"] and str(m["content"][0].get("text", "")).startswith("Brief ·")]
    return opened[-1]["content"][0]["text"]


def test_removing_a_learned_item_takes_it_out_of_the_next_turns_opening_view(client, in_project, monkeypatch):
    for kind, line in (("brief", "Always name the Diwali Dhamaka sale."), ("rule", "Keep lines under eight words.")):
        sid = learned.suggest(database, "f1", kind, line, "Seen in your edits.", 10)["item_id"]
        assert client.post(f"/projects/f1/learned/{sid}/accept").status_code == 200
    head = opening_view(client, monkeypatch)
    assert "Always name the Diwali Dhamaka sale." in head and "Keep lines under eight words." in head
    for entry in client.get("/projects/f1/learned").json()["learned"]:
        out = client.delete(f"/projects/f1/learned/{entry['item_id']}")
        assert out.status_code == 200, out.text
    page = client.get("/projects/f1/learned").json()
    assert page["learned"] == []
    assert repo.get_project("f1").brief == "Warm and bright." and rules.list_rules(database, "f1") == []
    head = opening_view(client, monkeypatch)
    assert "Dhamaka" not in head and "eight words" not in head
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert verbs.count("learned.removed") == 2 and verbs.count("learned.accepted") == 2


def test_no_claude_key_skips_the_pass_silently(client, in_project, monkeypatch):
    monkeypatch.setattr(main, "_learn_reader", None)
    monkeypatch.setattr(main, "settings", replace(main.settings, anthropic_api_key=""))
    for n in range(10):
        assert main._log_decision("p1", "plan1", item(n), "added") is not None
    assert client.get("/projects/f1/learned").json()["pending"] is None
    assert ledger.spent_usd_by_folder("f1") == 0


def test_a_project_at_its_ceiling_skips_the_pass(client, in_project, monkeypatch):
    reader = FakeReader()
    monkeypatch.setattr(main, "_learn_reader", reader)
    client.patch("/projects/f1", json={"ceiling_usd": 0.0000001})
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    assert reader.calls == [] and client.get("/projects/f1/learned").json()["pending"] is None


def test_the_flag_off_hides_learned_style_and_skips_the_pass(client, in_project, monkeypatch):
    reader = FakeReader()
    monkeypatch.setattr(main, "_learn_reader", reader)
    flags.set("projects.reuse", "local", False)
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    assert reader.calls == []
    assert client.get("/projects/f1/learned").status_code == 404


def learn_jobs():
    return [j for j in main.activity.list("f1", limit=200) if j.kind == "learn"]


def test_each_pass_is_an_activity_job_keyed_by_the_project(client, in_project, monkeypatch):
    monkeypatch.setattr(main, "_learn_reader", FakeReader())
    for n in range(20):
        main._log_decision("p1", "plan1", item(n), "added")
    done = learn_jobs()
    assert len(done) == 2 and all(j.status == "done" for j in done)
    assert done[0].step_label == "Suggested one line" and done[0].cost_usd and done[0].detail["at_count"] == 20
    assert done[0].video_id == "f1"


def test_a_pass_that_finds_nothing_or_fails_says_so_on_its_job(client, in_project, monkeypatch):
    monkeypatch.setattr(main, "_learn_reader", FakeReader({"kind": "none"}))
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")

    class Broken(FakeReader):
        def suggest(self, text, meter=None):
            raise RuntimeError("Claude is unavailable right now.")
    monkeypatch.setattr(main, "_learn_reader", Broken())
    for n in range(10):
        assert main._log_decision("p1", "plan1", item(n), "added") is not None   # the add still stands
    failed, nothing = learn_jobs()
    assert nothing.status == "done" and nothing.step_label == "No pattern yet"
    assert failed.status == "failed" and failed.error_code == "learn_failed" and "unavailable" in failed.error_text


def test_a_skipped_pass_makes_no_job(client, in_project, monkeypatch):
    monkeypatch.setattr(main, "_learn_reader", None)
    monkeypatch.setattr(main, "settings", replace(main.settings, anthropic_api_key=""))
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    assert learn_jobs() == []


def test_a_fake_key_never_reaches_the_real_model(client, in_project, monkeypatch):
    """A fake key and no fake reader: the real client is built, and the
    suite's network guard stops its request; the job fails, nothing is spent."""
    monkeypatch.setattr(main, "_learn_reader", None)
    monkeypatch.setattr(main, "_learn_reader_built", None)
    monkeypatch.setattr(main, "settings", replace(main.settings, anthropic_api_key="k"))
    for n in range(10):
        main._log_decision("p1", "plan1", item(n), "added")
    [job] = learn_jobs()
    assert job.status == "failed" and ledger.spent_usd_by_folder("f1") == 0
