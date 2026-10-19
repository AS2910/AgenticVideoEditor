"""Folders: a project is a folder of videos. The folder routes, the move
with its voice question, settings resolving video → project → user, the
project ceiling, the agent's Brief block, and the deprecated aliases."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, await_job, generate, take, upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def folder(client):
    resp = client.post("/projects", json={"name": "Spring sale", "brief": "Bright, short, the price up front."})
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload_into(client, path, project_id, name="ad.mp4"):
    with open(path, "rb") as handle:
        return client.post("/videos", files={"file": (name, handle, "video/mp4")},
                           data={"consent": "true", "project_id": project_id})


def share(client, project_id, voice_id="SHARED1", name="Priya"):
    """One of the owner's voices, shared into the project."""
    import app.api.main as main
    mine = main._my_voices("local")
    if not any(v["voice_id"] == voice_id for v in mine):
        main._set_my_voices("local", [*mine, {"voice_id": voice_id, "name": name, "seconds": 12.0, "at": main._now(),
                                              "kind": "recorded", "sample_sha": None, "description": "warm"}])
    resp = client.post(f"/projects/{project_id}/voices", json={"voice_id": voice_id})
    assert resp.status_code == 201, resp.text
    return resp.json()


def shipped_in(client, video_id, voice_id):
    """A kept edit on the video, spoken in `voice_id`."""
    candidate = generate(project_id=video_id, voice_id=voice_id)
    resp = client.post(f"/videos/{video_id}/edits", json={"candidate_id": candidate["candidate_id"]})
    assert resp.status_code == 200, resp.text


# ── the folder routes ────────────────────────────────────────────────────────

def test_projects_are_made_listed_changed_and_deleted(client, folder, sample_video):
    assert folder["project_id"] == "f1" and folder["name"] == "Spring sale" and folder["brief"].startswith("Bright")
    assert folder["ceiling_usd"] is None and folder["spent_usd"] == 0.0 and folder["created_at"]
    assert set(folder["settings"]) == {"autonomy", "turn_usd", "effort", "ask_before"}
    assert client.post("/projects", json={"name": "  "}).status_code == 422

    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1", name="second.mp4")
    [listed] = client.get("/projects").json()["projects"]
    assert (listed["project_id"], listed["name"], listed["video_count"], listed["voices"], listed["files"]) == ("f1", "Spring sale", 2, 0, 0)
    assert listed["last_at"] >= listed["created_at"] and listed["spent_usd"] == 0.0 and listed["ceiling_usd"] is None

    page = client.get("/projects/f1").json()
    assert page["project"]["project_id"] == "f1" and [v["filename"] for v in page["videos"]] == ["second.mp4", "ad.mp4"]
    assert all(v["project_id"] == "f1" and v["project_name"] == "Spring sale" and v["video_id"] for v in page["videos"])
    assert page["voices"] == [] and page["files"] == [] and page["suggestions"] == []
    assert [v["filename"] for v in client.get("/projects/f1/videos").json()["videos"]] == ["second.mp4", "ad.mp4"]

    changed = client.patch("/projects/f1", json={"name": "Spring Sale 2026", "brief": "Louder.", "ceiling_usd": 5.0,
                                                 "settings": {"autonomy": "draft", "turn_usd": 0.2}}).json()
    assert (changed["name"], changed["brief"], changed["ceiling_usd"]) == ("Spring Sale 2026", "Louder.", 5.0)
    assert (changed["settings"]["autonomy"], changed["settings"]["turn_usd"]) == ("draft", 0.2)
    assert client.patch("/projects/f1", json={"ceiling_usd": None}).json()["ceiling_usd"] is None
    assert client.patch("/projects/f1", json={"ceiling_usd": -1}).status_code == 422
    assert client.patch("/projects/f1", json={"settings": {"effort": "max"}}).status_code == 422
    assert client.get("/projects/f9").status_code == 404

    # Deleting always says what happens to the videos.
    assert client.delete("/projects/f1").status_code == 422
    assert client.delete("/projects/f1", params={"videos": "keep"}).status_code == 204
    assert client.get("/projects").json()["projects"] == []
    assert [v["project_id"] for v in client.get("/videos").json()["videos"]] == [None, None]

    client.post("/projects", json={"name": "Autumn"})
    upload_into(client, sample_video, "f2")
    assert client.delete("/projects/f2", params={"videos": "delete"}).status_code == 204
    assert [v["video_id"] for v in client.get("/videos").json()["videos"]] == ["p2", "p1"]
    assert client.get("/videos/p3").status_code == 404


def test_videos_are_listed_by_project_and_recent(client, folder, sample_video):
    upload(client, sample_video, name="alone.mp4")
    upload_into(client, sample_video, "f1", name="in.mp4")
    assert [v["filename"] for v in client.get("/videos").json()["videos"]] == ["in.mp4", "alone.mp4"]
    assert [v["filename"] for v in client.get("/videos", params={"project": "none"}).json()["videos"]] == ["alone.mp4"]
    assert [v["filename"] for v in client.get("/videos", params={"project": "f1"}).json()["videos"]] == ["in.mp4"]
    assert [v["filename"] for v in client.get("/videos", params={"recent": 1}).json()["videos"]] == ["in.mp4"]
    assert client.get("/videos", params={"project": "f9"}).status_code == 404
    assert upload_into(client, sample_video, "f9").status_code == 404
    record = client.get("/videos/p2").json()
    assert (record["video_id"], record["project_id"], record["project_name"]) == ("p2", "f1", "Spring sale")


# ── settings resolve video → project → user ──────────────────────────────────

def test_a_video_in_a_project_starts_with_its_defaults_and_a_missing_key_reads_project_then_user(client, folder, sample_video):
    import app.api.main as main
    client.put("/me/settings", json={"effort": "xhigh", "ask_before": {"ship": True}})
    client.patch("/projects/f1", json={"settings": {"autonomy": "draft", "turn_usd": 0.2, "ask_before": {"clone": True}}})
    assert client.get("/projects/f1").json()["project"]["settings"] == {
        "autonomy": "draft", "turn_usd": 0.2, "effort": "xhigh", "ask_before": {"ship": True, "clone": True, "design": False}}

    made = upload_into(client, sample_video, "f1").json()
    assert (made["settings"]["autonomy"], made["settings"]["turn_usd"], made["settings"]["effort"]) == ("draft", 0.2, "xhigh")
    assert made["settings"]["ask_before"] == {"ship": True, "clone": True, "design": False}
    # Copied in: a later change to the project's defaults leaves the video as it was set.
    client.patch("/projects/f1", json={"settings": {"autonomy": "ask"}})
    assert client.get("/videos/p1/settings").json()["settings"]["autonomy"] == "draft"

    # A video that never set a key reads the project's, then the owner's.
    with main.database.tx() as c:
        c.execute("UPDATE videos SET settings = '{}' WHERE id = 'p1'")
    resolved = client.get("/videos/p1/settings").json()["settings"]
    assert (resolved["autonomy"], resolved["turn_usd"], resolved["effort"]) == ("ask", 0.2, "xhigh")
    assert resolved["ask_before"] == {"ship": True, "clone": True, "design": False}
    # Out of the project, the same video reads the owner's alone.
    client.patch("/videos/p1", json={"project_id": None})
    alone = client.get("/videos/p1/settings").json()["settings"]
    assert (alone["autonomy"], alone["turn_usd"], alone["effort"], alone["ask_before"]) == (
        "ask", main.settings.agent_turn_usd, "xhigh", {"ship": True, "clone": False, "design": False})


# ── moving ───────────────────────────────────────────────────────────────────

def test_moving_a_video_keeps_its_work_and_asks_about_a_project_voice_it_uses(client, folder, sample_video):
    import app.api.main as main
    upload_into(client, sample_video, "f1")
    share(client, "f1")
    shipped_in(client, "p1", "SHARED1")
    client.post("/projects", json={"name": "Autumn"})

    # Leaving with the shared voice in a kept edit: the question, with the voices named.
    resp = client.patch("/videos/p1", json={"project_id": None})
    assert resp.status_code == 409
    assert resp.json()["voices"] == [{"voice_id": "SHARED1", "name": "Priya"}] and "Priya" in resp.json()["detail"]
    # Moving to another project that lacks the voice asks too; one that shares it does not.
    assert client.patch("/videos/p1", json={"project_id": "f2"}).status_code == 409
    assert client.get("/videos/p1").json()["project_id"] == "f1"
    assert client.get("/projects/f1").json()["voices"][0]["used_in"] == 1

    moved = client.patch("/videos/p1", json={"project_id": "f2", "voice": "copy"}).json()
    assert (moved["video_id"], moved["project_id"], moved["project_name"]) == ("p1", "f2", "Autumn")
    assert [m["voice_id"] for m in main.repo.settings("p1")["made_voices"]] == ["SHARED1"]
    # The edits came along; a voice the video now carries needs no question next time.
    assert len(client.get("/videos/p1").json()["edits"]) == 1
    assert client.patch("/videos/p1", json={"project_id": "f1"}).status_code == 200
    assert client.patch("/videos/p1", json={"project_id": None}).status_code == 200
    assert client.get("/videos/p1").json()["project_id"] is None
    assert client.patch("/videos/p1", json={"project_id": "f9"}).status_code == 404

    # `keep` puts the voice among the owner's own instead.
    main._set_my_voices("local", [])
    share(client, "f1", voice_id="SHARED2", name="Ravi")
    main._set_my_voices("local", [])     # shared, but no longer one of the owner's
    upload_into(client, sample_video, "f1", name="two.mp4")
    shipped_in(client, "p2", "SHARED2")
    assert client.patch("/videos/p2", json={"project_id": None}).status_code == 409
    assert client.patch("/videos/p2", json={"project_id": None, "voice": "keep"}).status_code == 200
    assert [(v["voice_id"], v["name"]) for v in main._my_voices("local")] == [("SHARED2", "Ravi")]
    assert "made_voices" not in main.repo.settings("p2")


def test_a_variant_lands_in_the_same_project_and_deleting_a_video_touches_nothing_else(client, folder, sample_video):
    upload_into(client, sample_video, "f1")
    upload_into(client, sample_video, "f1", name="two.mp4")
    variant = client.post("/videos/p1/variants").json()
    assert (variant["video_id"], variant["project_id"], variant["project_name"]) == ("p3", "f1", "Spring sale")
    assert client.delete("/videos/p1").status_code == 204
    page = client.get("/projects/f1").json()
    assert [v["video_id"] for v in page["videos"]] == ["p3", "p2"] and page["project"]["name"] == "Spring sale"


# ── money ────────────────────────────────────────────────────────────────────

def test_the_project_ceiling_joins_the_reservation_and_rows_carry_the_folder(client, folder, sample_video, monkeypatch):
    import app.api.main as main
    upload(client, sample_video)                         # p1, standalone
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.03)
    client.patch("/videos/p1", json={"project_id": "f1"})
    # Spend from before the move stays outside the project's share.
    assert client.get("/projects/f1").json()["project"]["spent_usd"] == 0.0
    main.ledger.record("p1", "elevenlabs", "speech", 100, "characters", 0.06)
    with main.database.tx() as c:
        assert [r["folder_id"] for r in c.execute("SELECT folder_id FROM usage WHERE project_id = 'p1' ORDER BY id")] == [None, "f1"]
    usage = client.get("/videos/p1/usage").json()
    assert usage["project_ceiling_usd"] is None and usage["project_spent_usd"] == 0.06 and usage["spent_usd"] == 0.09

    client.patch("/projects/f1", json={"ceiling_usd": 0.05})
    assert client.get("/videos/p1/usage").json()["project_ceiling_usd"] == 0.05
    assert client.get("/projects").json()["projects"][0]["spent_usd"] == 0.06
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [])
    resp = client.post("/videos/p1/turns", json={"text": "make it 30% off"})
    job = await_job(client, resp.json()["job_id"])
    assert job["status"] == "succeeded" and "The project Spring sale has used its $0.05 spending ceiling" in job["result"]["reply"]
    assert scripted.calls == []
    # The video's own ceiling was nowhere near; raise the project's and the turn runs.
    client.patch("/projects/f1", json={"ceiling_usd": 1.0})
    from tests.agent.conftest import reply, text
    scripted.responses.extend([reply(take(), stop="tool_use"), reply(text("Done."))])
    job = await_job(client, client.post("/videos/p1/turns", json={"text": "make it 30% off"}).json()["job_id"])
    assert job["result"]["reply"] == "Done."
    # Every row charged since the move — the turn's thinking, the take — carries the folder.
    with main.database.tx() as c:
        rows = [r["folder_id"] for r in c.execute("SELECT folder_id FROM usage WHERE project_id = 'p1' ORDER BY id")]
    assert len(rows) > 2 and rows[0] is None and all(f == "f1" for f in rows[1:])


def test_usage_is_by_video_and_by_project(client, folder, sample_video, monkeypatch):
    import app.api.main as main
    upload_into(client, sample_video, "f1")
    upload(client, sample_video, name="alone.mp4")
    main.ledger.record("p1", "elevenlabs", "speech", 40, "characters", 0.012)
    main.ledger.record("p2", "elevenlabs", "speech", 40, "characters", 0.02)
    main.repo.add_message("p1", "assistant", "Thinking", kind="step", cost=0.01)
    month = client.get("/usage").json()
    assert [(v["video_id"], v["project_id"], v["filename"], v["spent_usd"]) for v in month["by_video"]] == [
        ("p2", None, "alone.mp4", 0.02), ("p1", "f1", "ad.mp4", 0.012)]
    assert month["by_project"] == [{"project_id": "f1", "name": "Spring sale", "videos": 1, "turns": 1, "spent_usd": 0.012, "ceiling_usd": None}]
    assert "by_project" in month and all("video_id" in v for v in month["by_video"])


# ── reference files, shared voices, suggestions ──────────────────────────────

def test_reference_files_keep_their_text_where_it_can_be_read(client, folder):
    import app.api.main as main
    brief = client.post("/projects/f1/files", files={"file": ("brief.txt", io.BytesIO(b"Say the price first. Always 30% off."), "text/plain")})
    assert brief.status_code == 201, brief.text
    entry = brief.json()
    assert (entry["name"], entry["kind"], entry["size"]) == ("brief.txt", "txt", 36) and len(entry["sha256"]) == 64 and "text" not in entry
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as z:
        z.writestr("word/document.xml", "<w:document><w:body><w:p><w:r><w:t>Tone: warm</w:t></w:r></w:p><w:p><w:r><w:t>Never shout.</w:t></w:r></w:p></w:body></w:document>")
    assert client.post("/projects/f1/files", files={"file": ("notes.docx", docx.getvalue(), "application/octet-stream")}).status_code == 201
    pdf = client.post("/projects/f1/files", files={"file": ("deck.pdf", b"%PDF-1.4 nothing readable", "application/pdf")}).json()
    assert pdf["kind"] == "pdf"
    assert client.post("/projects/f1/files", files={"file": ("empty.txt", b"", "text/plain")}).status_code == 422

    kept = {f["name"]: f for f in main._project_files("f1")}
    assert kept["brief.txt"]["text"] == "Say the price first. Always 30% off."
    assert kept["notes.docx"]["text"].split() == ["Tone:", "warm", "Never", "shout."]
    try:
        import pypdf  # noqa: F401
    except ImportError:
        assert kept["deck.pdf"]["text"] == ""
    page = client.get("/projects/f1").json()
    assert [f["name"] for f in page["files"]] == ["brief.txt", "notes.docx", "deck.pdf"] and all("text" not in f for f in page["files"])
    assert client.get("/projects").json()["projects"][0]["files"] == 3

    served = client.get(f"/projects/f1/files/{entry['sha256']}")
    assert served.status_code == 200 and served.content == b"Say the price first. Always 30% off." and served.headers["content-type"].startswith("text/plain")
    assert client.get("/projects/f1/files/" + "0" * 64).status_code == 404
    assert client.delete(f"/projects/f1/files/{entry['sha256']}").status_code == 204
    assert client.delete(f"/projects/f1/files/{entry['sha256']}").status_code == 404
    assert client.get(f"/projects/f1/files/{entry['sha256']}").status_code == 404
    assert [f["name"] for f in main._project_files("f1")] == ["notes.docx", "deck.pdf"]


def test_voices_shared_in_a_project_are_listed_with_their_project(client, folder, sample_video):
    import app.api.main as main
    upload_into(client, sample_video, "f1")
    entry = share(client, "f1")
    assert (entry["voice_id"], entry["name"], entry["kind"], entry["used_in"]) == ("SHARED1", "Priya", "recorded", 0)
    assert client.post("/projects/f1/voices", json={"voice_id": "SHARED1"}).status_code == 409
    assert client.post("/projects/f1/voices", json={"voice_id": "nobody"}).status_code == 404
    # A voice Voltage made in a video can be shared too.
    main.repo.set_settings("p1", made_voices=[{"voice_id": "MADE1", "name": "Dusk", "kind": "designed", "at": main._now(), "description": "low"}])
    assert client.post("/projects/f1/voices", json={"voice_id": "MADE1"}).json()["kind"] == "designed"
    voices = client.get("/voices").json()
    assert [(v["voice_id"], v["project_id"], v["project_name"]) for v in voices["project"]] == [
        ("SHARED1", "f1", "Spring sale"), ("MADE1", "f1", "Spring sale")]
    assert [v["voice_id"] for v in voices["mine"]] == ["SHARED1"]
    shipped_in(client, "p1", "MADE1")
    assert [(v["voice_id"], v["used_in"]) for v in client.get("/projects/f1").json()["voices"]] == [("SHARED1", 0), ("MADE1", 1)]
    assert client.get("/projects").json()["projects"][0]["voices"] == 2
    assert client.delete("/projects/f1/voices/SHARED1").status_code == 204
    assert client.delete("/projects/f1/voices/SHARED1").status_code == 404
    assert [v["voice_id"] for v in client.get("/voices").json()["project"]] == ["MADE1"]
    # Deleting the project with its videos lets go of a made voice no one kept.
    deleted = []
    main.voice.delete_voice = deleted.append
    try:
        assert client.delete("/projects/f1", params={"videos": "delete"}).status_code == 204
    finally:
        del main.voice.delete_voice
    assert deleted == ["MADE1"] and client.get("/voices").json()["project"] == []


def test_brief_suggestions_are_accepted_or_dismissed(client, folder, sample_video):
    import app.api.main as main
    upload_into(client, sample_video, "f1")
    upload(client, sample_video, name="alone.mp4")
    assert main._suggest_brief("p2", "Nothing", "standalone") is None
    assert main._suggest_brief("p1", "Say the price first.", "Both videos lead with it.") == "s1"
    assert main._suggest_brief("p1", "End on the dates.", "") == "s2"
    [one, two] = client.get("/projects/f1").json()["suggestions"]
    assert (one["id"], one["text"], one["why"], one["video_id"], one["filename"]) == ("s1", "Say the price first.", "Both videos lead with it.", "p1", "ad.mp4")
    assert two["id"] == "s2" and one["at"]
    accepted = client.post("/projects/f1/suggestions/s1/accept").json()
    assert accepted["project"]["brief"] == "Bright, short, the price up front.\nSay the price first."
    assert [s["id"] for s in accepted["suggestions"]] == ["s2"]
    assert client.post("/projects/f1/suggestions/s1/accept").status_code == 404
    dismissed = client.post("/projects/f1/suggestions/s2/dismiss").json()
    assert dismissed["suggestions"] == [] and dismissed["project"]["brief"].endswith("Say the price first.")


# ── the agent sees the project ───────────────────────────────────────────────

def test_the_opening_view_starts_with_the_brief_block(client, folder, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text
    upload_into(client, sample_video, "f1", name="sister.mp4")
    shipped_in(client, "p1", "mock")
    upload_into(client, sample_video, "f1")
    share(client, "f1")
    client.post("/projects/f1/files", files={"file": ("brief.txt", b"Price first.", "text/plain")})
    client.put("/videos/p2/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(text("Hello."))])
    job = await_job(client, client.post("/videos/p2/turns", json={"text": "hi"}).json()["job_id"])
    assert job["status"] == "succeeded"
    head = main.repo.turns("p2")[0]["content"][0]["text"]
    assert head.startswith("Brief · Spring sale: Bright, short, the price up front.\n"
                           "Shared voices in this project: Priya.\n"
                           "Sister videos in this project: sister.mp4 (2.3 s).\n"
                           "Reference files: brief.txt (read_project_files searches them).\n"
                           "The clip: ad.mp4, 2.3 s,")
    # A standalone video has no Brief block.
    upload(client, sample_video, name="alone.mp4")
    client.put("/videos/p3/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(text("Hello."))])
    await_job(client, client.post("/videos/p3/turns", json={"text": "hi"}).json()["job_id"])
    assert main.repo.turns("p3")[0]["content"][0]["text"].startswith("The clip: alone.mp4")
    # The project seam the tools read.
    view = main._project_view("p2")
    assert view["name"] == "Spring sale" and [v["voice_id"] for v in view["voices"]] == ["SHARED1"]
    assert [(v["filename"], v["shipped"]) for v in view["videos"]] == [("sister.mp4", [{"text": "30% off", "voice": "Test tone's voice"}])]
    assert view["files"][0]["text"] == "Price first."


def test_a_search_help_step_carries_the_articles_it_found(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text, use
    upload(client, sample_video)
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    asked = []

    def fake_search(query, limit=3):
        asked.append((query, limit))
        return [{"slug": "ship-a-line", "section": "Editing", "title": "Ship a line", "summary": "Add it puts a take in the video.",
                 "body": "Press Add it on the line. " * 40, "tour": "ship"}]

    monkeypatch.setattr(main, "search_help_articles", fake_search)
    _agent_on(monkeypatch, main, [reply(use("search_help", query="how do I ship a line"), stop="tool_use"),
                                  reply(text("From Help, Ship a line: press Add it on the line. Want me to ship it?"))])
    job = await_job(client, client.post("/videos/p1/turns", json={"text": "how do I ship a line?"}).json()["job_id"])
    assert job["status"] == "succeeded" and asked == [("how do I ship a line", 3)]
    step = next(m for m in client.get("/videos/p1/messages").json() if m["kind"] == "step" and m["text"].startswith("Looked in Help"))
    assert step["text"] == "Looked in Help: Ship a line"
    assert step["data"]["tool"] == "search_help"
    assert step["data"]["help"] == [{"slug": "ship-a-line", "title": "Ship a line", "section": "Editing", "tour": "ship"}]


def test_a_tutorial_video_replays_without_the_agent(client, sample_video, monkeypatch):
    import app.api.main as main
    upload(client, sample_video)
    replayed = []
    monkeypatch.setattr(main, "is_tutorial", lambda repo_, video_id: video_id == "p1")
    monkeypatch.setattr(main, "replay_turn", lambda repo_, video_id, text, owner: replayed.append((video_id, text, owner)) or
                        {"job_id": "tutorial", "kind": "turn", "video_id": video_id, "status": "succeeded", "result": {"reply": "Replayed."}})
    # The agent is off (no key): a tutorial turn never needs it.
    resp = client.post("/videos/p1/turns", json={"text": "make it 30% off"})
    assert resp.status_code == 202 and resp.json()["result"]["reply"] == "Replayed."
    assert replayed == [("p1", "make it 30% off", "local")]
    monkeypatch.setattr(main, "is_tutorial", lambda repo_, video_id: False)
    assert client.post("/videos/p1/turns", json={"text": "make it 30% off"}).status_code == 503


# ── the old paths ────────────────────────────────────────────────────────────

def test_the_old_project_paths_answer_as_deprecated_aliases(client, sample_video):
    upload(client, sample_video)
    assert client.get("/projects/p1/settings").json() == client.get("/videos/p1/settings").json()
    assert client.get("/projects/p1/messages").status_code == 200
    assert client.put("/projects/p1/settings", json={"effort": "xhigh"}).json()["settings"]["effort"] == "xhigh"
    # The three that changed meaning belong to folders now.
    assert client.get("/projects/p1").status_code == 404
    assert client.delete("/projects/p1", params={"videos": "keep"}).status_code == 404
    assert client.post("/projects", json={"name": "A folder"}).status_code == 201
    paths = app.openapi()["paths"]
    assert paths["/projects/{project_id}/settings"]["get"].get("deprecated") is True
    assert "deprecated" not in paths["/videos/{project_id}/settings"]["get"]
    assert "/projects/{project_id}/artifacts/{sha256}" in paths and "/videos/{project_id}/artifacts/{sha256}" in paths
    # Every payload names the video as video_id and the folder as project_id.
    job = client.get("/videos/p1").json()
    assert job["video_id"] == "p1" and job["project_id"] is None
    assert client.post("/videos/p1/consent").json()["video_id"] == "p1"
