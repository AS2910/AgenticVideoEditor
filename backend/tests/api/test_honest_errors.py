"""Run 5 item 1: honest error messages. Each failure is forced through a
mocked vendor (AVE_CHAOS's seams, the rehearsal voice, a scripted Claude) and
the person must read the classifier's sentence: ours, the safety filter's
with the line named, or their own input's with what to change. Never the
SDK's text, never "refused on my side"."""
import random
from pathlib import Path

import anthropic
import httpx
import pytest

import app.api.main as main
from app import failures
from app.adapters.elevenlabs import VoiceConfigError, _raise_for
from app.adapters.openai_whisper import WhisperTranscriptionAdapter
from app.adapters.rehearsal import RehearsalVoiceAdapter
from app.budget import BudgetExceeded
from app.chaos import Chaos, parse
from app.errors import SafetyRefused
from app.failures import OUR_END, OUR_SIDE, SAFETY, USER_INPUT
from app.media import ffmpeg
from app.store.db import Database
from app.usage import SpendCeilingReached
from tests.agent.conftest import ScriptedClient, reply, text as said
from tests.api.test_endpoints import _agent_on, send, take, upload
from tests.factories import voiced_video

ROOT = Path(__file__).resolve().parents[2]
needs_ffmpeg = pytest.mark.skipif(not ffmpeg.available(), reason="ffmpeg/ffprobe not installed")


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    main.repo.reset()
    main.jobs.reset()
    monkeypatch.setenv("AVE_MOCK_SYNTH_SECONDS", "0")
    with main.database.tx() as c:
        c.execute("DELETE FROM meta WHERE key LIKE 'vendor_alert:%'")
        c.execute("DELETE FROM notifications WHERE kind = 'vendor_failure'")
    yield


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    return TestClient(main.app)


@pytest.fixture()
def video(client, sample_video):
    resp = upload(client, sample_video)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _alerts() -> list[dict]:
    with main.database.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM notifications WHERE kind = 'vendor_failure' ORDER BY id")]


def _reports(where: str) -> list[dict]:
    with main.database.tx() as c:
        return [dict(r) for r in c.execute("SELECT * FROM error_reports WHERE source = 'vendor' AND location = ? ORDER BY id",
                                           (where,))]


def _chaos(spec: str) -> Chaos:
    return Chaos(parse(spec), sleep=lambda _: None, rng=random.Random(0))


def _claude(monkeypatch, spec: str, responses=()):
    """Voltage on, its Claude behind an injected fault."""
    from app.adapters.mock_claude import MockAnthropic
    from app.agent.loop import Agent
    _agent_on(monkeypatch, main, list(responses))
    monkeypatch.setattr(main, "_agent_instance", Agent(_chaos(spec).anthropic_client(MockAnthropic())))


# ── our side: Anthropic in a turn ────────────────────────────────────────────

@needs_ffmpeg
@pytest.mark.parametrize("spec, reason", [
    ("anthropic=status:401", "the key was refused"),         # the invalid key that started this
    ("anthropic=status:403", "the key was refused"),
    ("anthropic=status:429", "rate limited"),
    ("anthropic=status:500", "an outage"),
    ("anthropic=hang:1", "a timeout"),
    ("anthropic=reset", "could not connect"),
])
def test_a_claude_failure_in_a_turn_is_our_end_with_nothing_charged_and_the_admins_told(client, video, monkeypatch, spec, reason):
    _claude(monkeypatch, spec)
    out = send(client, "make it 30% off")
    assert out["reply"] == OUR_END and out["error"] == OUR_END and out["spent_usd"] == 0.0
    thread = [m["text"] for m in client.get("/videos/p1/messages").json()]
    assert OUR_END in thread and not any("my side" in t or "chaos" in t or "anthropic" in t.lower() for t in thread)
    assert main.ledger.spent_usd("p1") == 0.0                                  # "Nothing was charged" is true
    alerts = _alerts()
    assert len(alerts) == 1 and reason in alerts[0]["title"] and "Claude" in alerts[0]["title"] and alerts[0]["link"] == "#admin"
    assert _reports("turn"), "the real cause is in the error reports"


@needs_ffmpeg
def test_the_same_outage_twice_is_one_admin_notice(client, video, monkeypatch):
    _claude(monkeypatch, "anthropic=status:401")
    send(client, "make it 30% off")
    send(client, "make it 40% off")
    assert len(_alerts()) == 1 and len(_reports("turn")) >= 2


class _FailsSecond(ScriptedClient):
    def _create(self, **params):
        if len(self.calls) == 1:
            self.calls.append(params)
            req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None)
        return super()._create(**params)


@needs_ffmpeg
def test_a_turn_that_paid_for_a_step_before_failing_says_what_it_spent(client, video, monkeypatch):
    from app.agent.loop import Agent
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [])
    monkeypatch.setattr(main, "_agent_instance", Agent(_FailsSecond([reply(take(), stop="tool_use")])))
    out = send(client, "make it 30% off")
    assert main.ledger.spent_usd("p1") > 0                                    # Claude's first answer was paid for
    assert out["reply"].startswith("Something went wrong on our end. The step that failed was not charged")
    assert "Nothing was charged" not in out["reply"]


@needs_ffmpeg
def test_claudes_own_refusal_says_the_safety_filter_and_quotes_the_request(client, video, monkeypatch):
    _agent_on(monkeypatch, main, [reply(said("no"), stop="refusal")])
    out = send(client, "make him say something awful")
    assert out["reply"] == failures.request_refused("make him say something awful")
    assert "safety filter" in out["reply"] and "make him say something awful" in out["reply"]
    assert _alerts() == []                                                    # not ours: no admin notice


# ── ElevenLabs, through the rehearsal voice and AVE_CHAOS ───────────────────

def _voice_fails(monkeypatch, spec: str):
    monkeypatch.setattr(main, "voice", RehearsalVoiceAdapter(main.artifacts, main.budget, _chaos(spec), 1))


def _voiced_with(client, monkeypatch, spec):
    _voice_fails(monkeypatch, spec)
    client.put("/videos/p1/settings", json={"autonomy": "draft"})
    _agent_on(monkeypatch, main, [reply(take(text="Get 30% off today only."), stop="tool_use"), reply(said("Done."))])
    send(client, "make it 30% off")
    messages = client.get("/videos/p1/messages").json()
    jobs = client.get("/videos/p1/jobs").json()["jobs"]
    line = next(j for j in jobs if j["kind"] == "voice_line")
    return messages, line


@needs_ffmpeg
def test_a_line_the_voice_vendors_safety_filter_refuses_is_named_and_refunded(client, video, monkeypatch):
    messages, line = _voiced_with(client, monkeypatch, "elevenlabs=refuse")
    assert line["status"] == "failed"
    assert "safety filter refused the line at 0:" in line["error_text"] and "Get 30% off today only." in line["error_text"]
    assert any("safety filter" in m["text"] for m in messages if m["kind"] == "step")
    assert main.budget.spent("p1") == 0                                       # the held charge came back
    assert _alerts() == []


@needs_ffmpeg
@pytest.mark.parametrize("spec, reason", [("elevenlabs=status:401", "the key was refused"),
                                          ("elevenlabs=status:429", "rate limited"),
                                          ("elevenlabs=reset", "could not connect")])
def test_a_voice_vendor_failure_is_our_end_and_refunded(client, video, monkeypatch, spec, reason):
    messages, line = _voiced_with(client, monkeypatch, spec)
    assert line["status"] == "failed" and line["error_text"] == OUR_END
    steps = " ".join(m["text"] for m in messages)
    assert "ElevenLabs" not in steps and "ELEVENLABS_API_KEY" not in steps and "chaos" not in steps
    assert main.budget.spent("p1") == 0
    assert reason in _alerts()[0]["title"]


# ── OpenAI transcription at upload ──────────────────────────────────────────

@needs_ffmpeg
@pytest.mark.parametrize("spec", ["openai=status:401", "openai=status:500", "openai=hang:1", "openai=reset"])
def test_a_transcription_failure_at_upload_is_our_end_and_not_charged(client, tmp_path, monkeypatch, spec):
    heard = WhisperTranscriptionAdapter("sk-test", post=_chaos(spec).openai_post(lambda *a: {"words": []}))
    monkeypatch.setattr(main, "transcriber", heard)
    monkeypatch.setattr(main, "transcriber_label", "openai:whisper-1")
    # Run 5 item 4: a silent clip is never sent, so the vendor only fails on one with sound.
    resp = upload(client, voiced_video(tmp_path / "voiced.mp4", 2.3))
    assert resp.status_code == 503 and resp.json()["detail"] == OUR_END
    with main.database.tx() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM usage WHERE vendor = 'openai'").fetchone()["n"] == 0
    assert "OpenAI transcription" in _alerts()[0]["title"]


# ── the person's input says what and how to fix it ───────────────────────────

@needs_ffmpeg
def test_an_upload_that_is_not_a_video_says_so_and_what_works(client, tmp_path):
    bad = tmp_path / "notes.mp4"
    bad.write_bytes(b"just some words, not a video at all" * 100)
    resp = upload(client, bad)
    assert resp.status_code == 415 and resp.json()["detail"].startswith("That file is not a video")
    assert _alerts() == []


def test_caps_and_budgets_are_the_persons_with_what_to_do():
    over = failures.classify(SpendCeilingReached(2.0, 2.0, "ad.mp4"))
    assert over.kind == USER_INPUT and "Raise it in Settings" in over.text
    budget = failures.classify(BudgetExceeded(120, 40))
    assert budget.kind == USER_INPUT and "AVE_" not in budget.text and "fewer new words" in budget.text
    assert failures.http(BudgetExceeded(120, 40), where="t").status_code == 402


# ── the classifier, one mapping at a time ────────────────────────────────────

def test_every_vendor_refusal_of_our_account_is_ours_with_no_vendor_words():
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    for exc in (anthropic.AuthenticationError("invalid x-api-key", response=httpx.Response(401, request=req), body=None),
                anthropic.APITimeoutError(request=req),
                VoiceConfigError("ElevenLabs rejected the API key (401). Check ELEVENLABS_API_KEY."),
                VoiceConfigError("The ElevenLabs quota for this month is used up.")):
        found = failures.classify(exc)
        assert (found.kind, found.text) == (OUR_SIDE, OUR_END)
    assert failures.classify(VoiceConfigError("The ElevenLabs quota for this month is used up.")).reason == "the account's quota is used up"
    assert failures.http(VoiceConfigError("x (401)"), where="t").status_code == 503


def test_elevenlabs_safety_answers_name_the_line_by_time_and_words():
    with pytest.raises(SafetyRefused) as refused:
        _raise_for(400, '{"detail": {"status": "content_against_policy", "message": "violates our terms"}}', ("Buy now", 6.2))
    found = failures.classify(refused.value)
    assert found.kind == SAFETY and "the line at 0:06 (“Buy now”)" in found.text and "Reword" in found.text
    with pytest.raises(VoiceConfigError):            # an account problem is not a safety refusal
        _raise_for(401, '{"detail": {"status": "invalid_api_key"}}')


def test_a_bug_of_ours_never_shows_its_text_and_promises_nothing_about_money():
    found = failures.classify(ValueError("invalid literal for int() with base 10: 'x'"))
    assert found.kind == OUR_SIDE and "literal" not in found.text and "Nothing was charged" not in found.text
    assert failures.say(ValueError("x"), where="t", spent_usd=0.0) == OUR_END


def test_admin_notices_go_to_every_admin_once_per_cause(tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    now = [1000.0]
    monkeypatch.setattr(failures, "_db", db)
    monkeypatch.setattr(failures, "_admins", lambda: ["a1", "a2"])
    monkeypatch.setattr(failures, "_reporter", None)
    monkeypatch.setattr(failures, "_clock", lambda: now[0])
    key = VoiceConfigError("ElevenLabs rejected the API key (401).")
    for _ in range(3):
        failures.say(key, where="t")
    failures.say(anthropic.APITimeoutError(request=httpx.Request("POST", "https://x")), where="t")
    with db.tx() as c:
        rows = c.execute("SELECT recipient, title FROM notifications WHERE kind = 'vendor_failure'").fetchall()
    assert sorted(r["recipient"] for r in rows) == ["a1", "a1", "a2", "a2"]          # one per cause, per admin
    now[0] += failures.ALERT_EVERY_S + 1
    failures.say(key, where="t")
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) AS n FROM notifications WHERE kind = 'vendor_failure'").fetchone()["n"] == 6


def test_chaos_refuse_is_for_the_voice_vendor_only():
    assert parse("elevenlabs=refuse")["elevenlabs"].kind == "refuse"
    with pytest.raises(ValueError):
        parse("anthropic=refuse")


def test_no_code_says_refused_on_my_side():
    for path in list((ROOT / "backend" / "app").rglob("*.py")) + list((ROOT / "frontend" / "src").rglob("*.ts*")):
        assert "on my side" not in path.read_text(encoding="utf-8"), path
