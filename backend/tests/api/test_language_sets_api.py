"""B2 through the API: Make language versions makes one variant per language
linked to its master and runs ONE batch turn over them; a master's new edit
marks every version out of sync; Sync this change runs a turn on one version
for only the master's lines changed since it last synced; a brand term stays
untranslated (a take that translates it is marked and never passes). Claude
is scripted per video and the voice is the mock (no spend)."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, flags, jobs, repo
from app.domain.models import ApprovedEdit, EditPlan, Selection
from app.media import ffmpeg
from app.store.actors import user
from tests.agent.conftest import reply, text
from tests.api.test_batch_api import agent, finished
from tests.api.test_endpoints import await_job, take
from tests.api.test_folders import upload_into
from tests.store.test_repository import AUDIO, FRAMES

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.batch", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def ship(video_id, edit_id, start, end, words):
    """A shipped edit on the master, as the editor's Add it records it (F7's edit.shipped)."""
    plan = EditPlan(Selection(start, end), words, "mock")
    repo.append_edit(video_id, ApprovedEdit(edit_id, f"c-{edit_id}", plan, AUDIO, FRAMES), actor=user("local"))


def master(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    assert upload_into(client, sample_video, "f1", name="ad.mp4").status_code == 200
    return "p1"


def make(client, langs=("hi", "ta"), voice="same"):
    resp = client.post("/videos/p1/languages", json={"languages": list(langs), "voice": voice})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    return body, finished(client, body["batch_id"])


def test_language_versions_are_linked_variants_made_by_one_batch(client, sample_video, monkeypatch):
    master(client, sample_video)
    agent(monkeypatch, {})
    got = client.get("/videos/p1/languages").json()
    assert got["original"] == "en" and [o["code"] for o in got["options"]] == ["hi", "hinglish", "ta", "mr"]
    dry = client.post("/videos/p1/languages", json={"languages": ["hi", "ta"], "dry_run": True}).json()
    assert dry["batch_id"] is None and dry["gate"]["videos"] == 2 and dry["gate"]["lines"] == 2
    assert repo.language_children("p1") == []                         # the numbers first, nothing made
    body, board = make(client)
    assert [c["language"] for c in body["children"]] == ["hi", "ta"]
    kids = {r.source.project_id: r for r in repo.language_children("p1")}
    assert set(kids) == {"p2", "p3"} and {k.language for k in kids.values()} == {"hi", "ta"}
    assert all(k.master_id == "p1" and k.folder_id == "f1" for k in kids.values())
    assert board["source"] == "language" and [r["video_id"] for r in board["rows"]] == ["p2", "p3"]
    assert board["phase"] == "finished"
    card = next(v for v in client.get("/projects/f1/videos").json()["videos"] if v["video_id"] == "p1")
    assert [c["label"] for c in card["languages"]] == ["Hindi", "Tamil"]
    assert client.post("/videos/p1/languages", json={"languages": ["hi"]}).status_code == 409    # made already
    assert client.post("/videos/p2/languages", json={"languages": ["mr"]}).status_code == 409    # not from a version
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert "language.versions_made" in verbs and "batch.started" in verbs


def test_the_translation_goal_and_opening_view_name_the_brand_and_glossary(client, sample_video, monkeypatch):
    import app.api.main as main
    from app.agent.context import brief_block
    master(client, sample_video)
    client.post("/projects/f1/rules", json={"kind": "pronounce", "data": {"term": "Bhajicam", "say": "bhaji cam", "brand": True}})
    client.post("/projects/f1/rules", json={"kind": "pronounce", "data": {"term": "off", "say": "off", "lang": "hi", "translation": "छूट"}})
    agent(monkeypatch, {})
    body, board = make(client, langs=("hi",))
    goal = board["goal"]
    assert "Hindi" in goal
    child = body["children"][0]["video_id"]
    block = "\n".join(brief_block(main._project_view(child)))
    assert "the Hindi version of ad.mp4" in block and "Never translate: Bhajicam" in block
    assert "Hindi glossary: “off” is “छूट”" in block


def test_a_master_edit_marks_every_version_out_of_sync(client, sample_video, monkeypatch):
    master(client, sample_video)
    agent(monkeypatch, {})
    make(client)
    assert [client.get(f"/videos/{v}").json()["out_of_sync"] for v in ("p2", "p3")] == [False, False]
    ship("p1", "e1", 0.0, 2.3, "Get 30% off today only.")
    assert [client.get(f"/videos/{v}").json()["out_of_sync"] for v in ("p2", "p3")] == [True, True]
    card = next(v for v in client.get("/projects/f1/videos").json()["videos"] if v["video_id"] == "p1")
    assert [c["out_of_sync"] for c in card["languages"]] == [True, True]
    assert client.get("/videos/p1").json()["out_of_sync"] is False                    # the master is never out of sync


def test_sync_touches_only_the_lines_changed_since_the_last_sync(client, sample_video, monkeypatch):
    import app.api.main as main
    master(client, sample_video)
    ship("p1", "e1", 0.0, 1.0, "Get thirty percent")                                 # before the versions: in them already
    agent(monkeypatch, {})
    make(client)
    ship("p1", "e2", 1.2, 2.3, "off this weekend only.")
    goals = []
    real = main._start_turn

    def spy(video_id, record, goal, owner, **kw):
        goals.append((video_id, goal, kw))
        return real(video_id, record, goal, owner, **kw)
    monkeypatch.setattr(main, "_start_turn", spy)
    resp = client.post("/videos/p2/sync")
    assert resp.status_code == 202, resp.text
    out = resp.json()
    assert [ln["edit_id"] for ln in out["lines"]] == ["e2"]
    (vid, goal, kw), = goals
    assert vid == "p2" and kw.get("approve") is True
    assert "off this weekend only." in goal and "1.2–2.3 s" in goal
    assert "Get thirty percent" not in goal and "0.0–1.0 s" not in goal
    assert "Hindi" in goal and "changed 1 line" in goal
    await_job(client, out["job_id"])
    for _ in range(600):                                                       # up to 30 s under load
        if not client.get("/videos/p2").json()["out_of_sync"]:
            break
        import time
        time.sleep(0.05)
    assert client.get("/videos/p2").json()["out_of_sync"] is False and repo.get("p2").synced_edit == out["to"]
    assert client.get("/videos/p3").json()["out_of_sync"] is True                     # only the one synced
    assert client.post("/videos/p2/sync").status_code == 409                           # in step now


def test_a_brand_term_stays_untranslated(client, sample_video, monkeypatch):
    import app.api.main as main
    master(client, sample_video)
    client.post("/projects/f1/rules", json={"kind": "pronounce", "data": {"term": "Bhajicam", "say": "bhaji cam", "brand": True}})
    ship("p1", "e1", 0.0, 2.3, "Bhajicam gives 20% off today only.")
    agent(monkeypatch, {
        "p2": [reply(take(text="भाजीकैम पर आज 20% छूट।"), stop="tool_use"), reply(text("Ready to hear."))],
        "p3": [reply(take(text="Bhajicam இல் இன்று 20% தள்ளுபடி."), stop="tool_use"), reply(text("Ready to hear."))],
    })
    body, board = make(client)
    hi = repo.latest_plan("p2").items[0]
    ta = repo.latest_plan("p3").items[0]
    assert hi.word_rule["brand"] == ["Bhajicam"]
    assert any(b.startswith("Brand name translated") for b in hi.word_rule["breaks"])
    assert not (ta.word_rule or {}).get("breaks")
    assert main._passing_items("p2")[1] == [] and main._passing_items("p3")[1] == [ta.item_id]
    added = client.post(f"/projects/f1/batches/{body['batch_id']}/add-all")
    assert added.status_code == 200
    assert [e for e in repo.list_edits("p2") if not e.reverted] == []                  # never picked
    assert len([e for e in repo.list_edits("p3") if not e.reverted]) == 1


def test_the_flag_off_hides_language_sets(client, sample_video):
    master(client, sample_video)
    flags.set("projects.batch", "local", False)
    assert client.get("/videos/p1/languages").status_code == 404
    assert client.post("/videos/p1/languages", json={"languages": ["hi"]}).status_code == 404
