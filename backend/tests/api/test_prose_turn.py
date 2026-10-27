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


def test_a_long_reply_stands_as_two_sentences_with_the_rest_behind_why(client, project, monkeypatch):
    """Run 5 item 5: at most two sentences plus the card in the thread; the rest waits behind "Why?"."""
    from tests.agent.conftest import reply, text as said
    from tests.api.test_endpoints import turn
    from app.agent.reply_lint import MAX_SENTENCES, sentences
    long = "Line 1 is ready to hear. Add it if it sounds right. I used the stock voice because the clip is short. It fits.\n0:00 to 0:02 · one line · $0.01"
    done = turn(client, monkeypatch, [reply(said(long))])
    assert done["reply"] == long                       # the record keeps every word
    last = [m for m in client.get("/videos/p1/messages?after=0").json() if m["role"] == "assistant" and m["kind"] == "say"][-1]
    assert len(sentences(last["text"])) <= MAX_SENTENCES
    assert last["text"] == "Line 1 is ready to hear. Add it if it sounds right."
    assert last["data"]["why"] == "I used the stock voice because the clip is short. It fits.\n0:00 to 0:02 · one line · $0.01"
    # A reply that fits carries nothing behind Why?.
    turn(client, monkeypatch, [reply(said("Line 1 is ready to hear. Add it?"))])
    last = [m for m in client.get("/videos/p1/messages?after=0").json() if m["role"] == "assistant" and m["kind"] == "say"][-1]
    assert last["text"] == "Line 1 is ready to hear. Add it?" and "why" not in (last.get("data") or {})
