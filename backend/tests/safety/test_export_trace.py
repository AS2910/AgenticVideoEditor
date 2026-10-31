"""Voice consent V1, step 7: the "AI voice" label and the permanent metadata on
every export, Trace on the admin page, and suspend cloning / restore.

Real ffmpeg renders (tiny clips): the tag is in the picture for the first
3 seconds and gone after (a frame diff against the same file unlabelled), at
every export preset and aspect ratio; the export id, Voltage, the time and
"contains AI-generated voice" read back from the container with ffprobe and
from the C2PA stub manifest. Then the plan's checklist through the real routes
with the mock vendor: the Export page's file and a batch export carry the label
(on by default; off when the reminder switched it off) and the metadata with
their export id, Trace lists the voice, its attestation, the export
confirmation, the line checks and the user, and every Trace is audited.
"""
import json
import zipfile
import io
from pathlib import Path

import numpy as np
import pytest

import app.api.main as main
from app import admin
from app.api.main import database, flags, repo
from app.media import ffmpeg
from app.render import deliver, label
from app.safety import provenance
from app.safety import voice_guard as vg
from tests.api.test_endpoints import generate
from tests.factories import export_now, media_get

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")
G = main.voice_guard
H = {"X-Requested-With": "voltage"}
TAG_RATIO = 471 / 192                       # the tag picture's width over its height


def clip(tmp_path, size="640x360", seconds=5.0, name="src.mp4"):
    """A picture with texture (so a re-encode cannot hide a change) and a tone."""
    dest = tmp_path / name
    ffmpeg._run(ffmpeg.FFMPEG, [
        "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"testsrc2=s={size}:r=25", "-f", "lavfi",
        "-i", "sine=frequency=220:sample_rate=48000", "-t", f"{seconds}", "-ac", "2", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(dest)])
    return dest


def size_of(path):
    s = next(s for s in ffmpeg.probe(path)["streams"] if s.get("codec_type") == "video")
    return int(s["width"]), int(s["height"])


def frame_at(path, t):
    w, h = size_of(path)
    raw, _ = ffmpeg.run_capture(["-v", "error", "-ss", f"{t}", "-i", str(path), "-frames:v", "1", "-f", "rawvideo",
                                 "-pix_fmt", "rgb24", "-"], text=False)
    return np.frombuffer(raw, dtype=np.uint8)[: w * h * 3].reshape(h, w, 3).astype(np.int16)


def tag_box(frame):
    """The corner where the tag sits in this frame: (top, bottom, left, right)."""
    tag_h, x, y = label.geometry(*frame)
    return y, y + tag_h, x, x + int(tag_h * TAG_RATIO)


def diff_in_tag(a, b, t, frame=None):
    """Mean absolute difference between two files' frames at `t`, inside the tag's corner."""
    fa, fb = frame_at(a, t), frame_at(b, t)
    top, bottom, left, right = tag_box(frame or size_of(a))
    return float(np.abs(fa[top:bottom, left:right] - fb[top:bottom, left:right]).mean())


def volt_share(path, t, frame=None):
    """How much of the tag's corner is volt (#D7FF3A) at `t`."""
    f = frame_at(path, t)
    top, bottom, left, right = tag_box(frame or size_of(path))
    box = f[top:bottom, left:right]
    volt = (np.abs(box[..., 0] - 0xD7) < 40) & (box[..., 1] > 200) & (box[..., 2] < 120)
    return float(volt.mean())


# ── the tag, drawn with real ffmpeg ──────────────────────────────────────────

def test_the_tag_is_in_the_first_three_seconds_and_gone_after(tmp_path):
    src = clip(tmp_path)
    out = tmp_path / "labelled.mp4"
    label.burn(src, out)
    assert abs(ffmpeg.duration_of(out) - ffmpeg.duration_of(src)) < 0.1
    for t in (0.2, 1.5, 2.8):                                   # there, and volt
        assert diff_in_tag(src, out, t) > 30 and volt_share(out, t) > 0.4, t
    for t in (3.3, 4.5):                                        # gone: only the re-encode's noise is left
        assert diff_in_tag(src, out, t) < 4 and volt_share(out, t) < 0.05, t
    assert any(s.get("codec_type") == "audio" for s in ffmpeg.probe(out)["streams"])   # the sound came along


@pytest.mark.parametrize("frame", [(1920, 1080), (1080, 1920), (1080, 1080), (1280, 720), (640, 360), (360, 640),
                                   (480, 480), (3840, 2160)])
def test_the_tag_is_legible_and_inside_the_frame_at_every_size(frame):
    tag_h, x, y = label.geometry(*frame)
    w, h = frame
    assert tag_h >= 22                                          # its words at least ~12 px tall
    assert tag_h <= 0.06 * min(frame) or tag_h == 22             # small: a corner tag, not a banner
    assert x + tag_h * TAG_RATIO < w * 0.5 and y + tag_h < h * 0.2
    if h >= 1.5 * w:
        assert y >= 0.06 * h - 1                                # below the platform's own top bar on 9:16


@pytest.mark.parametrize("platform", list(deliver.PLATFORMS))
def test_a_preset_file_carries_the_tag_only_when_asked(tmp_path, platform):
    src = clip(tmp_path, size="320x180", seconds=4.0)
    plain, labelled = tmp_path / "plain.mp4", tmp_path / "labelled.mp4"
    deliver.deliver(src, plain, platform=platform)
    report = deliver.deliver(src, labelled, platform=platform, label=True)
    frame = deliver.PLATFORMS[platform]["size"]
    assert report["label"] is True and size_of(labelled) == frame
    assert volt_share(labelled, 1.0) > 0.4 and volt_share(plain, 1.0) < 0.05
    assert volt_share(labelled, 3.5) < 0.05                     # gone after 3 s


# ── the metadata, read back ──────────────────────────────────────────────────

def test_stamp_writes_the_export_metadata_to_the_container_and_the_manifest(tmp_path):
    path = clip(tmp_path, seconds=1.0)
    signer = provenance.FakeSigner(b"k")
    wm = provenance.FakeWatermarker()
    made = provenance.stamp(path, video_id="p1", owner="local", watermarker=wm, signer=signer,
                            export={"export_id": "ve_abc123", "ai_voice": True, "label_on": True})
    tags = provenance.read_tags(path)
    assert tags["voltage_export_id"] == "ve_abc123" and tags["voltage_generator"] == "Voltage"
    assert tags["voltage_ai_voice"] == "contains AI-generated voice" and tags["voltage_created"]
    assert wm.read(path) == made["mark"]                        # the watermark is kept
    signed = json.loads(Path(made["manifest"]).read_text())
    m = signed["manifest"]
    export = next(a["data"] for a in m["assertions"] if a["label"] == "voltage.export")
    assert export == {"export_id": "ve_abc123", "generator": "Voltage", "created": tags["voltage_created"],
                      "ai_voice": "contains AI-generated voice", "label_on": True}
    assert next(a for a in m["assertions"] if a["label"] == "c2pa.ai_generated")["data"]["synthetic_voice"] is True
    assert m["asset"]["sha256"] == made["sha256"] and signer.verify(m, signed["signature"])
    # No cloned voice: the export id, Voltage and the time, and no AI voice line.
    other = clip(tmp_path, seconds=1.0, name="other.mp4")
    made = provenance.stamp(other, video_id="p1", owner="local", watermarker=wm, signer=signer,
                            export={"export_id": "ve_x", "ai_voice": False, "label_on": False})
    assert "voltage_ai_voice" not in provenance.read_tags(other) and provenance.read_tags(other)["voltage_export_id"] == "ve_x"
    m = json.loads(Path(made["manifest"]).read_text())["manifest"]
    assert next(a for a in m["assertions"] if a["label"] == "c2pa.ai_generated")["data"]["synthetic_voice"] is False


def test_without_export_the_stamp_is_as_before(tmp_path):
    path = clip(tmp_path, seconds=1.0)
    made = provenance.stamp(path, video_id="p1", owner="local", watermarker=provenance.FakeWatermarker(),
                            signer=provenance.FakeSigner(b"k"))
    assert not any(k.startswith("voltage_") for k in provenance.read_tags(path))
    labels = [a["label"] for a in json.loads(Path(made["manifest"]).read_text())["manifest"]["assertions"]]
    assert labels == ["c2pa.actions", "c2pa.ai_generated", "voltage.provenance"]


# ── through the routes ───────────────────────────────────────────────────────

@pytest.fixture()
def videos(client, sample_video):
    client.post("/projects", json={"name": "Diwali"})
    for _ in range(2):
        with open(sample_video, "rb") as f:
            made = client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "true", "project_id": "f1"})
        assert made.status_code == 200, made.text
    flags.set("projects.batch", "local", True)
    yield
    flags.clear("projects.batch", "local")


def _cloned(client, video="p1", voice="v-clone"):
    """`video` speaks in a clone of its own speaker, attested, the take added."""
    repo.set_clone(video, "_", voice)
    G.record_voice("local", voice, kind="cloned", scope="video", origin="clone", source_video_id=video,
                   speaker_label="_", speaker_name="Asha")
    main.voice.register_clone(voice)
    G.attest("local", video, voice, "my_voice", vg.STATEMENT_VERSION)
    made = generate(voice_id=voice, project_id=video)
    assert client.post(f"/videos/{video}/edits", json={"candidate_id": made["candidate_id"]}).status_code == 200
    return voice, made["candidate_id"]


def _export_page(client, video="p1", label_on=True):
    asked = client.post(f"/videos/{video}/export", json={"purpose": "export"})
    if asked.status_code == 409 and asked.json()["detail"].get("code") == "export_confirm_required":
        ref = asked.json()["detail"]["export_ref"]
        assert client.post(f"/exports/{ref}/confirm", json={"label_on": label_on}).status_code == 201
    out = export_now(client, f"/videos/{video}/export", json={"purpose": "export"})
    assert out.status_code == 200, out.text
    return out.json()


def test_the_export_page_file_carries_the_label_and_the_metadata_with_its_id(client, videos):
    voice, take = _cloned(client)
    out = _export_page(client)
    prov = out["provenance"]
    assert prov["export_id"].startswith("ve_") and prov["ai_voice"] is True and prov["label_on"] is True
    marked = Path(main.artifacts.find("p1", out["render"]["sha256"]))
    source = Path(main.artifacts.find("p1", prov["source_sha256"]))
    assert volt_share(marked, 1.0) > 0.4 and volt_share(source, 1.0) < 0.05          # the tag, drawn in
    tags = provenance.read_tags(marked)
    assert tags["voltage_export_id"] == prov["export_id"] and tags["voltage_ai_voice"] == provenance.AI_VOICE
    assert main.watermarker.read(marked) == prov["mark"]
    manifest = media_get(client, f"/videos/p1/artifacts/{out['render']['sha256']}/c2pa").json()["manifest"]
    assert next(a for a in manifest["assertions"] if a["label"] == "voltage.export")["data"]["export_id"] == prov["export_id"]
    desc = media_get(client, f"/videos/p1/artifacts/{out['render']['sha256']}/description").text
    assert label.LABEL_LINE in desc and f"Export id: {prov['export_id']}" in desc and "Made with Voltage." in desc
    with database.tx() as c:
        row = dict(c.execute("SELECT * FROM provenance_marks WHERE mark = ?", (prov["mark"],)).fetchone())
    assert row["export_id"] == prov["export_id"] and row["ai_voice"] == 1 and row["label_on"] == 1
    assert json.loads(row["voices"]) == [voice] and json.loads(row["takes"]) == [take] and row["export_attestation_id"]
    assert _export_page(client)["provenance"]["export_id"] == prov["export_id"]     # made once per render


def test_the_label_switched_off_on_the_reminder_leaves_the_picture_but_not_the_metadata(client, videos):
    _cloned(client)
    out = _export_page(client, label_on=False)
    prov = out["provenance"]
    assert prov["label_on"] is False and prov["ai_voice"] is True
    marked = Path(main.artifacts.find("p1", out["render"]["sha256"]))
    assert volt_share(marked, 1.0) < 0.05                                           # no tag
    assert provenance.read_tags(marked)["voltage_ai_voice"] == provenance.AI_VOICE  # the metadata is permanent
    desc = media_get(client, f"/videos/p1/artifacts/{out['render']['sha256']}/description").text
    assert label.LABEL_LINE not in desc and prov["export_id"] in desc


def test_an_export_with_no_cloned_voice_gets_the_metadata_and_no_label(client, videos):
    out = _export_page(client)
    prov = out["provenance"]
    marked = Path(main.artifacts.find("p1", out["render"]["sha256"]))
    tags = provenance.read_tags(marked)
    assert prov["ai_voice"] is False and tags["voltage_export_id"] == prov["export_id"] and "voltage_ai_voice" not in tags
    assert volt_share(marked, 1.0) < 0.05


def test_a_batch_export_carries_the_label_and_the_batch_export_id(client, videos):
    _cloned(client)
    preset = client.post("/projects/f1/export-presets", json={"name": "Reel", "platform": "reels"}).json()
    body = {"video_ids": ["p1", "p2"], "preset_ids": [preset["preset_id"]]}
    asked = client.post("/projects/f1/exports", json=body)
    assert asked.status_code == 409
    assert client.post(f"/exports/{asked.json()['detail']['export_ref']}/confirm", json={}).status_code == 201   # label on by default
    made = client.post("/projects/f1/exports", json=body)
    assert made.status_code == 201, made.text
    export_id = made.json()["export_id"]
    main.export_engine.wait(export_id, timeout=180)
    record = main.export_engine.get(export_id, "f1")
    folder = main._exports_dir("f1", export_id)
    files = {i["video_id"]: folder / i["file"]["name"] for i in record["items"]}
    tags = {v: provenance.read_tags(p) for v, p in files.items()}
    assert tags["p1"]["voltage_export_id"] == export_id == tags["p2"]["voltage_export_id"]
    assert tags["p1"]["voltage_ai_voice"] == provenance.AI_VOICE and "voltage_ai_voice" not in tags["p2"]
    assert volt_share(files["p1"], 1.0) > 0.4 and volt_share(files["p2"], 1.0) < 0.05
    assert label.LABEL_LINE in label.description_path(files["p1"]).read_text()
    assert label.LABEL_LINE not in label.description_path(files["p2"]).read_text()
    zipped = media_get(client, f"/projects/f1/exports/{export_id}/zip")
    names = zipfile.ZipFile(io.BytesIO(zipped.content)).namelist()
    assert len(set(files.values())) == 2                                             # two files, two names
    assert sorted(n for n in names if n.endswith(".txt")) == sorted(p.stem + ".txt" for p in files.values())


def test_with_the_flag_off_the_export_is_unchanged(client, videos):
    flags.set("voices.cloning_verified", "local", False)
    out = _export_page(client)
    assert set(out["provenance"]) == {"sha256", "mark", "source_sha256"}
    marked = Path(main.artifacts.find("p1", out["render"]["sha256"]))
    assert not any(k.startswith("voltage_") for k in provenance.read_tags(marked))
    assert media_get(client, f"/videos/p1/artifacts/{out['render']['sha256']}/description").status_code == 404
    assert G.export_facts("local", "p1") is None


# ── Trace ────────────────────────────────────────────────────────────────────

def test_trace_lists_voice_attestation_line_checks_and_user_and_is_audited(client, videos):
    voice, take = _cloned(client)
    prov = _export_page(client)["provenance"]
    traced = client.get(f"/admin/exports/{prov['export_id']}/trace")
    assert traced.status_code == 200, traced.text
    t = traced.json()
    assert t["found_by"] == "export" and [e["mark"] for e in t["exports"]] == [prov["mark"]]
    [v] = t["voices"]
    assert v["voice_id"] == voice and v["scope"] == "video" and v["source_video_id"] == "p1"
    assert [a["choice"] for a in v["attestations"]] == ["my_voice"]
    [confirmation] = t["export_attestations"]
    assert confirmation["voices_used"] == [voice] and confirmation["label_on"] is True
    [synth] = t["synthesis"]
    assert synth["take_id"] == take and synth["voice_id"] == voice and synth["attestation_id"] == v["attestations"][0]["id"]
    [check] = t["line_checks"]
    assert check["id"] == synth["line_check_id"] and check["verdict"] == "pass"
    [user] = t["users"]
    assert user["owner"] == "local" and user["suspended"] is None and user["limits"] == {"day": 5, "month": 30}
    # By its mark, by the export reminder's reference, and by an abuse report that names the mark.
    assert client.get(f"/admin/exports/{prov['mark']}/trace").json()["found_by"] == "mark"
    by_ref = client.get(f"/admin/exports/{confirmation['export_id']}/trace").json()
    assert by_ref["found_by"] == "confirmation" and [e["mark"] for e in by_ref["exports"]] == [prov["mark"]]
    with database.tx() as c:
        report = c.execute("INSERT INTO abuse_reports (location, kind, details, created_at) VALUES (?, ?, ?, ?)",
                           ("https://x.example/v", "impersonation", f"Not me. File mark {prov['mark']}.", main._now())).lastrowid
    by_report = client.get(f"/admin/exports/{report}/trace").json()
    assert by_report["found_by"] == "abuse_report" and by_report["abuse_report"]["id"] == report
    assert [e["mark"] for e in by_report["exports"]] == [prov["mark"]]
    # Every Trace is in the audit trail, the miss too.
    assert client.get("/admin/exports/nothing-here/trace").status_code == 404
    audit = admin.recent_audit(database, 5)
    assert [a["action"] for a in audit[:5]] == ["voice_trace"] * 5
    assert audit[0]["target"] == "nothing-here" and audit[0]["details"]["found"] is False
    assert audit[-1]["details"]["owners"] == ["local"] and audit[-1]["details"]["marks"] == [prov["mark"]]


def test_trace_is_for_admins_only(client, videos, monkeypatch):
    from fastapi import HTTPException
    import app.admin_api as admin_api

    def refuse(request):
        raise HTTPException(status_code=404, detail="Not found")
    monkeypatch.setattr(admin_api, "_admin", refuse)
    assert client.get("/admin/exports/ve_x/trace").status_code == 404
    assert client.get("/admin/users/local/cloning").status_code == 404


# ── suspend cloning / restore ────────────────────────────────────────────────

def test_suspend_disables_every_cloned_voice_blocks_new_clones_and_restore_needs_a_reason(client, videos):
    voice, _ = _cloned(client)
    G.record_voice("local", "v-mine", kind="recorded", scope="library", origin="upload")
    state = client.get("/admin/users/local/cloning").json()
    assert state["suspended"] is None and state["voices"]["active"] == 2 and state["limits"] == {"day": 5, "month": 30}
    assert state["used"]["day"] == 2
    assert client.post("/admin/users/local/suspend-cloning", json={"reason": "  "}, headers=H).status_code == 422
    done = client.post("/admin/users/local/suspend-cloning", json={"reason": "credible report #7"}, headers=H).json()
    assert done["voices_disabled"] == 2                                              # the uploaded recording too
    state = client.get("/admin/users/local/cloning").json()
    assert state["suspended"]["reason"] == "credible report #7" and state["voices"] == {"active": 0, "suspended": 2, "withdrawn": 0}
    with pytest.raises(vg.VoiceGuardError) as no_clone:
        G.can_clone("local", "p2", "_", "Ravi")
    assert no_clone.value.data["reason"] == "suspended"
    for v in (voice, "v-mine"):
        with pytest.raises(vg.VoiceGuardError) as no_voice:
            G.check_scope(v, "p1", "local")
        assert no_voice.value.code == "voice_unavailable"
    assert client.post("/admin/users/local/restore-cloning", json={"reason": ""}, headers=H).status_code == 422
    assert client.post("/admin/users/local/restore-cloning", headers=H).status_code == 422
    back = client.post("/admin/users/local/restore-cloning", json={"reason": "report was a mistake"}, headers=H).json()
    assert back["voices_restored"] == 2 and client.get("/admin/users/local/cloning").json()["suspended"] is None
    G.check_scope(voice, "p1", "local")
    [restore, suspend] = admin.recent_audit(database, 2, target="local")
    assert (restore["action"], restore["reason"]) == ("voice_restore", "report was a mistake")
    assert (suspend["action"], suspend["details"]) == ("voice_suspend", {"voices_disabled": 2})
