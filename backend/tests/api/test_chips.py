"""The chips above Voltage's box come from this video (2026-10-20)."""
from tests.api.test_endpoints import _agent_on, client, project, reset_state, send, speechless  # noqa: F401


def chip(label, kind, ground, prompt=None):
    return {"label": label, "prompt": prompt or label, "kind": kind, "grounded_in": ground}


def test_without_claude_the_generic_set_by_clip_type(client, project, monkeypatch):
    import app.api.main as main
    out = client.get("/videos/p1/suggestions").json()
    assert out["source"] == "generic" and 3 <= len(out["suggestions"]) <= 4
    assert all(len(c["label"]) <= 40 for c in out["suggestions"])
    from app.domain.models import Transcript
    speechless(monkeypatch, main, Transcript(words=()))
    silent = client.get("/videos/p1/suggestions").json()["suggestions"]
    assert silent[0]["kind"] == "add" and silent[0]["grounded_in"] == "frames"


def test_the_first_read_brings_grounded_chips_and_the_brief_reaches_it(client, project, monkeypatch):
    import app.api.main as main
    from app.orchestrator.planner import Reading
    seen = {}

    class Reader:
        identity = "claude"

        def read(self, lines, meter=None, brief=""):
            seen["brief"] = brief
            return Reading("The offer is said once, at 0:00.", (), (
                chip("Add the 30% Diwali offer", "change", "brief"),
                chip("Say Twenty clearly", "fix", "words"),          # "Twenty" is not said: dropped
                chip("Tighten the line at 0:00", "fix", "time"),
                chip("Welcome everyone to Goa", "add", "frames"),     # nothing names Goa: dropped
            ))

    monkeypatch.setattr(main, "planner", Reader())
    f = client.post("/projects", json={"name": "Festive", "brief": "Diwali sale, 30% off everything."}).json()
    assert client.patch("/videos/p1", json={"project_id": f["project_id"]}).status_code == 200
    reading = client.post("/videos/p1/reading", json={}).json()
    assert seen["brief"] == "Festive: Diwali sale, 30% off everything."
    assert [c["label"] for c in reading["suggestions"]] == ["Add the 30% Diwali offer", "Tighten the line at 0:00"]
    now = client.get("/videos/p1/suggestions").json()
    assert now["source"] == "reading" and len(now["suggestions"]) == 2
    assert client.get("/videos/p1").json()["suggestions"] == now["suggestions"]


def test_a_turn_replaces_the_chips_and_the_user_never_sees_the_block(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    block = '<next>[{"label": "Make line 1 warmer", "prompt": "Voice line 1 again, warmer.", "kind": "voice", "grounded_in": "words"}, {"label": "Export", "prompt": "Export the video.", "kind": "finish", "grounded_in": "time"}]</next>'
    _agent_on(monkeypatch, main, [reply(said("Line 1 is ready to hear.\n" + block))])
    result = send(client, "make it 30% off")
    assert result["reply"] == "Line 1 is ready to hear."
    assert [c["label"] for c in result["suggestions"]] == ["Make line 1 warmer", "Export"]
    assert "<next>" not in client.get("/videos/p1").json()["messages"][-1]["text"]
    assert client.get("/videos/p1/suggestions").json()["source"] == "turn"
    # A turn with no block: the chip just used goes, the others stay.
    _agent_on(monkeypatch, main, [reply(said("Done."))])
    send(client, "Voice line 1 again, warmer.")
    assert [c["label"] for c in client.get("/videos/p1/suggestions").json()["suggestions"]] == ["Export"]


def test_chips_are_never_saved_into_the_conversation_history(client, project, monkeypatch):
    """One edit at a time, part 5: the `<next>` block is in neither the messages nor the stored thread."""
    import json
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    block = '<next>[{"label": "Export", "prompt": "Export the video.", "kind": "finish", "grounded_in": "time"}]</next>'
    _agent_on(monkeypatch, main, [reply(said("Line 1 is ready to hear.\n" + block))])
    result = send(client, "make it 30% off")
    assert [c["label"] for c in result["suggestions"]] == ["Export"]
    assert all("<next>" not in m["text"] and "Export the video." not in m["text"] for m in client.get("/videos/p1").json()["messages"])
    thread = json.dumps(main.repo.turns("p1"))
    assert "<next>" not in thread and "Export the video." not in thread
    assert "Line 1 is ready to hear." in thread


def test_without_next_keeps_a_word_when_only_the_block_was_said():
    from app.agent.suggestions import without_next
    assert without_next("<next>[]</next>") == "Done."
    assert without_next("Ready.\n<next>[]</next>") == "Ready."
    assert without_next("No block here.") == "No block here."
    blocks = [{"type": "thinking", "thinking": "x", "signature": "s"}, {"type": "text", "text": "Ready. <next>[]</next>"}]
    assert without_next(blocks) == [blocks[0], {"type": "text", "text": "Ready."}]


def test_chip_use_is_counted_by_kind(client, project):
    for event in ({"event": "shown", "kind": "fix", "label": "Tighten"}, {"event": "clicked", "kind": "fix"},
                  {"event": "sent", "kind": "fix", "edited": True}, {"event": "sent", "kind": "finish"}):
        assert client.post("/videos/p1/suggestions/events", json=event).status_code == 204
    stats = client.get("/suggestions/stats").json()["by_kind"]
    assert stats["fix"] == {"shown": 1, "clicked": 1, "edited": 1, "sent_as_is": 0}
    assert stats["finish"]["sent_as_is"] == 1
    assert client.post("/videos/p1/suggestions/events", json={"event": "liked", "kind": "fix"}).status_code == 422
