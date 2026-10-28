"""Run 5 addendum 0a: every run-4 cost lever has its own switch, so the evals
can measure each alone, and one that hurts a score can be turned off."""
from dataclasses import replace

from app.config import load_settings
from tests.adapters.test_elevenlabs import PLAN, SOURCE, TRANSCRIPT, Takes, adapter, needs_ffmpeg
from tests.api.test_content_cache import Counting
from tests.api.test_endpoints import client, project, reset_state, upload  # noqa: F401
from tests.api.test_understanding import Looker


def test_each_lever_has_a_switch(monkeypatch):
    for name in ("AVE_PLANNER_CACHE", "AVE_TAKE_EARLY_STOP", "AVE_CONTENT_CACHE", "AVE_OPENING_TRIM"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("AVE_QUESTION_MODEL", raising=False)
    default = load_settings()
    # 1a, 1b and 1d on; 1c and 1e off (the owner keeps only 1b and 1d of the quality-facing levers).
    assert (default.planner_cache, default.take_early_stop, default.content_cache, default.opening_trim) == (True, False, True, False)
    assert default.question_model == "claude-haiku-5-5"
    for name in ("AVE_PLANNER_CACHE", "AVE_TAKE_EARLY_STOP", "AVE_CONTENT_CACHE", "AVE_OPENING_TRIM"):
        monkeypatch.setenv(name, "1")
    on = load_settings()
    assert (on.planner_cache, on.take_early_stop, on.content_cache, on.opening_trim) == (True, True, True, True)
    for name in ("AVE_PLANNER_CACHE", "AVE_TAKE_EARLY_STOP", "AVE_CONTENT_CACHE", "AVE_OPENING_TRIM"):
        monkeypatch.setenv(name, "0")
    monkeypatch.setenv("AVE_QUESTION_MODEL", "")
    off = load_settings()
    assert (off.planner_cache, off.take_early_stop, off.content_cache, off.opening_trim) == (False, False, False, False)
    assert off.question_model == ""


def test_planner_cache_off_sends_the_instructions_plain():
    from app.adapters.claude_planner import ClaudePlanner

    class Client:
        def __init__(self):
            self.messages, self.kw = self, None

        def parse(self, **kw):
            self.kw = kw
            raise RuntimeError("stop here")

    for cache, marked in ((True, True), (False, False)):
        c = Client()
        try:
            ClaudePlanner("k", None, client=c, cache=cache)._parse("rules", "hi", None, "low", None)
        except RuntimeError:
            pass
        assert ("cache_control" in c.kw["system"][0]) is marked


@needs_ffmpeg
def test_early_stop_off_voices_every_take_and_keeps_the_nearest(store):
    # 1.3 s misses a 0.9 s slot, 0.92 s is within tolerance: on, the search stops there;
    # off, the third take is voiced too and the nearest (0.9 s) wins.
    on = Takes([1.3, 0.92, 0.9])
    voice = adapter(store, post=on)
    voice._takes, voice._early_stop = 3, True
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(on.calls) == 2
    off = Takes([1.3, 0.92, 0.9])
    voice = adapter(store, post=off)
    voice._takes = 3                                    # the adapter's default, as the settings'
    voice.synthesize(SOURCE, PLAN, TRANSCRIPT)
    assert len(off.calls) == 3 and "nearest of 3 takes" in voice.last_notes


def test_content_cache_off_hears_and_reads_every_upload(client, sample_video, monkeypatch):
    import app.api.main as main
    from app.store import content_cache
    heard, looker = Counting(main.transcriber), Looker()
    monkeypatch.setattr(main, "transcriber", heard)
    monkeypatch.setattr(main, "planner", looker)
    monkeypatch.setattr(main, "settings", replace(main.settings, content_cache=False))
    first = upload(client, sample_video).json()
    client.post(f"/videos/{first['video_id']}/reading", json={})
    second = upload(client, sample_video).json()
    client.post(f"/videos/{second['video_id']}/reading", json={})
    assert heard.calls == 2 and len(looker.calls) == 2
    sha = main.repo.get(first["video_id"]).source.media.sha256
    owner = main.repo.get(first["video_id"]).owner
    assert content_cache.get(main.database, owner, sha, "transcript", content_cache.key_of(main.transcriber_label, content_cache.VERSION)) is None


def test_opening_trim_off_keeps_every_motion_peak():
    from app import understanding as U
    record = {"beats": [{"at": 2.9, "kind": "motion", "label": "motion peak", "confidence": 0.8},
                        {"at": 2.9, "kind": "visual", "label": "highlight jumps", "confidence": 0.7, "source": "vision"}],
              "read": {}, "signals": {}}
    trimmed = next(line for line in U.context_lines(record, trim=True) if line.startswith("Beats:"))
    full = next(line for line in U.context_lines(record) if line.startswith("Beats:"))
    assert trimmed == "Beats: 2.9 s highlight jumps."
    assert full == "Beats: 2.9 s motion peak; 2.9 s highlight jumps."


def test_opening_trim_off_sends_the_full_opening_every_turn(client, project, monkeypatch):
    import app.api.main as main
    from app import understanding as U
    from app.agent.context import UNCHANGED
    from tests.agent.conftest import reply, text as said
    from tests.api.test_endpoints import _agent_on, send
    scripted = _agent_on(monkeypatch, main, [reply(said("Ready.")), reply(said("Still ready.")), reply(said("Yes."))])
    monkeypatch.setattr(main, "settings", replace(main.settings, opening_trim=False))
    main.repo.set_settings("p1", understanding=U.build({"beats": []}, {"format": "ad"}, ""))
    for words in ("make it 30% off", "now warmer", "and warmer"):
        send(client, words)
    assert all(UNCHANGED not in call["messages"][-1]["content"][0]["text"] for call in scripted.calls)
