"""Run 5 addendum 3, item 1: the check after every render. A line it fails is
carried by the render but is not "In your video": the render's `includes`
names it under `needs_fix`, with the reason, for its row's "Needs a fix"."""
import pytest

import app.api.main as main
from tests.api.test_endpoints import client, generate, project, reset_state, settle_renders  # noqa: F401
from tests.factories import export_now


def _hears(words):
    calls = []

    def hearing(project_id, owner):
        def hear(mono, rate, edit_id):
            calls.append((edit_id, round(len(mono) / rate, 2)))
            return words
        return hear
    return hearing, calls


def _latest(client):
    return client.get("/videos/p1/renders/latest?mode=final").json()["latest"]


def test_a_clean_line_is_in_the_video_with_nothing_to_fix(client, project, monkeypatch):
    hearing, calls = _hears(["30%", "off"])
    monkeypatch.setattr(main, "_render_hearing", hearing)
    take = generate()
    client.post("/videos/p1/edits", json={"candidate_id": take["candidate_id"]})
    out = export_now(client, "/videos/p1/export").json()
    settle_renders()
    assert out["check"]["needs_fix"] == {}, out["check"]
    assert _latest(client)["includes"]["needs_fix"] == {}
    assert calls and calls[0][0].startswith("e1:replace:")


def test_a_line_whose_words_are_not_heard_needs_a_fix_with_the_reason(client, project, monkeypatch):
    hearing, _ = _hears(["30%"])
    monkeypatch.setattr(main, "_render_hearing", hearing)
    take = generate()
    client.post("/videos/p1/edits", json={"candidate_id": take["candidate_id"]})
    export_now(client, "/videos/p1/export")
    settle_renders()
    latest = _latest(client)
    assert "e1" in latest["includes"]["edit_ids"]
    reason = "The last word, “off”, is not heard: it may be cut off."
    assert latest["includes"]["needs_fix"] == {"e1": reason, take["candidate_id"]: reason}
    assert any(f["rule"] == "words" for f in latest["manifest"]["check"]["findings"])


def test_whisper_is_not_called_without_the_real_transcriber_and_its_flag(client, project, monkeypatch):
    assert main._render_hearing("p1", "local") is None           # the mock transcriber: never heard
    monkeypatch.setattr(main, "transcriber_label", "openai-whisper")
    monkeypatch.setattr(main.transcriber, "hear", lambda source: ["x"], raising=False)
    assert main._render_hearing("p1", "local") is not None       # on by default
    main.flags.set(main.RENDER_HEAR_FLAG, "local", False)
    try:
        assert main._render_hearing("p1", "local") is None
    finally:
        main.flags.clear(main.RENDER_HEAR_FLAG, "local")


def test_a_heard_span_is_charged_to_the_ledger_once(client, project, monkeypatch):
    import numpy as np
    monkeypatch.setattr(main, "transcriber_label", "openai-whisper")
    heard = []
    monkeypatch.setattr(main.transcriber, "hear", lambda source: heard.append(source.duration) or ["hello"], raising=False)
    main._heard_spans.clear()
    hear = main._render_hearing("p1", "local")
    span = (np.sin(np.arange(48000 * 3) / 10) * 0.2).astype(np.float32)
    before = main.ledger.spent_usd("p1")
    assert hear(span, 48000, "e1") == ["hello"]
    assert hear(span, 48000, "e1") == ["hello"]                  # the same span again: not sent twice
    assert heard == [pytest.approx(3.0)]
    assert main.ledger.spent_usd("p1") - before == pytest.approx(3 / 60 * 0.006, abs=1e-6)
