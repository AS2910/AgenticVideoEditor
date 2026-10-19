"""A whole turn: Voltage's reply and steps carry no em dash, unless the user wrote one."""
from tests.api.test_endpoints import client, project, reset_state  # noqa: F401 - the module's fixtures


def test_a_turns_reply_and_steps_are_cleaned_unless_the_user_wrote_one(client, project, monkeypatch):
    from tests.agent.conftest import reply, text as said
    from tests.api.test_endpoints import take, turn
    import app.api.main as main
    done = turn(client, monkeypatch, [reply(take(text="Get 30% off today only."), stop="tool_use"), reply(said("Voiced line 1 — hear it."))])
    assert done["reply"] == "Voiced line 1, hear it."
    msgs = client.get("/videos/p1/messages?after=0").json()
    assert not any("—" in m["text"] for m in msgs if m["role"] == "assistant")
    done = turn(client, monkeypatch, [reply(said("Kept it short — as you asked."))], text="Shorter — punchier, please")
    assert done["reply"] == "Kept it short — as you asked."
