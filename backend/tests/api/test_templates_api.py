"""D1 through the API: Save as template keeps a project's brief, words and
rules, presets, defaults and ceiling; New project from a template starts
with the same brief text and rules and no videos; a project's own voices
ask the move's question (copy into the template, or keep in my voices);
starters are read-only; the flag off hides it all."""
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, database, flags, jobs, repo
from app.media import ffmpeg
from app.store import presets, rules
from tests.api.test_folders import upload_into


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield
    flags.clear("projects.reuse", "local")


@pytest.fixture()
def client():
    return TestClient(app)


def project_with_everything(client):
    made = client.post("/projects", json={"name": "Diwali 2026", "brief": "Warm and bright. Say 30% off."}).json()
    pid = made["project_id"]
    assert client.patch(f"/projects/{pid}", json={"settings": {"autonomy": "draft", "turn_usd": 0.8, "effort": "high"},
                                                  "ceiling_usd": 25}).status_code == 200
    for kind, data in (("pronounce", {"term": "Bhaji", "say": "BAH-jee", "respell": "bah jee", "brand": True}),
                       ("banned", {"word": "cheap"}), ("required_line", {"text": "T&C apply."}),
                       ("style", {"text": "Short lines."})):
        assert client.post(f"/projects/{pid}/rules", json={"kind": kind, "data": data}).status_code == 201
    client.get(f"/projects/{pid}/export-presets")   # the three defaults
    assert client.post(f"/projects/{pid}/export-presets", json={"name": "Shorts", "platform": "reels", "captions": True,
                                                                "loudness": -16}).status_code == 201
    return pid


def test_a_project_from_a_template_has_no_videos_and_the_same_brief_and_rules(client, sample_video):
    if not ffmpeg.available():
        pytest.skip("ffmpeg not installed")
    pid = project_with_everything(client)
    assert upload_into(client, sample_video, pid).status_code == 200
    saved = client.post(f"/projects/{pid}/template", json={"name": "  Festival   ads "})
    assert saved.status_code == 201, saved.text
    t = saved.json()
    assert t["name"] == "Festival ads" and t["starter"] is False
    assert t["summary"]["rules"] == 4 and t["summary"]["words"] == 1 and t["summary"]["presets"] == 4
    made = client.post("/projects", json={"name": "Holi 2027", "template_id": t["template_id"]})
    assert made.status_code == 201, made.text
    new = made.json()["project_id"]
    assert new != pid
    assert client.get(f"/projects/{new}/videos").json()["videos"] == []
    page = client.get(f"/projects/{new}").json()
    assert page["project"]["brief"] == "Warm and bright. Say 30% off." and page["project"]["brief_version"] == 1
    assert page["project"]["ceiling_usd"] == 25
    assert page["project"]["settings"] == client.get(f"/projects/{pid}").json()["project"]["settings"]
    assert {k: page["project"]["settings"][k] for k in ("autonomy", "turn_usd", "effort")} == {"autonomy": "draft", "turn_usd": 0.8, "effort": "high"}
    pick = lambda p: [(r.kind, r.data) for r in rules.list_rules(database, p)]
    assert pick(new) == pick(pid)
    names = lambda p: [(x.name, x.platform, x.loudness, x.captions) for x in presets.list_presets(database, p, "local")]
    assert names(new) == names(pid)
    verbs = [e["verb"] for e in client.get(f"/projects/{new}/events").json()["events"]]
    assert "project.from_template" in verbs


def test_starters_are_listed_first_read_only_and_make_a_project(client):
    listed = client.get("/templates").json()["templates"]
    assert [t["name"] for t in listed[:3]] == ["Festive ad", "Product explainer", "Interview cleanup"]
    assert all(t["starter"] for t in listed[:3])
    for t in listed[:3]:
        text = repr(t)
        assert "—" not in text and "–" not in text   # plain copy, no dashes
    assert client.delete("/templates/starter-festive-ad").status_code == 403
    assert client.patch("/templates/starter-festive-ad", json={"name": "Mine"}).status_code == 403
    made = client.post("/projects", json={"name": "Navratri sale", "template_id": "starter-festive-ad"}).json()
    texts = [r.data.get("text") for r in rules.list_rules(database, made["project_id"], "required_line")]
    assert texts == ["T&C apply."]
    assert [p.name for p in presets.list_presets(database, made["project_id"], "local")] == ["Reels 9:16", "Feed 1:1", "YouTube 16:9"]
    assert made["ceiling_usd"] == 20


def test_templates_are_renamed_and_deleted_and_projects_made_from_them_keep_everything(client):
    pid = project_with_everything(client)
    t = client.post(f"/projects/{pid}/template", json={"name": "Ads"}).json()
    renamed = client.patch(f"/templates/{t['template_id']}", json={"name": "Festival ads"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "Festival ads"
    assert client.patch(f"/templates/{t['template_id']}", json={"name": "  "}).status_code == 422
    new = client.post("/projects", json={"name": "Later", "template_id": t["template_id"]}).json()["project_id"]
    assert client.delete(f"/templates/{t['template_id']}").status_code == 204
    assert client.delete(f"/templates/{t['template_id']}").status_code == 404
    assert t["template_id"] not in [x["template_id"] for x in client.get("/templates").json()["templates"]]
    assert len(rules.list_rules(database, new)) == 4
    assert client.post("/projects", json={"name": "Gone", "template_id": t["template_id"]}).status_code == 404


def test_a_projects_own_voice_asks_copy_or_keep_and_mine_are_referenced(client):
    pid = project_with_everything(client)
    main._set_my_voices("local", [{"voice_id": "MINE1", "name": "Priya", "seconds": 3.0, "at": main._now(), "kind": "recorded"}])
    main._set_project_voices(pid, [
        {"voice_id": "MINE1", "name": "Priya", "kind": "recorded", "at": main._now()},
        {"voice_id": "MADE1", "name": "Dusk", "kind": "designed", "at": main._now(), "consent_needed": False},
    ])
    asked = client.post(f"/projects/{pid}/template", json={"name": "Ads"})
    assert asked.status_code == 409
    assert asked.json()["voices"] == [{"voice_id": "MADE1", "name": "Dusk"}]
    assert "Copy the voice into the template, or keep it in your voices." in asked.json()["detail"]
    copied = client.post(f"/projects/{pid}/template", json={"name": "Ads", "voice": "copy"}).json()
    assert [v["voice_id"] for v in main._my_voices("local")] == ["MINE1"]   # copy leaves my voices alone
    kept = client.post(f"/projects/{pid}/template", json={"name": "Ads 2", "voice": "keep"}).json()
    assert [v["voice_id"] for v in main._my_voices("local")] == ["MINE1", "MADE1"]
    assert kept["summary"]["voices"] == 2 and copied["summary"]["voices"] == 2
    # A new project shares both; once Priya leaves my voices, a referenced voice is not shared any more.
    a = client.post("/projects", json={"name": "A", "template_id": copied["template_id"]}).json()["project_id"]
    assert [v["voice_id"] for v in main._project_voices(a)] == ["MINE1", "MADE1"]
    main._set_my_voices("local", [v for v in main._my_voices("local") if v["voice_id"] != "MINE1"])
    b = client.post("/projects", json={"name": "B", "template_id": copied["template_id"]}).json()["project_id"]
    assert [v["voice_id"] for v in main._project_voices(b)] == ["MADE1"]


def test_an_archived_project_can_still_be_saved_as_a_template(client):
    pid = project_with_everything(client)
    assert client.post(f"/projects/{pid}/archive").status_code == 200
    assert client.post(f"/projects/{pid}/template", json={"name": "From the archive"}).status_code == 201


def test_the_flag_off_hides_templates(client):
    pid = project_with_everything(client)
    flags.set("projects.reuse", "local", False)
    assert client.get("/templates").status_code == 404
    assert client.post(f"/projects/{pid}/template", json={"name": "x"}).status_code == 404
    assert client.post("/projects", json={"name": "x", "template_id": "starter-festive-ad"}).status_code == 404
