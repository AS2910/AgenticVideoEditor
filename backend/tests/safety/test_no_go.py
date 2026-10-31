"""Voice consent V1, step 5: the public-figure block on clone and the no-go list's
admin routes. The speaker model is faked (`no_go.embed` returns a vector picked
per test, so the score against an entry at [1, 0] is exactly the one asked for);
the vendor is the mock. `voices.cloning_verified` is on for `local`
(tests/safety/conftest.py)."""
import json
import math

import pytest

import app.api.main as main
from app import admin
from app.api.main import database, flags, repo
from app.domain.models import Selection
from app.media import ffmpeg
from app.safety import voice_guard as vg
from app.safety.no_go import NoGoError
from app.safety.voice_guard import NoGoVerdict, VoiceGuardError
from tests.api.test_endpoints import WORDS

pytestmark = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")

G = main.voice_guard
N = main.no_go
H = {"X-Requested-With": "voltage"}
SPEAKER = "_"          # the canned clip's one voice is the whole clip's


def _scoring(monkeypatch, score):
    """The speaker model, faked: every clip's vector scores `score` against an entry at [1, 0]."""
    vector = None if score is None else [score, math.sqrt(max(0.0, 1 - score * score))]
    calls = []
    monkeypatch.setattr(N, "embed", lambda path: calls.append(path) or vector)
    return calls


def _entry(name="A. Famous Person"):
    return N.add(name=name, reason="public figure", embedding=[1.0, 0.0], added_by="admin", source="upload", source_ref="x.wav")


@pytest.fixture()
def video(client, sample_video, monkeypatch):
    with open(sample_video, "rb") as f:
        assert client.post("/videos", files={"file": ("ad.mp4", f, "video/mp4")}, data={"consent": "true"}).status_code == 200
    monkeypatch.setattr(main.clones, "_min", 0.5)
    with database.tx() as c:                                        # the speaker's consent check passed
        c.execute("INSERT INTO liveness_attempts (id, owner, video_id, speaker, sentence, status, provider, method, created_at) "
                  "VALUES ('cv_1', 'local', 'p1', NULL, 'x', 'passed', 'verified', 'verified', ?)", (main._now(),))
    made = []
    real = main.voice.inner.create_clone
    monkeypatch.setattr(main.voice.inner, "create_clone", lambda name, ref: made.append(name) or real(name, ref))
    return made


def _clone_speaker():
    record = repo.get("p1")
    label = next(iter({w.speaker for w in record.transcript.words if w.speaker} or {None}))
    return main._voice_for("p1", record, Selection(*WORDS), "mock", label)


def _refused() -> VoiceGuardError:
    with pytest.raises(VoiceGuardError) as caught:
        _clone_speaker()
    return caught.value


def _rows(table):
    with database.tx() as c:
        return [dict(r) for r in c.execute(f"SELECT * FROM {table} ORDER BY created_at, id")]


# ── on clone ─────────────────────────────────────────────────────────────────

def test_the_list_starts_empty_and_an_empty_list_needs_no_model(client, video, monkeypatch):
    assert client.get("/admin/no-go-voices").json()["voices"] == []
    calls = _scoring(monkeypatch, 0.99)
    G.attest("local", "p1", SPEAKER, "my_voice", vg.STATEMENT_VERSION)
    assert _clone_speaker().cloned and video
    assert calls == [] and _rows("no_go_checks") == []                  # nothing to compare: no model, no row


def test_a_no_go_voice_at_or_above_092_cannot_be_cloned(video, monkeypatch):
    entry = _entry()
    _scoring(monkeypatch, 0.95)
    err = _refused()
    assert (err.code, err.data["reason"], err.status) == ("clone_not_allowed", "no_go", 403)
    assert err.message == vg.REASONS["no_go_voice"] and "match" not in err.data     # the entry is never named
    assert video == []                                                              # nothing reached the vendor
    [row] = _rows("no_go_checks")
    assert (row["verdict"], row["how"], row["no_go_id"], row["owner"], row["video_id"]) == ("block", "voice", entry["id"], "local", "p1")
    assert row["score"] == pytest.approx(0.95) and json.loads(row["scores"])[0]["id"] == entry["id"]
    _scoring(monkeypatch, 0.92)
    assert _refused().data["reason"] == "no_go"                                     # 0.92 itself blocks


def test_below_084_the_clone_continues_and_is_logged(video, monkeypatch):
    _entry()
    _scoring(monkeypatch, 0.80)
    G.attest("local", "p1", SPEAKER, "my_voice", vg.STATEMENT_VERSION)
    assert _clone_speaker().cloned and len(video) == 1
    [row] = _rows("no_go_checks")
    assert row["verdict"] == "pass" and row["score"] == pytest.approx(0.80)


def test_084_to_092_waits_for_review_then_approve_lets_it_through(client, video, monkeypatch):
    entry = _entry()
    _scoring(monkeypatch, 0.88)
    err = _refused()
    assert (err.data["reason"], err.message) == ("no_go_review", vg.REASONS["no_go_review"]) and video == []
    hold_id = err.data["hold_id"]
    assert _refused().data["hold_id"] == hold_id                                    # a retry waits on the same hold
    G.attest("local", "p1", SPEAKER, "my_voice", vg.STATEMENT_VERSION)
    assert _refused().data["reason"] == "no_go_review"

    queue = client.get("/admin/no-go-holds").json()
    assert queue["waiting"] == 1
    [item] = queue["items"]
    assert (item["id"], item["no_go_id"], item["owner"], item["status"]) == (hold_id, entry["id"], "local", "waiting")
    assert item["score"] == pytest.approx(0.88) and item["has_audio"] and "audio_path" not in item
    assert client.get(f"/admin/no-go-holds/{hold_id}/audio").status_code == 200
    kept = N.hold(hold_id)["audio_path"]

    assert client.post(f"/admin/no-go-holds/{hold_id}", json={"decision": "approve", "reason": ""}, headers=H).status_code == 422
    done = client.post(f"/admin/no-go-holds/{hold_id}", json={"decision": "approve", "reason": "Different person"}, headers=H)
    assert done.status_code == 200 and done.json()["status"] == "approved"
    assert not __import__("pathlib").Path(kept).exists()                            # the clip goes once decided
    assert client.get(f"/admin/no-go-holds/{hold_id}/audio").status_code == 404
    assert client.post(f"/admin/no-go-holds/{hold_id}", json={"decision": "reject", "reason": "again"}, headers=H).status_code == 409
    [audit] = admin.recent_audit(database, 1, target="local")
    assert audit["action"] == "no_go_approve" and audit["reason"] == "Different person" and audit["details"]["hold_id"] == hold_id
    with database.tx() as c:
        told = c.execute("SELECT title FROM notifications WHERE recipient = 'local' AND kind = 'consent_decided'").fetchall()
    assert any("you can clone" in r["title"] for r in told)

    assert _clone_speaker().cloned and len(video) == 1                              # the clone goes through now
    assert [r["verdict"] for r in _rows("no_go_checks")][-1] == "pass"
    assert _rows("no_go_checks")[-1]["how"] == "approved"


def test_084_to_092_rejected_cannot_be_cloned(client, video, monkeypatch):
    _entry()
    _scoring(monkeypatch, 0.86)
    hold_id = _refused().data["hold_id"]
    done = client.post(f"/admin/no-go-holds/{hold_id}", json={"decision": "reject", "reason": "It is them"}, headers=H)
    assert done.json()["status"] == "rejected"
    err = _refused()
    assert (err.data["reason"], err.message) == ("no_go", vg.REASONS["no_go_voice"]) and video == []
    assert client.get("/admin/no-go-holds?status=decided").json()["items"][0]["decided_by"] == "local"
    assert admin.recent_audit(database, 1, target="local")[0]["action"] == "no_go_reject"


def test_an_unmeasured_voice_is_held_when_the_list_is_not_empty(video, monkeypatch):
    _entry()
    _scoring(monkeypatch, None)                                                     # no speaker model here
    err = _refused()
    assert err.data["reason"] == "no_go_review"
    hold = N.hold(err.data["hold_id"])
    assert hold["no_go_id"] is None and _rows("no_go_checks")[0]["how"] == "unmeasured"


def test_the_name_list_still_blocks(video):
    figure = main.public_figures.figures[0]
    with pytest.raises(VoiceGuardError) as caught:
        G.can_clone("local", "p1", SPEAKER, figure)
    assert caught.value.data["reason"] == "no_go" and caught.value.data["match"] == figure
    assert _rows("no_go_checks")[0]["how"] == "name"


def test_an_uploaded_recording_is_checked_by_its_audio(video, monkeypatch, tmp_path):
    _entry()
    _scoring(monkeypatch, 0.9)
    wav, _ = ffmpeg.generate_tone(tmp_path / "me.wav", 4.0, 220)
    with pytest.raises(VoiceGuardError) as caught:
        G.check_no_go("local", None, None, "My voice", wav)
    assert caught.value.data["reason"] == "no_go_review"
    assert N.hold(caught.value.data["hold_id"])["subject"].startswith("audio:")


def test_a_vendor_check_can_be_plugged_in_for_v2(video, monkeypatch):
    class Vendor:
        name = "vendor"

        def check(self, reference):
            return NoGoVerdict("block", "Someone Known", 0.97, "vendor")
    monkeypatch.setattr(N, "vendor", Vendor())
    assert _refused().data["reason"] == "no_go" and _rows("no_go_checks")[0]["how"] == "vendor"


def test_an_admin_never_decides_their_own_clone_when_sign_in_is_on(video, monkeypatch):
    _entry()
    _scoring(monkeypatch, 0.88)
    hold_id = _refused().data["hold_id"]
    with pytest.raises(NoGoError) as caught:
        N.decide(hold_id, approve=True, reason="mine", who="local")
    assert caught.value.status == 403


def test_with_the_flag_off_nothing_is_compared(video, monkeypatch):
    flags.set("voices.cloning_verified", "local", False)
    flags.set("voices.cloning", "local", True)                      # today's admin-opened cloning
    _entry()
    calls = _scoring(monkeypatch, 0.99)
    assert _clone_speaker().cloned and len(video) == 1
    assert calls == [] and _rows("no_go_checks") == [] and _rows("no_go_holds") == []


# ── the admin routes ─────────────────────────────────────────────────────────

def test_an_admin_adds_a_voice_from_a_clip_and_removes_it_with_a_reason(client, video, monkeypatch, tmp_path):
    _scoring(monkeypatch, 1.0)
    clip, _ = ffmpeg.generate_tone(tmp_path / "figure.wav", 4.0, 330)
    form = {"name": "A. Famous Person", "reason": "Public figure, flagged by counsel"}
    assert client.post("/admin/no-go-voices", data={**form, "reason": ""}, files={"file": ("f.wav", clip.read_bytes(), "audio/wav")},
                       headers=H).status_code == 422
    added = client.post("/admin/no-go-voices", data=form, files={"file": ("f.wav", clip.read_bytes(), "audio/wav")}, headers=H)
    assert added.status_code == 201, added.text
    entry = added.json()
    assert (entry["name"], entry["source"], entry["source_ref"], entry["dims"]) == ("A. Famous Person", "upload", "f.wav", 2)
    assert entry["model"] == main.no_go.model and "reference_embedding" not in entry
    listed = client.get("/admin/no-go-voices").json()
    assert [v["id"] for v in listed["voices"]] == [entry["id"]] and (listed["block_at"], listed["review_from"]) == (0.92, 0.84)
    [audit] = admin.recent_audit(database, 1, target=entry["id"])
    assert audit["action"] == "no_go_add" and audit["details"]["source"] == "upload"

    _scoring(monkeypatch, 0.88)
    hold_id = _refused().data["hold_id"]                                            # a clone waits on it
    assert client.request("DELETE", f"/admin/no-go-voices/{entry['id']}", json={"reason": ""}, headers=H).status_code == 422
    gone = client.request("DELETE", f"/admin/no-go-voices/{entry['id']}", json={"reason": "Added by mistake"}, headers=H)
    assert gone.status_code == 200 and gone.json()["holds_closed"] == 1
    assert client.get("/admin/no-go-voices").json()["voices"] == [] and N.hold(hold_id)["status"] == "closed"
    [audit] = admin.recent_audit(database, 1, target=entry["id"])
    assert (audit["action"], audit["reason"], audit["details"]["name"]) == ("no_go_remove", "Added by mistake", "A. Famous Person")
    assert client.request("DELETE", f"/admin/no-go-voices/{entry['id']}", json={"reason": "again"}, headers=H).status_code == 404


def test_an_admin_adds_a_voice_from_a_reported_export(client, video, monkeypatch, tmp_path):
    _scoring(monkeypatch, 1.0)
    export, _ = ffmpeg.generate_tone(tmp_path / "export.wav", 8.0, 330)
    with database.tx() as c:
        c.execute("INSERT INTO provenance_marks (mark, owner, video_id, file, sha256, manifest, created_at) "
                  "VALUES ('0123456789abcdef', 'local', 'p1', ?, 'x', '{}', ?)", (str(export), main._now()))
        report = c.execute("INSERT INTO abuse_reports (location, kind, details, created_at) VALUES (?, 'public_figure', ?, ?)",
                           ("https://example.com/v.mp4", "mark 0123456789ABCDEF", main._now())).lastrowid
    by_report = client.post("/admin/no-go-voices", data={"name": "Reported voice", "reason": "Abuse report",
                                                         "abuse_report_id": str(report), "start": "1", "end": "6"}, headers=H)
    assert by_report.status_code == 201, by_report.text
    assert by_report.json()["source"] == "export" and by_report.json()["seconds"] == pytest.approx(5.0, abs=0.2)
    assert f"report #{report}" in by_report.json()["source_ref"]
    assert client.post("/admin/no-go-voices", data={"name": "x", "reason": "short", "mark": "0123456789abcdef", "start": "0",
                                                    "end": "1"}, headers=H).status_code == 422          # too little of the voice
    assert client.post("/admin/no-go-voices", data={"name": "x", "reason": "none", "mark": "ffffffffffffffff"},
                       headers=H).status_code == 404
    _scoring(monkeypatch, None)
    assert client.post("/admin/no-go-voices", data={"name": "x", "reason": "no model", "mark": "0123456789abcdef"},
                       headers=H).status_code == 503


def test_the_admin_routes_are_admins_only(client, video, monkeypatch):
    monkeypatch.setattr(main, "_admin_or_404", lambda request: (_ for _ in ()).throw(main.HTTPException(status_code=404)))
    assert client.get("/admin/no-go-voices").status_code == 404
    assert client.get("/admin/no-go-holds").status_code == 404
