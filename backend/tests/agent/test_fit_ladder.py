"""Lines that run long (p61, the boxing clip): written to length before they
are voiced, refused free when they would not fit, climbed down the fit
ladder, tried shorter in the same turn, and asked about together."""
import dataclasses
import json
from types import SimpleNamespace as NS

from app.agent import fitting
from app.agent.guards import TurnBudget
from app.agent.loop import Agent
from app.agent.tools import BY_NAME
from app.domain.models import Selection
from app.domain.plan import PlanItem
from app.media import fit
from app.media.ffmpeg import SpanMismatch
from tests.agent.conftest import ScriptedClient, reply, text, use

VOICE = "kL06KYMvPY56NluIQ72m"
# Ten syllables and a full stop and a comma: about 2.9 s at the default rate,
# so it passes the pre-flight check for a 2.8 s gap; this voice is slower.
LONG = "Back to centre. Red stalks him now, gloves up."
SHORT = "Red stalks him."


def _args(**kw):
    base = {"text": "", "voice_id": VOICE, "start": None, "end": None, "direction": None, "mix": None, "line": None,
            "item_id": None, "model": "default", "fit": "fit", "picture": "default", "beat_at": -1, "key_word": ""}
    return {**base, **kw}


def _natural(text_, spoken_at, speed=1.0):
    return round(fit.syllables(fit.spoken(text_)) / (spoken_at * speed), 3)


def _voice(world, spoken_at, held=False):
    """A voice that speaks `spoken_at` syllables a second. A take is paid for
    before it is fitted, as the vendor does; one longer than its slot by more
    than tempo (and the picture, where it may ease) can take raises
    SpanMismatch. With `held`, the take already paid for is kept and fitted
    again for free (no vendor call), as the real adapter does."""
    real = world.wb.generate
    paid, free = [], []

    def fits(text_, selection, speed, flex_max):
        natural = _natural(text_, spoken_at, speed)
        reach = (selection.end - selection.start) * 1.25 * max(1.0, flex_max or 1.0)
        return natural, natural <= reach + 1e-6

    def generate(project_id, rec, candidate_id, selection, text_, *a, **k):
        speed = float(((k.get("voice_settings") or {}).get("speed")) or 1.0)
        paid.append((text_, speed, selection))
        natural, ok = fits(text_, selection, speed, k.get("flex_max"))
        if not ok:
            world.ledger.record(project_id, "elevenlabs", "take", len(text_), "characters", 0.03)
            raise SpanMismatch(natural, selection.end - selection.start)
        return real(project_id, rec, candidate_id, selection, text_, *a, **k)

    def held_take(project_id, rec, candidate_id, selection, text_, *a, flex_max=None, **k):
        speed = float(((k.get("voice_settings") or {}).get("speed")) or 1.0)
        free.append((selection, flex_max))
        natural, ok = fits(text_, selection, speed, flex_max)
        if not ok:
            raise SpanMismatch(natural, selection.end - selection.start)
        # The same audio placed again: nothing paid (move_take makes the fake candidate without a charge).
        c = world.wb.move_take(project_id, rec, NS(candidate_id=candidate_id, plan=NS(selection=selection, new_text=text_)), selection.start, None)
        c.plan.flex = flex_max if flex_max and flex_max > 1 else None
        return c

    wb = dataclasses.replace(world.wb, generate=generate, held_take=held_take if held else None)
    return wb, paid, free


def _planned(world, item_id, start, end, words, beat=None):
    plan = world.repo.get_plan("p1", "plan1")
    item = PlanItem(item_id=item_id, selection=Selection(start, end), old_text="", new_text=words, mix="layer", status="planned", beat=beat)
    world.repo.update_plan("p1", "plan1", items=plan.items + (item,))


# ── 1. writing to length ─────────────────────────────────────────────────────

def test_four_lines_planned_two_seconds_apart_get_budgets_that_fit(world):
    t = world.turn()
    starts = (0.0, 2.0, 4.0, 6.0)
    out = BY_NAME["plan_lines"].run(world.wb, t, {"voice_id": VOICE, "speed": 1, "commentary": True,
                                                   "lines": [{"start": s, "end": -1, "text": ""} for s in starts]})
    planned = fitting.plan([{"start": s, "end": -1, "text": ""} for s in starts], 7.5, fit.DEFAULT_VOICE_RATE, commentary=True)
    lines = planned["lines"]
    # Each window ends a breath before the next line; the last at the clip's end.
    assert [(r["start"], r["end"]) for r in lines] == [(0.0, 1.8), (2.0, 3.8), (4.0, 5.8), (6.0, 7.5)]
    # Commentary breathes: the budgets together are at most 70% of the clip.
    assert planned["breathing"] and sum(r["budget"] for r in lines) / fit.DEFAULT_VOICE_RATE <= 7.5 * 0.7
    assert "The budgets hold the talk to about 70% of the clip, so the lines breathe." in out.text
    assert "1. 0.0–1.8 s, a 1.8 s window: up to 5 syllables." in out.text
    assert out.step == "Planned 4 lines together: each fits its window"
    # A line written to its budget passes the pre-flight check and is voiced.
    for n, r in enumerate(lines):
        words = " ".join(["la"] * r["budget"])
        assert fit.estimate_seconds(words, fit.DEFAULT_VOICE_RATE) <= r["window"]
        res = BY_NAME["synthesize_take"].run(world.wb, t, _args(text=words, start=r["start"], end=r["end"]))
        assert res.text.startswith(f"Take c{n + 1} on i{n + 1}"), res.text
    assert len(world.made) == 4


def test_plan_lines_names_a_line_too_long_and_too_much_talk(world):
    out = BY_NAME["plan_lines"].run(world.wb, world.turn(), {"voice_id": VOICE, "speed": 1, "commentary": True, "lines": [
        {"start": 0.2, "end": -1, "text": "Back to the centre now. Red shorts stalking, gloves held high."},
        {"start": 2.6, "end": 7.5, "text": "Blue goes DOWN!"}]})
    assert ("1. 0.2–2.4 s, a 2.2 s window: up to 5 syllables; “Back to the centre now. Red shorts stalking, gloves held high.” "
            "runs about 3.6 s (13 syllables). Too long: rewrite to about 5 syllables.") in out.text
    assert out.step == "Planned 2 lines together: 1 too long, to rewrite"


def test_find_room_gives_every_window_its_length_and_syllables_at_the_voices_rate(world):
    world.repo.set_settings("p1", sight={"beats": [{"at": 0.3, "note": "the clinch breaks"}, {"at": 2.6, "note": "they square up"}]})
    out = BY_NAME["find_room"].run(world.wb, world.turn(), {"voice_id": VOICE})
    assert "Varsha speaks about 4.0 syllables a second (the default until Varsha has takes)." in out.text
    assert "- 0.3–2.6 s (2.3 s): up to 8 syllables; beat: the clinch breaks" in out.text
    assert "- 2.6–7.5 s (4.9 s): up to 19 syllables; beat: they square up" in out.text
    assert "keep the talk under about 70% of the clip (5.2 s here)" in out.text


def test_a_voices_rate_is_learned_from_its_takes_and_every_estimate_is_logged(world):
    wb = dataclasses.replace(world.wb, measured=lambda: {"seconds": 2.6, "speed": 1.0})
    t = world.turn()
    line = "Referee breaks the clinch, he wants them apart."          # 11 syllables and a comma
    BY_NAME["synthesize_take"].run(wb, t, _args(text=line, start=0.2, end=3.2))
    rate, takes = fitting.voice_rate(world.repo, VOICE)
    assert takes == 1 and rate == round(11 / (2.6 - 0.12), 2)
    log = json.loads(world.repo.get_meta(fitting.LOG_KEY))
    assert log[-1] == {"at": "", "video": "p1", "item": "i1", "voice_id": VOICE, "text": line,
                       "estimate_s": round(fit.estimate_seconds(line, fit.DEFAULT_VOICE_RATE), 2), "actual_s": 2.6,
                       "window_s": 3.0, "speed": 1.0, "outcome": "fit"}
    # The next estimate for this voice is at its own rate.
    assert "Varsha speaks about 4.4 syllables a second (measured over 1 take)." in BY_NAME["find_room"].run(wb, t, {"voice_id": VOICE}).text


# ── 2. pre-flight ────────────────────────────────────────────────────────────

def test_preflight_refuses_an_overlong_line_at_no_cost(world):
    t = world.turn()
    # p61's middle line, 13 syllables, in a 2.3 s gap.
    out = BY_NAME["synthesize_take"].run(world.wb, t, _args(text="Back to the centre now. Red shorts stalking, gloves held high.",
                                                             start=2.2, end=4.5))
    assert out.text == ("Too long: about 3.6 s for a 2.3 s window; rewrite to about 7 syllables (it has 13 now) and call again. "
                        "Nothing was voiced or paid.")
    assert out.step == "Checked “Back to the centre now. Red shorts stalk…” before voicing: about 3.6 s for 2.3 s, too long"
    assert out.cost_usd == 0 and world.made == [] and world.ledger.spent_usd("p1") == 0
    assert world.repo.get_plan("p1", "plan1").items == ()           # nothing was started either
    ok = BY_NAME["synthesize_take"].run(world.wb, t, _args(text="Back to centre. Red stalks him.", start=2.2, end=4.5))
    assert ok.text.startswith("Take c1 on i1")


def test_a_line_that_fits_the_estimate_is_not_held_back():
    assert fitting.preflight("Blue goes DOWN!", 2.0, fit.DEFAULT_VOICE_RATE) is None
    check = fitting.preflight("[excited] Ohh, there's the exchange! Red catches him CLEAN!", 2.3, fit.DEFAULT_VOICE_RATE)
    assert check == {"estimate": 3.22, "window": 2.3, "syllables": 11, "budget": 7}
    assert fit.tags_of("[curious] So... [whispers] here?") == ["curious", "whispers"]
    assert fit.spoken("[curious] So... [whispers] here?") == "So... here?"


# ── 3. the fit ladder ────────────────────────────────────────────────────────

def test_the_ladder_starts_150_ms_early_from_the_take_already_paid_for(world):
    wb, paid, free = _voice(world, spoken_at=_natural_rate(3.6), held=True)    # needs 3.6 s: 2.8 s × 1.25 is 3.5
    out = BY_NAME["synthesize_take"].run(wb, world.turn(), _args(text=LONG, start=2.0, end=4.8))
    assert free[0] == (Selection(1.85, 4.8), 1.0)
    assert ("It ran long at first; it fits now after: trimmed the take's pauses, lead-in and tail, and sped the speech "
            "up to 1.25×; started 150 ms early.") in out.text
    item = world.repo.get_plan("p1", "plan1").items[0]
    assert item.status == "ready" and item.selection == Selection(1.85, 4.8)
    assert len(paid) == 1                                           # one paid take; the early start reused it


def _natural_rate(seconds):
    """The rate at which LONG runs `seconds`."""
    return fit.syllables(fit.spoken(LONG)) / seconds


def test_the_ladder_retakes_at_the_models_own_speed_up_to_115(world):
    wb, paid, free = _voice(world, spoken_at=_natural_rate(4.0))   # 4.0 s: 1.14× speed brings it within 2.8 s × 1.25
    out = BY_NAME["synthesize_take"].run(wb, world.turn(), _args(text=LONG, start=2.0, end=4.8))
    assert [round(s, 2) for _, s, _ in paid] == [1.0, 1.15]
    assert "a retake at 1.15× speed." in out.text and world.repo.get_plan("p1", "plan1").items[0].status == "ready"


def test_a_failure_says_exactly_what_was_tried_and_keeps_the_take_for_the_picture_to_ease(world):
    _planned(world, "i9", 5.0, 7.5, "Blue goes DOWN!", beat={"at": 5.0, "key_word": "DOWN"})
    wb, paid, free = _voice(world, spoken_at=_natural_rate(4.55), held=True)
    t = world.turn()
    out = BY_NAME["synthesize_take"].run(wb, t, _args(text=LONG, start=2.0, end=4.8))
    item = world.repo.get_plan("p1", "plan1").item("i2")
    assert item.status == "failed" and item.error == "Too long for its gap: needs 4.5 s, has 2.8 s."
    failure = item.fit_failure
    assert failure["tried"] == ["trimmed the take's pauses, lead-in and tail, and sped the speech up to 1.25×",
                                "started 150 ms early",
                                "a faster retake would need 1.23× speed, past the 1.15× that still sounds natural",
                                "the next line had no room before its beat",
                                "the picture may not ease unless you allow it"]
    assert failure["budget"] == 6 and failure["syllables"] == 10 and failure["needs"] == 4.55 and failure["has"] == 2.8
    # The paid take is kept, fitted with the picture easing, for the user to choose at no new cost.
    assert failure["eased_candidate_id"] and failure["ease_s"] == round(2.95 * 0.25, 2)
    assert free[-1] == (Selection(1.85, 4.8), fit.USER_EASE_MAX)
    assert len(paid) == 1 and failure["cost_usd"] == 0.03
    assert "Rewrite it to about 6 syllables (it has 10) and voice it again now on i2, once." in out.text
    assert "The take is kept: with the picture easing 0.7 s it fits" in out.text
    assert out.step == "Too long for its gap: “Back to centre. Red stalks him now, glov…”, 4.5 s for 2.8 s"
    assert t.fit_failed["i2"]["budget"] == 6


def test_the_next_added_line_flows_later_when_it_has_room_before_its_beat(world):
    t = world.turn()
    BY_NAME["synthesize_take"].run(world.wb, t, _args(text="Ohh, he catches him!", start=5.0, end=6.6))
    # Its key word lands 0.1 s early for its beat, so it may move up to 0.4 s later.
    world.repo.update_item("p1", "plan1", "i1", beat={"at": 5.6, "key_word": "catches", "miss": -0.1})
    wb, paid, free = _voice(world, spoken_at=_natural_rate(4.37), held=True)
    out = BY_NAME["synthesize_take"].run(wb, t, _args(text=LONG, start=2.1, end=4.8, speed=1.15))
    assert "ran on 0.2 s into the room after it; the next line flows 0.2 s later" in out.text, out.text
    plan = world.repo.get_plan("p1", "plan1")
    assert plan.item("i2").status == "ready" and plan.item("i1").selection.start == 5.21
    assert ("c1", 5.21) in world.moved


# ── 4. recovered within the turn ─────────────────────────────────────────────

def _run(wb, client, turn):
    return Agent(client).run(wb, turn, [], "Commentary, two commentators", persist=lambda r, c: None)


def test_a_failure_is_rewritten_and_fits_in_the_same_turn(world):
    wb, paid, _ = _voice(world, spoken_at=_natural_rate(4.55))
    client = ScriptedClient([
        reply(use("synthesize_take", "a", **_args(text=LONG, start=2.0, end=4.8)), stop="tool_use"),
        reply(use("synthesize_take", "b", **_args(text=SHORT, item_id="i1")), stop="tool_use"),
        reply(text("The middle line is shorter now and lands in its gap.")),
    ])
    t = world.turn()
    out = _run(wb, client, t)
    first = client.calls[1]["messages"][-1]["content"][0]["content"]
    assert "Rewrite it to about 6 syllables (it has 10) and voice it again now on i1, once." in first
    item = world.repo.get_plan("p1", "plan1").items[0]
    assert item.status == "ready" and item.new_text == SHORT and item.fit_failure is None and item.error is None
    assert out.question is None and t.fit_retried == {"i1"}
    assert [p[0] for p in paid] == [LONG, SHORT]


def test_a_turn_that_would_end_with_a_line_too_long_is_told_to_try_it_shorter(world):
    wb, paid, _ = _voice(world, spoken_at=_natural_rate(4.55))
    client = ScriptedClient([
        reply(use("synthesize_take", "a", **_args(text=LONG, start=2.0, end=4.8)), stop="tool_use"),
        reply(text("One line was too long.")),                      # it would stop here
        reply(use("synthesize_take", "b", **_args(text=SHORT, item_id="i1")), stop="tool_use"),
        reply(text("The middle line is shorter now.")),
    ])
    out = _run(wb, client, world.turn())
    nudge = client.calls[2]["messages"][-1]["content"][0]["text"]
    assert nudge == ("Not finished: these lines were too long for their gaps and have not been tried shorter: "
                     f"i1 (“{LONG}”: about 6 syllables for 2.8 s). Rewrite each to its syllables and voice it again once now, "
                     "with its item_id. Then close the turn.")
    assert out.reply == "The middle line is shorter now." and out.question is None
    assert world.repo.get_plan("p1", "plan1").items[0].status == "ready"


def test_with_the_cap_reached_one_grouped_question_appears(world):
    wb, paid, _ = _voice(world, spoken_at=2.0)
    lines = [(LONG, 0.2, 3.0), ("Blue backs off, Red follows him now.", 3.2, 6.0)]
    client = ScriptedClient([
        reply(*[use("synthesize_take", f"u{n}", **_args(text=w, start=s, end=e)) for n, (w, s, e) in enumerate(lines)], stop="tool_use"),
        reply(text("Both lines ran long.")),
    ])
    t = world.turn(budget=TurnBudget(usd=0.07))                      # two paid takes leave too little to retake both
    out = _run(wb, client, t)
    plan = world.repo.get_plan("p1", "plan1")
    assert [i.status for i in plan.items] == ["failed", "failed"] and len(paid) == 2
    usd = round(sum(round(len(w) * 0.0003, 4) for w, _, _ in lines), 2)
    assert out.question == {"text": f"2 lines need shorter versions, about ${usd:.2f}. Go ahead?",
                            "options": ["Go ahead", "Leave them for now"], "guess": "Go ahead", "gate": True, "cost_usd": usd,
                            "details": ["Rewrite each to fit their gaps and voice each once.",
                                        "They stay as they are; shorten, ease or discard them from their rows."]}
    assert len(client.calls) == 2                                     # one question; no per-line asks, no nudge past the cap


def test_a_shorter_retry_the_cap_refuses_is_left_for_the_one_question(world):
    wb, paid, _ = _voice(world, spoken_at=_natural_rate(4.55))
    client = ScriptedClient([
        reply(use("synthesize_take", "a", **_args(text=LONG, start=2.0, end=4.8)), stop="tool_use"),
        reply(use("synthesize_take", "b", **_args(text=SHORT, item_id="i1")), stop="tool_use"),
        reply(text("The line is still too long.")),
    ])
    out = _run(wb, client, world.turn(budget=TurnBudget(usd=0.032)))
    refused = client.calls[2]["messages"][-1]["content"][0]["content"]
    assert refused.startswith("The turn's cap does not cover voicing this now. Do not ask about it on its own")
    assert out.question["text"] == "1 line needs a shorter version, about $0.01. Go ahead?"


def test_the_opening_names_a_line_that_ran_long_with_its_syllables(world):
    from app.agent.context import opening
    wb, _, _ = _voice(world, spoken_at=_natural_rate(4.55))
    BY_NAME["synthesize_take"].run(wb, world.turn(), _args(text=LONG, start=2.0, end=4.8))
    head = opening(world.repo.get_plan("p1", "plan1"), duration=7.5, filename="boxing.mp4", speakers=[], lines=0, autonomy="draft",
                   spent_usd=0.03, ceiling_usd=2.0, turn_usd=0.5)
    assert "(failed: too long, needs 4.5 s for 2.8 s; rewrite to about 6 syllables)" in head
