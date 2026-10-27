"""Run 5 item 7: the voice A/B page. Blind order per admin, votes kept, revealed after voting."""
import json

import pytest
from fastapi.testclient import TestClient

from app import analytics_api, voice_ab
from app.api.main import app, database

H = {"X-Requested-With": "voltage"}
RUN = "20261027T000000Z-test"


@pytest.fixture()
def runs(tmp_path, monkeypatch):
    monkeypatch.setenv("AVE_VOICE_AB_DIR", str(tmp_path))
    d = tmp_path / RUN
    d.mkdir()
    for name in ("t1-original.wav", "t1-old.wav", "t1-new.wav"):
        (d / name).write_bytes(b"RIFF" + name.encode())
    (d / "trials.json").write_text(json.dumps({"clip": "story", "trials": [{
        "id": "t1", "speaker": "A", "before": "That summer day", "after": "That spring day", "start": 1.0, "end": 2.0,
        "files": {"original": "t1-original.wav", "old": "t1-old.wav", "new": "t1-new.wav"},
        "scores": {"old": {"sim_o": 0.7}, "new": {"sim_o": 0.8}},
    }]}))
    (tmp_path / "not-a-run").mkdir()
    with database.tx() as c:
        c.execute("DELETE FROM voice_ab_votes")
    return tmp_path


def test_the_order_is_blind_but_steady_per_person():
    seen = {voice_ab.first(RUN, f"t{i}", "ada") for i in range(20)}
    assert seen == {"old", "new"}                                       # both orders happen
    assert voice_ab.first(RUN, "t1", "ada") == voice_ab.first(RUN, "t1", "ada")
    assert voice_ab.method_of(RUN, "t1", "ada", "a") != voice_ab.method_of(RUN, "t1", "ada", "b")


def test_a_trial_is_blind_until_voted_then_revealed_and_tallied(runs):
    client = TestClient(app)
    page = client.get("/admin/voice-ab").json()
    assert page["run"] == RUN and page["runs"] == [RUN]
    [t] = page["trials"]
    assert t["voted"] is False and "scores" not in t and "a_is" not in t
    a_is = voice_ab.first(RUN, "t1", "local")
    a = client.get(f"/admin/voice-ab/{RUN}/t1/a")
    assert a.status_code == 200 and a.content == b"RIFF" + f"t1-{a_is}.wav".encode()
    assert client.get(f"/admin/voice-ab/{RUN}/t1/original").status_code == 200
    assert client.post(f"/admin/voice-ab/{RUN}/t1/vote", json={"choice": "maybe"}, headers=H).status_code == 422
    out = client.post(f"/admin/voice-ab/{RUN}/t1/vote", json={"choice": "a"}, headers=H).json()
    [t] = out["trials"]
    assert t["voted"] and t["choice"] == "a" and t["a_is"] == a_is and t["scores"]["new"]["sim_o"] == 0.8
    assert out["tally"][a_is] == 1 and out["voters"] == 1
    # Changing one's mind replaces the vote.
    out = client.post(f"/admin/voice-ab/{RUN}/t1/vote", json={"choice": "same"}, headers=H).json()
    assert out["tally"] == {"old": 0, "new": 0, "same": 1}


def test_names_come_from_the_folder_never_the_request(runs):
    client = TestClient(app)
    assert client.get(f"/admin/voice-ab/{RUN}/t1/old").status_code == 404           # only original, a, b
    assert client.get(f"/admin/voice-ab/{RUN}/t9/a").status_code == 404
    assert client.get("/admin/voice-ab/not-a-run/t1/a").status_code == 404
    assert client.get("/admin/voice-ab/..%2F..%2Fetc/t1/a").status_code == 404
    assert client.post("/admin/voice-ab/nope/t1/vote", json={"choice": "a"}, headers=H).status_code == 404


def test_no_runs_is_an_empty_page(tmp_path, monkeypatch):
    monkeypatch.setenv("AVE_VOICE_AB_DIR", str(tmp_path / "none"))
    assert TestClient(app).get("/admin/voice-ab").json()["trials"] == []


def test_only_admins_see_it(runs, monkeypatch):
    monkeypatch.setattr(analytics_api, "is_admin", lambda user: False)
    client = TestClient(app)
    assert client.get("/admin/voice-ab").status_code == 404
    assert client.get(f"/admin/voice-ab/{RUN}/t1/a").status_code == 404
    assert client.post(f"/admin/voice-ab/{RUN}/t1/vote", json={"choice": "a"}, headers=H).status_code == 404


def test_a_trial_without_both_methods_is_left_off_the_page(runs):
    data = json.loads((runs / RUN / "trials.json").read_text())
    data["trials"].append({"id": "t2", "before": "x", "after": "y", "start": 0, "end": 1,
                           "files": {"original": "t1-original.wav", "old": "t1-old.wav", "noref": "t1-new.wav"},
                           "scores": {"old": {}, "noref": {}}})
    (runs / RUN / "trials.json").write_text(json.dumps(data))
    page = TestClient(app).get("/admin/voice-ab").json()
    assert [t["id"] for t in page["trials"]] == ["t1"]
    assert TestClient(app).get(f"/admin/voice-ab/{RUN}/t2/a").status_code == 404
