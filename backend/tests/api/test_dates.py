"""Bug 2 (2026-10-19): "1 Jan 1970" on Shared voices — a boolean consent
formatted as a date. One format on the wire: ISO 8601 UTC strings or null,
never numbers or booleans; consent is `consent_granted_at`."""
import json
import re

import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, jobs, repo
from app.store.db import Database
from app.timefmt import CLIP_TIME, is_time_key, to_iso
from tests.api.test_endpoints import generate, upload

CANON = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


def bad_dates(value, path="$"):
    """Every time-like field that is not an ISO string or null, with where it is."""
    out = []
    if isinstance(value, dict):
        for k, v in value.items():
            here = f"{path}.{k}"
            if k in CLIP_TIME:
                continue
            if (is_time_key(k) or k == "consent") and not isinstance(v, (dict, list)):
                if k == "consent" or isinstance(v, (bool, int, float)) or (isinstance(v, str) and not CANON.match(v)):
                    out.append((here, v))
            else:
                out.extend(bad_dates(v, here))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            out.extend(bad_dates(v, f"{path}[{i}]"))
    return out


def test_every_answer_sends_moments_as_iso_strings_or_null(client, sample_video):
    assert upload(client, sample_video).status_code == 200
    take = generate(text="Welcome", start=0.4, end=1.3, mix="layer")
    client.post("/videos/p1/edits", json={"candidate_id": take["candidate_id"]})
    client.post("/videos/p1/export")
    folder = client.post("/projects", json={"name": "Diwali"}).json()
    client.patch("/videos/p1", json={"project_id": folder["project_id"]})
    # One of the owner's voices, then shared into the project.
    main._set_my_voices("local", [{"voice_id": "v1", "name": "Deewar song", "seconds": 15.3, "at": main._now(), "kind": "recorded",
                                   "sample_sha": None, "description": None, "consent_granted_at": main._now()}])
    shared = client.post(f"/projects/{folder['project_id']}/voices", json={"voice_id": "v1"})
    assert shared.status_code == 201, shared.text
    answers = {
        "video": client.get("/videos/p1").json(),
        "videos": client.get("/videos").json(),
        "folders": client.get("/projects").json(),
        "folder": client.get(f"/projects/{folder['project_id']}").json(),
        "voices": client.get("/voices").json(),
        "usage": client.get("/usage?period=all").json(),
        "video usage": client.get("/videos/p1/usage").json(),
        "receipt": client.get("/videos/p1/receipt").json(),
        "messages": client.get("/videos/p1/messages?after=0").json(),
        "renders": client.get("/videos/p1/renders").json(),
        "consent": client.post("/videos/p1/consent").json(),
        "settings": client.get("/me/settings").json(),
    }
    problems = {name: bad_dates(body) for name, body in answers.items() if bad_dates(body)}
    assert problems == {}
    voice = answers["folder"]["voices"][0]
    assert voice["name"] == "Deewar song" and voice["consent_granted_at"].endswith("Z") and "consent" not in voice
    assert answers["video"]["consent_granted_at"].endswith("Z") and "consent" not in answers["video"]


def test_the_schema_check_itself_catches_numbers_booleans_and_other_forms():
    assert bad_dates({"at": 1729350000}) == [("$.at", 1729350000)]
    assert bad_dates({"voices": [{"consent": True}]}) == [("$.voices[0].consent", True)]
    assert bad_dates({"created_at": "2026-10-19T14:32:05.123456+00:00"}) != []
    assert bad_dates({"created_at": None, "frames": [{"at": 1.5}], "at": "2026-10-19T14:32:05.123Z"}) == []


def test_to_iso_reads_every_form_a_moment_was_stored_in_and_never_invents_1970():
    assert to_iso("2026-10-19T14:32:05.123456+00:00") == "2026-10-19T14:32:05.123Z"
    assert to_iso("2026-10-19T20:02:05+05:30") == "2026-10-19T14:32:05.000Z"
    assert to_iso(1760884325) == "2025-10-19T14:32:05.000Z"          # seconds
    assert to_iso(1760884325123) == "2025-10-19T14:32:05.123Z"       # milliseconds
    for nothing in (None, True, False, 0, -5, "", "yes", "true"):
        assert to_iso(nothing) is None


def test_the_backfill_rewrites_old_rows_and_turns_a_boolean_consent_into_a_marked_moment(tmp_path):
    path = tmp_path / "old.db"
    db = Database(path)
    c = db._conn
    c.execute("DELETE FROM meta WHERE key = 'times_v2'")      # an old database, never backfilled
    c.execute("INSERT INTO videos (id, owner, created_at, source, transcript, consent_at) VALUES ('p1', 'local', '2026-10-19T16:14:20.085114+00:00', '{}', '{}', '2026-10-19T16:15:41.042+00:00')")
    c.execute("INSERT INTO messages (project_id, seq, role, text, at) VALUES ('p1', 1, 'user', 'hi', '2026-10-19T16:15:41.042000+00:00')")
    c.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("my_voices:local", json.dumps([
        {"voice_id": "v1", "name": "Deewar song", "kind": "recorded", "at": "2026-10-19T16:09:46.615209+00:00"}])))
    c.execute("INSERT INTO meta (key, value) VALUES (?, ?)", ("project_voices:f1", json.dumps([
        {"voice_id": "v1", "name": "Deewar song", "kind": "recorded", "at": "2026-10-19T16:10:24.983155+00:00", "consent": True},
        {"voice_id": "v2", "name": "Narrator", "kind": "designed", "at": "2026-10-19T16:11:00+00:00", "consent": True},
        {"voice_id": "v3", "name": "Clone", "kind": "cloned", "at": 0, "consent": False}])))
    again = Database(path)
    c = again._conn
    assert again.migrated_times > 0
    assert c.execute("SELECT created_at, consent_at FROM videos").fetchone()[:] == ("2026-10-19T16:14:20.085Z", "2026-10-19T16:15:41.042Z")
    assert c.execute("SELECT at FROM messages").fetchone()[0] == "2026-10-19T16:15:41.042Z"
    mine = json.loads(c.execute("SELECT value FROM meta WHERE key = 'my_voices:local'").fetchone()[0])[0]
    assert mine["consent_granted_at"] == "2026-10-19T16:09:46.615Z" and mine["consent_approximate"] is True
    shared = json.loads(c.execute("SELECT value FROM meta WHERE key = 'project_voices:f1'").fetchone()[0])
    assert all("consent" not in e for e in shared)
    # The shared voice takes its owner's moment; marked approximate, never 0.
    assert shared[0]["consent_granted_at"] == "2026-10-19T16:09:46.615Z" and shared[0]["consent_approximate"] is True
    assert shared[1]["consent_granted_at"] == "2026-10-19T16:11:00.000Z"
    assert shared[2]["consent_granted_at"] is None and shared[2]["at"] is None
    assert "1970" not in json.dumps(shared)
    assert Database(path).migrated_times == 0                   # once only
