"""Run 5 item 2, end to end with mocked vendors (a scripted Claude, the mock
voice): under Check with me, a $0.04 voice-over takes one click from request to
a proposal you can hear; past the user's limit one card asks; the limit lives
in the user's Settings, server-side, default $0.25 a turn."""
import pytest
from fastapi.testclient import TestClient

from app.api.main import app, repo, jobs
from app.media import ffmpeg
from tests.api.test_endpoints import _agent_on, send, take, upload

pytestmark = pytest.mark.skipif(
    not ffmpeg.available(), reason="ffmpeg/ffprobe not installed (`brew install ffmpeg`)",
)


@pytest.fixture(autouse=True)
def reset_state():
    repo.reset()
    jobs.reset()
    yield


@pytest.fixture()
def client():
    return TestClient(app)


@pytest.fixture()
def four_cents(client, sample_video, monkeypatch):
    """A fresh video under the default settings (Check with me), whose take costs $0.04."""
    import app.api.main as main
    assert upload(client, sample_video).status_code == 200
    monkeypatch.setattr(main.voice, "cost_of", lambda plan: 20)           # 20 characters a take
    monkeypatch.setattr(main.budget, "usd_per_1k", 2.0)                    # $0.04 a take
    assert main._workbench().estimate_usd("Get 30% off today only.")[1] == pytest.approx(0.04)
    return main


def test_the_limit_is_a_per_user_setting_kept_server_side_default_25_cents(client, four_cents):
    assert client.get("/me/settings").json()["ask_over_usd"] == 0.25
    assert client.get("/videos/p1/settings").json()["settings"]["autonomy"] == "ask"
    assert client.put("/me/settings", json={"ask_over_usd": 0.6}).json()["ask_over_usd"] == 0.6
    assert client.get("/me/settings").json()["ask_over_usd"] == 0.6
    # The video reads its owner's limit; it is never copied into the video.
    assert client.get("/videos/p1/settings").json()["settings"]["ask_over_usd"] == 0.6
    assert "ask_over_usd" not in repo.settings("p1")
    # Nothing (always ask) to the video ceiling, never below or above.
    assert client.put("/me/settings", json={"ask_over_usd": -1}).json()["ask_over_usd"] == 0.0
    assert client.put("/me/settings", json={"ask_over_usd": 99}).json()["ask_over_usd"] == four_cents.ledger.ceiling_usd


def test_a_four_cent_voice_over_takes_one_click_from_request_to_proposal(client, four_cents, monkeypatch):
    from tests.agent.conftest import reply, text
    _agent_on(monkeypatch, four_cents, [reply(take(), stop="tool_use"), reply(text("Here it is. Hear it on line 1."))])
    clicks = 0
    result = send(client, "make it 30% off")                                 # the one click: Send
    clicks += 1
    assert result["question"] is None and result["plan"]["question"] is None
    [item] = result["plan"]["items"]
    assert item["status"] == "ready" and item["candidate"]["audio"]           # a proposal, ready to hear
    assert clicks == 1


def test_past_the_limit_one_card_asks_with_the_step_and_price_on_its_yes(client, four_cents, monkeypatch):
    from tests.agent.conftest import reply, text
    client.put("/me/settings", json={"ask_over_usd": 0.0})
    _agent_on(monkeypatch, four_cents, [reply(take(), stop="tool_use")])
    q = send(client, "make it 30% off")["question"]
    assert q["gate"] and q["options"] == ["Voice it · $0.04", "Not yet"] and q["cost_usd"] == pytest.approx(0.04)
    # Its yes is the one approval: the take is voiced and nothing asks again.
    _agent_on(monkeypatch, four_cents, [reply(take("d"), stop="tool_use"), reply(text("Voiced. Hear it on line 1."))])
    result = send(client, "Voice it · $0.04")
    assert result["question"] is None and [i["status"] for i in result["plan"]["items"]] == ["ready"]


def test_a_meaning_question_is_still_asked_and_the_pick_is_the_approval(client, four_cents, monkeypatch):
    """Which line is a question about meaning: asked even under the limit. Its card
    carries the price, and the pick voices it, over the limit, with no second card."""
    from tests.agent.conftest import reply, text, use
    client.put("/me/settings", json={"ask_over_usd": 0.0})
    ask = use("ask", "a1", question="Which line should say it?", guess="Voice it here", cost_usd=0.04,
              options=[{"label": "Voice it here", "detail": "Replaces line 1."}, {"label": "Somewhere else", "detail": ""}])
    _agent_on(monkeypatch, four_cents, [reply(ask, stop="tool_use")])
    q = send(client, "make it 30% off")["question"]
    assert not q["gate"] and q["cost_usd"] == pytest.approx(0.04) and q["guess"] == "Voice it here"
    _agent_on(monkeypatch, four_cents, [reply(take(), stop="tool_use"), reply(text("Voiced. Hear it on line 1."))])
    result = send(client, "Voice it here")
    assert result["question"] is None and [i["status"] for i in result["plan"]["items"]] == ["ready"]


def test_without_consent_on_record_nothing_is_voiced_without_a_yes(client, sample_video, monkeypatch):
    import app.api.main as main
    from tests.agent.conftest import reply
    assert upload(client, sample_video, consent=False).status_code == 200
    _agent_on(monkeypatch, main, [reply(take(), stop="tool_use")])
    q = send(client, "make it 30% off")["question"]
    assert q["gate"] and q["options"][0].startswith("Voice it · $")
