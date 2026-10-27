"""B3 through the API, with real ffmpeg on tiny generated clips: presets
(three defaults on first use, CRUD, checks), pre-flight (stages and the
project check's warnings), one export of videos x presets under one parent
job, files named by the pattern at the platform's frame and the loudness
target, a failed render tried once more then Failed with its reason while
the rest finish, videos moved to Exported, a zip of the files, and a share
link that lists and serves them with no account."""
import io
import zipfile

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, export_engine, flags, jobs, repo
from app.media import ffmpeg
from app.render import deliver
from app.store import stages
from app.store.actors import user
from tests.api.test_folders import upload_into
from tests.render.test_deliver import clip
from tests.factories import media_get

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


def project_with(client, path, names):
    client.post("/projects", json={"name": "Diwali Sale"})
    for n in names:
        assert upload_into(client, path, "f1", name=n).status_code in (200, 201)


def finished(client, export_id):
    export_engine.wait(export_id, timeout=120)
    return client.get(f"/projects/f1/exports/{export_id}").json()


def presets_by_name(client):
    return {p["name"]: p for p in client.get("/projects/f1/export-presets").json()["presets"]}


def test_presets_start_with_three_defaults_and_are_changed_with_checks(client):
    client.post("/projects", json={"name": "Spring"})
    body = client.get("/projects/f1/export-presets").json()
    assert [(p["name"], p["platform"], p["loudness"], p["codec"], p["captions"]) for p in body["presets"]] == [
        ("YouTube 16:9", "youtube", -14.0, "h264", False), ("Reels 9:16", "reels", -14.0, "h264", False),
        ("Feed 1:1", "feed", -14.0, "h264", False)]
    assert body["presets"][0]["pattern"] == "{project}_{video}_{lang}_{preset}_v{version}"
    assert [c["id"] for c in body["codecs"]] == ["h264", "hevc"] and [x["lufs"] for x in body["loudness"]] == [-14.0, -16.0, -24.0]
    made = client.post("/projects/f1/export-presets", json={"name": "TV spot", "platform": "youtube", "loudness": -24, "captions": True})
    assert made.status_code == 201 and made.json()["loudness"] == -24.0 and made.json()["captions"] is True
    pid = made.json()["preset_id"]
    changed = client.patch(f"/projects/f1/export-presets/{pid}", json={"pattern": "{video}-{preset}"})
    assert changed.status_code == 200 and changed.json()["pattern"] == "{video}-{preset}" and changed.json()["loudness"] == -24.0
    for bad, words in [({"pattern": "{client}_{video}"}, "can use"), ({"pattern": "{project}"}, "{video}"),
                       ({"loudness": -20}, "Loudness"), ({"name": "  "}, "name")]:
        resp = client.patch(f"/projects/f1/export-presets/{pid}", json=bad)
        assert resp.status_code == 422 and words in resp.json()["detail"], (bad, resp.text)
    for p in client.get("/projects/f1/export-presets").json()["presets"]:
        assert client.delete(f"/projects/f1/export-presets/{p['preset_id']}").status_code == 204
    assert client.get("/projects/f1/export-presets").json()["presets"] == []     # deleted stay deleted
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert {"export_preset.added", "export_preset.changed", "export_preset.removed"} <= set(verbs)
    flags.set("projects.batch", "local", False)
    assert client.get("/projects/f1/export-presets").status_code == 404
    assert client.get("/projects/f1/exports/preflight").status_code == 404


def test_export_flow_files_stages_zip_and_share(client, sample_video):
    project_with(client, sample_video, ["bhaji cam.mp4", "offer.mp4"])
    stages.move(main.database, "p1", "approved", user("local"))
    pre = client.get("/projects/f1/exports/preflight").json()
    assert [(v["video_id"], v["stage"], v["approved"]) for v in pre["videos"]] == [("p1", "approved", True), ("p2", "draft", False)]
    assert isinstance(pre["warnings"], list)
    by = presets_by_name(client)
    started = client.post("/projects/f1/exports", json={"video_ids": ["p1", "p2"], "preset_ids": [by["YouTube 16:9"]["preset_id"], by["Reels 9:16"]["preset_id"]]})
    assert started.status_code == 201, started.text
    eid = started.json()["export_id"]
    assert started.json()["counts"]["total"] == 4
    body = finished(client, eid)
    assert body["phase"] == "finished" and body["counts"] == {"total": 4, "ready": 4, "failed": 0}
    names = sorted(f["file"]["name"] for f in body["files"])
    assert names == ["Diwali-Sale_bhaji-cam_en_Reels-9-16_v1.mp4", "Diwali-Sale_bhaji-cam_en_YouTube-16-9_v1.mp4",
                     "Diwali-Sale_offer_en_Reels-9-16_v1.mp4", "Diwali-Sale_offer_en_YouTube-16-9_v1.mp4"]
    reels = next(f for f in body["files"] if f["preset"]["platform"] == "reels" and f["video_id"] == "p1")
    assert reels["file"]["report"]["framing"].startswith("Letterboxed") and (reels["file"]["report"]["width"], reels["file"]["report"]["height"]) == (1080, 1920)
    assert {f["approved"] for f in body["files"] if f["video_id"] == "p2"} == {False}         # flagged, still exported
    # One parent job keyed by the project, one child per file in its video's slot.
    parent = main.activity.get(eid)
    assert parent.kind == "export" and parent.status == "done" and parent.detail["batch_export"] and parent.step_label == "4 of 4 files ready"
    assert {main.activity.get(f["job_id"]).detail["parent_id"] for f in body["files"]} == {eid}
    assert stages.current(main.database, "p1") == "exported" and stages.current(main.database, "p2") == "exported"
    one = media_get(client, f"/projects/f1/exports/{eid}/files/{reels['index']}?download=true")
    assert one.status_code == 200 and one.headers["content-disposition"].startswith("attachment")
    z = media_get(client, f"/projects/f1/exports/{eid}/zip")
    assert z.status_code == 200 and z.headers["content-type"] == "application/zip"
    assert 'filename="Diwali-Sale-export.zip"' in z.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(z.content)) as zf:
        assert sorted(zf.namelist()) == names and zf.testzip() is None
        assert len(zf.read(reels["file"]["name"])) == reels["file"]["size"]
    link = client.post(f"/projects/f1/exports/{eid}/share")
    assert link.status_code == 201 and link.json()["scope"] == "export"
    assert client.get(f"/projects/f1/exports/{eid}").json()["share"]["share_id"] == link.json()["share_id"]
    token = link.json()["url"].split("/#s/")[1]
    shared = client.get(f"/share/{token}").json()
    assert shared["title"] == "Diwali Sale" and sorted(f["name"] for f in shared["files"]) == names
    assert all("path" not in f for f in shared["files"])
    played = client.get(f"/share/{token}/files/{shared['files'][0]['file_id']}")
    assert played.status_code == 200 and played.headers["content-type"] == "video/mp4"
    with zipfile.ZipFile(io.BytesIO(client.get(f"/share/{token}/zip").content)) as zf:
        assert sorted(zf.namelist()) == names
    client.delete(f"/projects/f1/shares/{link.json()['share_id']}")
    assert client.get(f"/share/{token}").status_code == 410 and client.get(f"/share/{token}/zip").status_code == 410
    verbs = [e["verb"] for e in client.get("/projects/f1/events").json()["events"]]
    assert {"export.started", "export.finished", "stage.moved", "share.created", "share.revoked"} <= set(verbs)


def test_a_failed_render_is_tried_once_more_then_failed_with_its_reason(client, sample_video, monkeypatch):
    project_with(client, sample_video, ["a.mp4", "b.mp4", "c.mp4"])
    real = deliver.deliver
    tries: dict[str, int] = {}

    def flaky(src, dest, **kw):
        video = next(v for v in ("p1", "p2", "p3") if f"/{v}/" in str(src))
        tries[video] = tries.get(video, 0) + 1
        if video == "p1" and tries[video] == 1:
            raise RuntimeError("ffmpeg ran out of memory")                    # once: the retry makes it
        if video == "p2":
            raise RuntimeError("the encoder crashed")                        # always: Failed with the reason
        return real(src, dest, **kw)
    monkeypatch.setattr(main.deliver_mod, "deliver", flaky)
    feed = presets_by_name(client)["Feed 1:1"]["preset_id"]
    eid = client.post("/projects/f1/exports", json={"video_ids": ["p1", "p2", "p3"], "preset_ids": [feed]}).json()["export_id"]
    body = finished(client, eid)
    rows = {f["video_id"]: f for f in body["files"]}
    assert rows["p1"]["state"] == "ready" and rows["p1"]["attempts"] == 2 and tries["p1"] == 2
    assert rows["p2"]["state"] == "failed" and rows["p2"]["attempts"] == 2 and tries["p2"] == 2
    assert rows["p2"]["why"] == "The render failed twice. Something went wrong on our end. Nothing was charged. Try again in a minute."   # run 5 item 1: never the encoder's words
    assert main.activity.get(rows["p2"]["job_id"]).error_text == rows["p2"]["why"]
    assert rows["p3"]["state"] == "ready" and tries["p3"] == 1
    assert body["counts"] == {"total": 3, "ready": 2, "failed": 1}
    assert main.activity.get(eid).step_label == "2 of 3 files ready, 1 failed"
    assert stages.current(main.database, "p2") == "draft" and stages.current(main.database, "p3") == "exported"


def test_the_file_lands_within_one_lu_of_the_presets_loudness(client, tmp_path):
    loud = clip(tmp_path, seconds=4.0, volume=0.5)
    project_with(client, loud, ["tone.mp4"])
    made = client.post("/projects/f1/export-presets", json={"name": "Broadcast", "platform": "feed", "loudness": -24, "pattern": "{video}_{preset}"}).json()
    eid = client.post("/projects/f1/exports", json={"video_ids": ["p1"], "preset_ids": [made["preset_id"]]}).json()["export_id"]
    body = finished(client, eid)
    f = body["files"][0]
    assert f["state"] == "ready" and f["file"]["name"] == "tone_Broadcast.mp4"
    path = main._exports_dir("f1", eid) / f["file"]["name"]
    assert abs(deliver.measure(path)["lufs"] - (-24.0)) <= 1.0


def test_requests_that_cannot_run_are_refused(client, sample_video):
    project_with(client, sample_video, ["a.mp4"])
    feed = presets_by_name(client)["Feed 1:1"]["preset_id"]
    assert client.post("/projects/f1/exports", json={"video_ids": [], "preset_ids": [feed]}).status_code == 422
    assert client.post("/projects/f1/exports", json={"video_ids": ["p9"], "preset_ids": [feed]}).status_code == 404
    assert client.post("/projects/f1/exports", json={"video_ids": ["p1"], "preset_ids": [999]}).status_code == 404
    assert client.get("/projects/f1/exports/J999").status_code == 404
    assert client.post("/projects/f1/shares", json={"scope": "export", "target": "J999"}).status_code == 404
    assert client.get("/projects/f1/exports").json() == {"exports": []}


def test_non_latin_captions_without_libass_are_a_warning_before_export(client, sample_video, monkeypatch):
    """9c: a preset that burns in captions, a video whose captions are not in
    Latin letters, and an ffmpeg without libass: the pre-flight and the export
    say the file will be made without captions."""
    import app.api.main as main
    from app.render import captions as captions_mod
    project_with(client, sample_video, ["ad.mp4"])
    reels = presets_by_name(client)["Reels 9:16"]
    preflight = lambda: client.get("/projects/f1/exports/preflight").json()["warnings"]   # noqa: E731
    monkeypatch.setattr(main.deliver_mod, "has_libass", lambda: False)
    monkeypatch.setattr(main, "_caption_passages", lambda vid, rec: [captions_mod.Passage("आज 20% छूट", 0.0, 1.0)])
    assert [w for w in preflight() if w["kind"] == "captions"] == []          # no preset burns captions yet
    client.patch(f"/projects/f1/export-presets/{reels['preset_id']}", json={"captions": True})
    got = [w for w in preflight() if w["kind"] == "captions"]
    assert len(got) == 1 and "libass" in got[0]["message"] and got[0]["places"][0]["filename"] == "ad.mp4"
    assert "\u2014" not in got[0]["message"]
    monkeypatch.setattr(main.deliver_mod, "has_libass", lambda: True)
    assert [w for w in preflight() if w["kind"] == "captions"] == []
    monkeypatch.setattr(main.deliver_mod, "has_libass", lambda: False)
    monkeypatch.setattr(main, "_caption_passages", lambda vid, rec: [captions_mod.Passage("Get 20% off", 0.0, 1.0)])
    assert [w for w in preflight() if w["kind"] == "captions"] == []
