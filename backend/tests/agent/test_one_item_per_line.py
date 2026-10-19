"""p60 (2026-10-19): Voltage said line 2 was voiced and waiting; the editor showed
"Couldn't voice it". A retry that named only the line made a second item, and a
later failed attempt overwrote the item that held a good take."""
from types import SimpleNamespace as NS

import pytest

from app.agent.reply_check import corrections
from app.agent.tools import BY_NAME
from app.media.ffmpeg import SpanMismatch

LINE2 = dict(index=2, start=5.64, end=7.98, speaker=None, text="a Mormon or I got so hammered last", syllables=9, budget=7)


def _take(world, t, **extra):
    return BY_NAME["synthesize_take"].run(world.wb, t, {"text": "a Mormon, or I got so hammered last", "voice_id": "kL06KYMvPY56NluIQ72m",
                                                        "line": 2, "direction": None, "mix": None, "item_id": None, "start": None, "end": None, **extra})




def test_a_retry_on_the_same_line_re_voices_the_same_item(world):
    world.lines[:] = [NS(**LINE2)]
    t = world.turn()
    _take(world, t)
    _take(world, t)
    items = [i for i in world.repo.get_plan("p1", "plan1").items if i.status != "dismissed"]
    assert len(items) == 1, [i.item_id for i in items]          # one line, one item
    assert items[0].attempt == 2 and [h["outcome"] for h in items[0].history] == ["ready", "ready"]


def test_a_failed_latest_attempt_keeps_the_good_take_and_says_so(world, monkeypatch):
    import dataclasses
    world.lines[:] = [NS(**LINE2)]
    t = world.turn()
    _take(world, t)                                               # a good take: ready
    good = world.repo.get_plan("p1", "plan1").items[0].candidate_id

    def too_long(*a, **k):
        raise SpanMismatch(3.76, 2.34)
    failing = dataclasses.replace(world.wb, generate=too_long)
    out = BY_NAME["synthesize_take"].run(failing, t, {"text": "a Mormon, or I got so hammered last", "voice_id": "kL06KYMvPY56NluIQ72m",
                                                      "line": 2, "direction": None, "mix": None, "item_id": None, "start": None, "end": None})
    item = world.repo.get_plan("p1", "plan1").items[0]
    assert item.status == "ready" and item.candidate_id == good and item.error is None
    assert [h["outcome"] for h in item.history] == ["ready", "failed"]
    assert "keeps its earlier take" in out.text and "Too long for its gap: needs 3.8 s, has 2.3 s." in out.text
    assert "—" not in item.history[-1]["error"]


def test_a_failed_attempt_with_no_take_is_the_items_state(world):
    import dataclasses
    world.lines[:] = [NS(**LINE2)]

    def too_long(*a, **k):
        raise SpanMismatch(3.76, 2.34)
    failing = dataclasses.replace(world.wb, generate=too_long)
    BY_NAME["synthesize_take"].run(failing, world.turn(), {"text": "a Mormon, or I got so hammered last", "voice_id": "kL06KYMvPY56NluIQ72m",
                                                           "line": 2, "direction": None, "mix": None, "item_id": None, "start": None, "end": None})
    item = world.repo.get_plan("p1", "plan1").items[0]
    assert item.status == "failed" and item.error.startswith("Too long for its gap")


def test_an_older_attempt_finishing_after_a_newer_one_cannot_set_the_state(world):
    """Two attempts in flight: the newer succeeds first; the older one's failure lands after it."""
    from app.domain.models import Selection
    from app.domain.plan import PlanItem
    repo = world.repo
    item = PlanItem(item_id="i1", selection=Selection(5.64, 7.98), old_text="x", new_text="y")
    repo.update_plan("p1", "plan1", items=(item,))
    older = repo.begin_attempt("p1", "plan1", "i1")
    newer = repo.begin_attempt("p1", "plan1", "i1")
    assert (older, newer) == (1, 2)
    assert repo.finish_attempt("p1", "plan1", "i1", newer, candidate_id="c3") == "ready"
    assert repo.finish_attempt("p1", "plan1", "i1", older, error="Too long for its gap: needs 3.8 s, has 2.3 s.") == "stale"
    item = repo.get_plan("p1", "plan1").item("i1")
    assert item.status == "ready" and item.candidate_id == "c3"
    assert [(h["attempt"], h["outcome"]) for h in item.history] == [(2, "ready"), (1, "failed")]
    # And an older success after a newer one does not replace the newer take either.
    assert repo.finish_attempt("p1", "plan1", "i1", older, candidate_id="c2") == "stale"
    assert repo.get_plan("p1", "plan1").item("i1").candidate_id == "c3"


def test_the_reply_check_catches_p60s_claim():
    lines = [NS(index=1, start=0.0, end=5.64), NS(index=2, start=5.64, end=7.98)]
    items = [NS(kind="planned", status="ready", selection=NS(start=0.0, end=5.64), new_text="excuse for why", old_text="x", error=None),
             NS(kind="planned", status="failed", selection=NS(start=5.64, end=7.98), new_text="a Mormon, or I got so hammered last",
                old_text="x", error="Too long for its gap: needs 3.8 s, has 2.3 s.")]
    reply = ("Both lines are redone in the Deewar song voice with your words unchanged, and you can play them now. "
             "Line 2 only fit its short gap with the steadier model at a faster pace.")
    assert corrections(reply, items, lines) == ["Correction: line 2 is not voiced: Too long for its gap: needs 3.8 s, has 2.3 s."]
    items[1].status = "ready"
    assert corrections(reply, items, lines) == []
    # A claim that a proposal is in the video is corrected too.
    assert corrections("Line 1 is now in the video.", items, lines) == ["Correction: line 1 is not in the video yet; it is proposed and waiting for your Add it."]
    # Saying it was not voiced is not a claim to correct.
    items[1].status = "failed"
    assert corrections("Line 2 could not be voiced; it is too long for its gap.", items, lines) == []
