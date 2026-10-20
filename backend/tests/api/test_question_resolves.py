"""A waiting question resolves when its subject changes outside the chat (2026-10-20)."""
from tests.api.test_endpoints import _agent_on, client, project, reset_state, send, take  # noqa: F401
from tests.agent.conftest import reply, text as said, use

ASK = {"question": "How should I handle the middle line?",
       "options": [{"label": "Voice it next turn", "detail": ""}, {"label": "Add the four now", "detail": ""}, {"label": "Let me listen first", "detail": ""}],
       "guess": "Voice it next turn"}


def asked(client, monkeypatch):
    import app.api.main as main
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(take(), stop="tool_use"), reply(use("ask", "a1", **ASK), stop="tool_use")])
    result = send(client, "make it 30% off")
    plan = client.get(f"/videos/p1/plans/{result['plan']['plan_id']}").json()
    assert plan["status"] == "clarifying" and plan["question"]["text"] == ASK["question"]
    return plan


def test_adding_the_line_by_hand_settles_the_question(client, project, monkeypatch):
    plan = asked(client, monkeypatch)
    out = client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i1"]}).json()
    assert out["plan"]["status"] != "clarifying"
    q = out["plan"]["question"]
    assert q["resolved"]["by"] == "editor" and q["resolved"]["why"] == "you added the line"
    assert q["options"] and q["text"] == ASK["question"]          # kept, for the quiet card


def test_discarding_the_line_settles_it_too(client, project, monkeypatch):
    plan = asked(client, monkeypatch)
    out = client.post(f"/videos/p1/plans/{plan['plan_id']}/items/i1/dismiss").json()
    assert out["status"] != "clarifying" and out["question"]["resolved"]["why"].startswith("you discarded the line at")


def test_a_newer_turn_resolves_the_open_question_and_is_no_gate(client, project, monkeypatch):
    import app.api.main as main
    asked(client, monkeypatch)
    _agent_on(monkeypatch, main, [reply(said("Doing something else."))])
    send(client, "actually, make the shopkeeper warmer")
    last = main.repo.settings("p1")["last_question"]
    assert last["text"] == ASK["question"] and last["resolved"]["why"] == "a newer turn started"


def test_a_settled_question_is_no_gate_for_the_next_turn(client, project, monkeypatch):
    import app.api.main as main
    plan = asked(client, monkeypatch)
    client.post(f"/videos/p1/plans/{plan['plan_id']}/approve", json={"items": ["i1"]})
    scripted = _agent_on(monkeypatch, main, [reply(said("All in."))])
    send(client, "Voice it next turn")                            # the old option's words, said after it settled
    opening = scripted.calls[0]["messages"][-1]["content"]
    assert not any("answering yes" in (c.get("text") or "") for c in opening)
