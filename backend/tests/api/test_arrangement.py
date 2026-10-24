"""The arrangement over the API (2026-10-19): the transcript's order is the
playback order, a move is one action and one undo, a moved line plays at its
new place with the room's sound at its old one, and moves made before it
become the arrangement."""
import pytest

from tests.api.test_endpoints import client, generate, project, reset_state, speechless  # noqa: F401
from tests.factories import export_now  # noqa: E402


@pytest.fixture
def three(monkeypatch, project):
    """The test clip as three lines: "Get" 0.0-0.4, "20% off" 0.4-1.3, "today only." 1.3-2.3."""
    import app.api.main as main
    from app.domain.models import Statement, Transcript
    words = main.repo.get("p1").transcript.words
    speechless(monkeypatch, main, Transcript(words=words, statements=(
        Statement("Get", 0.0, 0.4), Statement("20% off", 0.4, 1.3), Statement("today only.", 1.3, 2.3))))
    return main


def starts(body):
    return [(ln["key"], ln["start"]) for ln in body["lines"]]


def test_reordering_plays_the_lines_one_after_another(client, three):
    body = client.put("/videos/p1/arrangement", json={"order": ["L2", "L0", "L1"]}).json()

    assert starts(body) == [("L2", 0.0), ("L0", 1.0), ("L1", 1.4)]
    assert [ln["moved"] for ln in body["lines"]] == [True, True, True]
    assert body["can_undo"] is True
    assert client.get("/videos/p1").json()["messages"][-1]["text"].startswith("Moved line 3 to 0:00")
    # Rendered: each line's old place gets the room's sound, its words play at the new place.
    manifest = export_now(client, "/videos/p1/export").json()       # made by its job (run 4, item 3d), then read
    assert {round(s["start"], 1) for s in manifest["segments"] if s["kind"] == "edited"} == {0.0, 0.4, 1.3}


def test_one_action_is_one_undo(client, three):
    client.put("/videos/p1/arrangement", json={"order": ["L2", "L0", "L1"]})
    client.put("/videos/p1/arrangement", json={"order": ["L2", "L0", "L1"], "pins": {"L2": 0.2}})

    back = client.post("/videos/p1/arrangement/undo").json()
    assert back["arrangement"]["pins"] == {} and starts(back)[0] == ("L2", 0.0)
    back = client.post("/videos/p1/arrangement/undo").json()
    assert starts(back) == [("L0", 0.0), ("L1", 0.4), ("L2", 1.3)] and back["can_undo"] is False
    assert client.post("/videos/p1/arrangement/undo").status_code == 409
    # Back where it was shot: the render is the source again.
    assert [s["kind"] for s in export_now(client, "/videos/p1/export").json()["segments"]] == ["original"]


def test_a_pinned_line_holds_and_the_others_are_pushed_after_it(client, three):
    body = client.put("/videos/p1/arrangement", json={"pins": {"L1": 0.0}}).json()
    by = {ln["key"]: ln for ln in body["lines"]}

    assert by["L1"]["pinned"] and by["L1"]["start"] == 0.0
    assert by["L0"]["pushed_after"] == 0.0 and by["L0"]["start"] == pytest.approx(0.9)


def test_two_pins_at_once_are_refused_with_a_reason(client, three):
    resp = client.put("/videos/p1/arrangement", json={"pins": {"L0": 0.0, "L1": 0.2}})
    assert resp.status_code == 422 and "would play at once" in resp.json()["detail"]


def test_a_run_past_the_end_is_held_unless_trimmed(client, three):
    body = client.put("/videos/p1/arrangement", json={"pins": {"L1": 1.8}}).json()
    assert body["overrun"] > 0 and body["ease_ok"] is True
    held = export_now(client, "/videos/p1/export").json()
    assert held["inserts"], "the last frame holds while the line finishes"

    client.put("/videos/p1/arrangement", json={"pins": {"L1": 1.8}, "end": "trim"})
    trimmed = export_now(client, "/videos/p1/export").json()
    assert not trimmed["inserts"]


def test_a_replacement_travels_with_its_line(client, three):
    take = generate(text="30% off", start=0.4, end=1.3)
    edit_id = client.post("/videos/p1/edits", json={"candidate_id": take["candidate_id"]}).json()["edit_id"]
    body = client.put("/videos/p1/arrangement", json={"order": ["L1", "L0", "L2"]}).json()

    assert body["lines"][0]["key"] == "L1" and body["lines"][0]["replaced_by"] == edit_id
    import app.api.main as main
    edits, _ = main._render_edits("p1", False)
    moved = next(e for e in edits if e.edit_id == "arr-L1-in")
    assert moved.plan.mix == "layer" and moved.audio.sha256 == take["audio"]["sha256"]
    assert edit_id not in {e.edit_id for e in edits}, "the replacement plays at the new place, not the old"


def test_moving_a_kept_replacement_moves_its_line(client, three):
    take = generate(text="30% off", start=0.4, end=1.3)
    edit_id = client.post("/videos/p1/edits", json={"candidate_id": take["candidate_id"]}).json()["edit_id"]

    out = client.post(f"/videos/p1/edits/{edit_id}/move", json={"start": 0.0}).json()

    assert out["pinned"] == "L1" and out["reverted"] is None
    assert [e["reverted"] for e in client.get("/videos/p1").json()["edits"]] == [False]


def test_the_old_shift_endpoint_pins_the_line(client, three):
    out = client.post("/videos/p1/lines/shift", json={"start": 1.3, "end": 2.3, "to": 0.0}).json()
    assert out["key"] == "L2" and out["selection"]["start"] == 0.0
    assert client.get("/videos/p1").json()["edits"] == []
    assert client.get("/videos/p1/arrangement").json()["arrangement"]["pins"] == {"L2": 0.0}


def test_a_shift_made_before_the_arrangement_becomes_it(client, three):
    """p60's case: two shift pairs and a take moved off its line, one row each once migrated."""
    import app.api.main as main
    from app.domain.models import ApprovedEdit, EditPlan, Selection
    record = main.repo.get("p1")
    room = main._room_tone_candidate("p1", record, Selection(1.3, 2.3))
    main.repo.append_edit("p1", ApprovedEdit("e1", room.candidate_id, room.plan, room.audio, room.frames, partner="e2"))
    layer = EditPlan(Selection(0.0, 1.0), "today only.", "original", fit="start", mix="layer")
    main.repo.append_edit("p1", ApprovedEdit("e2", room.candidate_id, layer, room.audio, room.frames, partner="e1"))

    body = client.get("/videos/p1/arrangement").json()

    assert [ln["key"] for ln in body["lines"]][0] == "L2" and body["lines"][0]["start"] == 0.0
    assert [e["reverted"] for e in client.get("/videos/p1").json()["edits"]] == [True, True]
    assert body["can_undo"] is False
