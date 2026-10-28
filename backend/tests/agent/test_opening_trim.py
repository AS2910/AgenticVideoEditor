"""Cost 1e: the opening view says each thing once (AVE_OPENING_TRIM=1; off by default since run 5)."""
from app import understanding as U
from app.agent.context import UNCHANGED, opening
from tests.agent.conftest import reply, text as said
from tests.api.test_endpoints import _agent_on, client, project, reset_state, send  # noqa: F401


def test_a_motion_peak_on_a_named_beat_is_not_said_twice():
    record = {"beats": [{"at": 2.9, "kind": "motion", "label": "motion peak", "confidence": 0.8},
                        {"at": 2.9, "kind": "visual", "label": "highlight jumps", "confidence": 0.7, "source": "vision"},
                        {"at": 7.0, "kind": "motion", "label": "motion peak", "confidence": 0.8}],
              "read": {}, "signals": {}}
    beats = next(line for line in U.context_lines(record, trim=True) if line.startswith("Beats:"))
    assert beats == "Beats: 2.9 s highlight jumps; 7.0 s motion peak."


def test_known_blocks_become_one_line():
    project = {"name": "Diwali", "brief": "Warm, festive.", "voices": [], "videos": []}
    args = dict(duration=2.3, filename="ad.mp4", speakers=["A"], lines=1, autonomy="draft", spent_usd=0.0,
                ceiling_usd=10.0, turn_usd=1.0, project=project, understanding=["What you see: ad"])
    full, short = opening(None, **args), opening(None, **args, fixed_known=True)
    assert "Brief · Diwali" in full and "What you see: ad" in full and UNCHANGED not in full
    assert "Brief" not in short and "What you see" not in short and UNCHANGED in short
    assert "The clip: ad.mp4" in short and "this turn may spend up to $1.00" in short


def test_the_second_turn_points_back_to_the_first(client, project, monkeypatch):
    from dataclasses import replace
    import app.api.main as main
    scripted = _agent_on(monkeypatch, main, [reply(said("Ready.")), reply(said("Still ready.")), reply(said("Yes."))])
    monkeypatch.setattr(main, "settings", replace(main.settings, opening_trim=True))   # AVE_OPENING_TRIM=1
    send(client, "make it 30% off")
    assert UNCHANGED not in scripted.calls[0]["messages"][-1]["content"][0]["text"]   # nothing fixed to point to yet
    main.repo.set_settings("p1", understanding=U.build({"beats": []}, {"format": "ad"}, ""))
    send(client, "now warmer")
    send(client, "and warmer")
    first = scripted.calls[1]["messages"][-1]["content"][0]["text"]
    second = scripted.calls[2]["messages"][-1]["content"][0]["text"]
    assert UNCHANGED not in first and UNCHANGED in second
