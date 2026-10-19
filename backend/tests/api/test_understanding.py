"""The video as a piece (2026-10-20): the understanding record, corrections, the style line."""
import numpy as np

from tests.api.test_endpoints import _agent_on, client, project, reset_state, send  # noqa: F401
from app import understanding as U
from app.media import understand as M

RATE = 48000


class Looker:
    """A planner stand-in that understands the clip as a boxing bout and says a few things it should not."""
    identity = "claude"

    def __init__(self):
        self.calls = []

    def understand(self, frames, signals, lines, meter=None, brief=""):
        self.calls.append({"frames": [f.at for f in frames], "signals": signals, "brief": brief})
        return {"format": "sports clip", "genre": "boxing bout", "purpose": "a highlight", "audience": "fight fans",
                "setting": "A ring under bright lights.", "subjects": "Two boxers, red and blue, and a referee.",
                "on_screen_text": [], "visual_events": [{"at": 1.2, "label": "knockdown", "confidence": 0.7},
                                                        {"at": 0.4, "label": "Tyson lands a hook", "confidence": 0.6}],
                "audio_notes": "a crowd", "language": "English",
                "summary": "A bout under bright lights. The Las Vegas crowd erupts at 0:01.",
                "style_line": "Ringside commentary: present tense, short phrases, rising to the knockdown at 0:01.",
                "opening": "The knockdown comes at 0:01.", "roles": [], "suggestions": [
                    {"label": "Call the knockdown at 0:01", "prompt": "Add a commentary line for the knockdown at 0:01.", "kind": "add", "grounded_in": "frames"}]}


def test_the_signals_are_read_from_a_real_clip(sample_video):
    sig = M.read_signals(sample_video, 2.3).as_dict()
    assert sig["orientation"] in ("landscape", "vertical", "square") and len(sig["energy"]) == 5
    assert 1 <= len(sig["frame_times"]) <= M.MAX_FRAMES and all(0 <= t <= 2.3 for t in sig["frame_times"])


def test_a_crowd_roar_after_quiet_is_a_beat_with_a_name():
    rng = np.random.default_rng(0)
    quiet = rng.standard_normal((3 * RATE, 1)) * 0.003
    roar = rng.standard_normal((2 * RATE, 1)) * 0.4
    beats = M.audio_events(np.vstack([quiet, roar]))
    assert beats and abs(beats[0].at - 3.0) < 0.5 and beats[0].label == "crowd roar"


def test_frames_follow_the_beats_and_stay_within_24():
    beats = [M.Beat(5.0, "cut", "cut", 0.8), M.Beat(13.0, "audio", "crowd roar", 0.7)]
    times = M.adaptive_frame_times(60.0, beats)
    assert len(times) == 24 and 5.15 in times and 13.0 in times


def test_no_name_survives_unless_it_was_said_shown_or_in_the_brief():
    record = U.build({"beats": []}, Looker().understand([], {}, []), sources="Two boxers in a ring")
    assert "Las Vegas" not in record["read"]["summary"] and record["read"]["summary"] == "A bout under bright lights."
    assert [b["label"] for b in record["beats"]] == ["knockdown"]          # "Tyson" is nowhere: that event goes


def test_the_first_read_builds_the_record_and_the_style_shows_before_the_first_paid_step(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    looker = Looker()
    monkeypatch.setattr(main, "planner", looker)
    reading = client.post("/videos/p1/reading", json={}).json()
    assert reading["opening"] == "The knockdown comes at 0:01." and reading["suggestions"][0]["label"] == "Call the knockdown at 0:01"
    assert looker.calls and looker.calls[0]["frames"]
    seen = client.get("/videos/p1/understanding").json()
    assert seen["version"] == 1 and seen["read"]["genre"] == "boxing bout" and seen["style"]["accepted"] is False
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [reply(said("Ready when you are."))])
    send(client, "add commentary")
    msgs = client.get("/videos/p1").json()["messages"]
    style = next(i for i, m in enumerate(msgs) if m["text"].startswith("Style for this video: Ringside commentary"))
    assert all(m.get("kind") != "step" or m["text"].startswith("Style") or i > style for i, m in enumerate(msgs))
    opening = scripted.calls[0]["messages"][-1]["content"][0]["text"]
    assert "What you see: sports clip, boxing bout" in opening and "knockdown" in opening


def test_a_correction_wins_in_the_next_turn(client, project, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply, text as said
    monkeypatch.setattr(main, "planner", Looker())
    client.post("/videos/p1/reading", json={})
    client.post("/videos/p1/understanding/corrections", json={"text": "This is Muay Thai"})
    out = client.post("/videos/p1/understanding/corrections", json={"text": "That's not a knockdown, he slipped", "beat_at": 1.2, "label": "a slip"}).json()
    assert any(b["label"] == "a slip" and b["source"] == "user" for b in out["beats"])
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    scripted = _agent_on(monkeypatch, main, [reply(said("Noted."))])
    send(client, "add commentary")
    opening = scripted.calls[0]["messages"][-1]["content"][0]["text"]
    assert "The user corrected your read of this video; these win over everything below: This is Muay Thai | That's not a knockdown, he slipped" in opening
    assert "1.2 s a slip (user)" in opening and "1.2 s knockdown" not in opening


def test_the_style_line_can_be_accepted_or_changed(client, project, monkeypatch):
    import app.api.main as main
    monkeypatch.setattr(main, "planner", Looker())
    client.post("/videos/p1/reading", json={})
    out = client.put("/videos/p1/style", json={"line": "Calm, dry commentary, no shouting."}).json()
    assert out["style"] == {"line": "Calm, dry commentary, no shouting.", "accepted": True, "by": "user", "shown": True}
    assert client.put("/videos/p1/style", json={"line": " "}).status_code == 422
    # A new read keeps what the user chose.
    client.post("/videos/p1/reading", json={"again": True})
    assert client.get("/videos/p1/understanding").json()["style"]["line"] == "Calm, dry commentary, no shouting."
