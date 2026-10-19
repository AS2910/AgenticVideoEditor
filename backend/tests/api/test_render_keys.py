"""Bug 1 (2026-10-19): an added line that sometimes played and sometimes did not.

Every render is keyed by (video, mode, edit-set hash); an identical request
reuses the artifact, a changed set renders anew, identical requests in flight
share one render, and the record — not memory — says whether the final render
matches the edits now. Each case below checks the audio itself: the added
line is in the render when it should be, measured by correlation against the
take (as in 20h)."""
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.api.main as main
from app.api.main import app, jobs, repo
from app.domain.models import Selection
from app.domain.plan import Plan, PlanItem
from app.render import compose
from tests.api.test_endpoints import generate, upload

RATE = compose.OUT_RATE
SPAN = (0.4, 1.3)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def video(client, sample_video):
    r = upload(client, sample_video)
    assert r.status_code == 200, r.text
    return r.json()


def _layer(text="Welcome to Goa"):
    """A layered take over SPAN, through the same path the agent uses."""
    return generate(text=text, start=SPAN[0], end=SPAN[1], mix="layer")


def _approve(client, candidate_id):
    r = client.post("/videos/p1/edits", json={"candidate_id": candidate_id})
    assert r.status_code == 200, r.text
    return r.json()


def _path(sha):
    found = main.artifacts.find("p1", sha)
    assert found is not None, sha
    return found


def line_correlation(render_sha: str, take_sha: str, start: float = SPAN[0]) -> float:
    """How strongly the take is present in the render where it should play:
    the correlation of the render's audio there with the take itself."""
    out = compose.decode(_path(render_sha), channels=1)[:, 0]
    take = compose.decode(_path(take_sha), channels=1)[:, 0]
    at = int(start * RATE)
    n = min(len(take), len(out) - at)
    seg, ref = out[at:at + n], take[:n]
    if np.std(seg) < 1e-6 or np.std(ref) < 1e-6:
        return 0.0
    return float(np.corrcoef(seg, ref)[0, 1])


def _plan_with_ready(candidate_id, item_id="i1"):
    plan = Plan(plan_id=repo.next_plan_id("p1"), project_id="p1", goal="g", summary="", status="done", created_at=main._now(),
                items=(PlanItem(item_id=item_id, selection=Selection(*SPAN), old_text="", new_text="Welcome to Goa", mix="layer",
                                status="ready", candidate_id=candidate_id),))
    repo.save_plan(plan)
    return plan


def test_an_identical_request_reuses_the_render_and_a_changed_edit_set_renders_anew(client, video, monkeypatch):
    calls = []
    real = main._render_now
    monkeypatch.setattr(main, "_render_now", lambda *a, **k: calls.append(1) or real(*a, **k))
    take = _layer()
    _approve(client, take["candidate_id"])
    first = client.post("/videos/p1/export").json()
    again = client.post("/videos/p1/export").json()
    assert again["render"]["sha256"] == first["render"]["sha256"] and again["cached"] is True
    assert first["edit_hash"] == again["edit_hash"]
    # _approve rendered once already; the two exports reuse it.
    assert len(calls) == 1
    state = client.get("/videos/p1/renders").json()["final"]
    assert state["edit_hash"] == first["edit_hash"] and state["render"]["sha256"] == first["render"]["sha256"]
    assert line_correlation(first["render"]["sha256"], take["audio"]["sha256"]) > 0.9
    # A layer in another role is a different edit set: a new hash, a new render.
    edit_id = client.get("/videos/p1").json()["edits"][0]["edit_id"]
    client.post(f"/videos/p1/edits/{edit_id}/role", json={"role": "bed", "confirm": True})
    third = client.post("/videos/p1/export").json()
    assert third["edit_hash"] != first["edit_hash"] and third["cached"] is False and len(calls) == 2   # the level change itself does not render


def test_two_overlapping_renders_each_carry_their_own_edit_set_and_the_latest_is_current(client, video, monkeypatch):
    """The older request starts first and is slow; a newer edit lands meanwhile and its render is asked for too.
    Each response names its own hash, and the record's current final render is the newer one — with the line."""
    real = main._render_now
    slow = threading.Event()

    def render_now(record, edits, previewed, proposals):
        if not slow.is_set():
            slow.set()
            time.sleep(0.6)   # the first render is still running when the second request arrives
        return real(record, edits, previewed, proposals)

    monkeypatch.setattr(main, "_render_now", render_now)
    take = _layer()
    results = {}
    old = threading.Thread(target=lambda: results.__setitem__("old", client.post("/videos/p1/export", json={"request_id": 1}).json()))
    old.start()
    slow.wait(2)
    _approve(client, take["candidate_id"])                     # the edit set changes under the running render
    results["new"] = client.post("/videos/p1/export", json={"request_id": 2}).json()
    old.join(5)
    assert results["old"]["request_id"] == 1 and results["new"]["request_id"] == 2
    assert results["old"]["edit_hash"] != results["new"]["edit_hash"]
    current = client.get("/videos/p1/renders").json()["final"]
    assert current["edit_hash"] == results["new"]["edit_hash"]
    assert current["render"]["sha256"] == results["new"]["render"]["sha256"]
    assert line_correlation(results["new"]["render"]["sha256"], take["audio"]["sha256"]) > 0.9
    # The stale one is the original, with no line in it: a client keeping only request 2 is right.
    assert line_correlation(results["old"]["render"]["sha256"], take["audio"]["sha256"]) < 0.3


def test_identical_requests_in_flight_share_one_render(client, video, monkeypatch):
    calls = []
    real = main._render_now

    def render_now(*a, **k):
        calls.append(1)
        time.sleep(0.4)
        return real(*a, **k)

    take = _layer()
    _approve(client, take["candidate_id"])
    monkeypatch.setattr(main, "_render_now", render_now)
    main.repo.set_settings("p1", renders={})                 # forget the approve's render
    out = []
    threads = [threading.Thread(target=lambda: out.append(client.post("/videos/p1/export").json())) for _ in range(3)]
    [t.start() for t in threads]
    [t.join(10) for t in threads]
    assert len(calls) == 1 and len({o["render"]["sha256"] for o in out}) == 1


def test_a_mode_switch_during_a_render_gives_each_mode_its_own_render(client, video, monkeypatch):
    real = main._render_now
    started = threading.Event()

    def render_now(record, edits, previewed, proposals):
        if not proposals:
            started.set()
            time.sleep(0.4)
        return real(record, edits, previewed, proposals)

    monkeypatch.setattr(main, "_render_now", render_now)
    take = _layer()
    _plan_with_ready(take["candidate_id"])                     # proposed, not in the video
    res = {}
    t = threading.Thread(target=lambda: res.__setitem__("final", client.post("/videos/p1/export").json()))
    t.start()
    started.wait(2)
    res["proposals"] = client.post("/videos/p1/export", json={"with_proposals": True}).json()
    t.join(5)
    assert res["final"]["mode"] == "final" and res["proposals"]["mode"] == "proposals"
    assert res["final"]["edit_hash"] != res["proposals"]["edit_hash"]
    assert line_correlation(res["proposals"]["render"]["sha256"], take["audio"]["sha256"]) > 0.9
    assert line_correlation(res["final"]["render"]["sha256"], take["audio"]["sha256"]) < 0.3
    state = client.get("/videos/p1/renders").json()
    assert state["proposals"]["render"]["sha256"] == res["proposals"]["render"]["sha256"]
    assert state["final"]["render"]["sha256"] == res["final"]["render"]["sha256"]


def test_undo_then_re_add_gives_back_the_render_with_the_line(client, video):
    take = _layer()
    first = _approve(client, take["candidate_id"])
    with_line = client.post("/videos/p1/export").json()
    assert line_correlation(with_line["render"]["sha256"], take["audio"]["sha256"]) > 0.9
    client.post(f"/videos/p1/edits/{first['edit_id']}/revert")
    without = client.post("/videos/p1/export").json()
    assert without["edit_hash"] != with_line["edit_hash"]
    assert line_correlation(without["render"]["sha256"], take["audio"]["sha256"]) < 0.3
    _approve(client, take["candidate_id"])
    back = client.post("/videos/p1/export").json()
    # The same edit set as before: the same render, and the line is in it.
    assert back["edit_hash"] == with_line["edit_hash"] and back["render"]["sha256"] == with_line["render"]["sha256"]
    assert line_correlation(back["render"]["sha256"], take["audio"]["sha256"]) > 0.9


def test_an_agent_shipped_edit_then_an_immediate_preview_carries_the_line(client, video):
    take = _layer()
    plan = _plan_with_ready(take["candidate_id"])
    shipped = main._ship("p1", repo.get("p1"), plan.plan_id, ["i1"])     # what the agent's ship tool calls
    assert shipped["approved"] and shipped["export"]
    preview = client.post("/videos/p1/export", json={"with_proposals": True}).json()
    final = client.post("/videos/p1/export").json()
    assert final["cached"] is True and final["render"]["sha256"] == shipped["export"]["render"]["sha256"]
    for r in (shipped["export"], preview, final):
        assert line_correlation(r["render"]["sha256"], take["audio"]["sha256"]) > 0.9
    assert client.get("/videos/p1/renders").json()["final"]["render"] is not None


def test_an_unretimed_hevc_source_is_stream_copied_not_re_encoded(tmp_path, sample_video):
    """The bug's clip was 8K HEVC: copying the picture instead of re-encoding it is what makes renders fast."""
    from app.media import ffmpeg
    hevc = tmp_path / "hevc.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(sample_video), "-c:v", "libx265", "-x265-params", "log-level=error",
                    "-c:a", "copy", "-tag:v", "hvc1", str(hevc)], check=True)
    from app.domain.models import Source
    art = main.artifacts.put_file("hv", hevc, kind="video", container="mp4", duration=ffmpeg.duration_of(hevc))
    source = Source(project_id="hv", filename="hevc.mp4", duration=art.duration, media=art)
    out = compose.compose(source, [], tmp_path / "out.mp4")
    video = next(s for s in ffmpeg.probe(out)["streams"] if s["codec_type"] == "video")
    assert video["codec_name"] == "hevc" and video.get("codec_tag_string") == "hvc1"
