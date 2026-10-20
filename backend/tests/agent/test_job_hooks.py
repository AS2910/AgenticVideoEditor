"""The agent's side of the one processing model (2026-10-20): every line it
voices reports through a Job, lines planned with words stand as items before a
Go, and Stop ends the turn after the step that is running."""
import dataclasses

from app.agent.loop import STOPPED, Agent
from app.agent.tools import BY_NAME
from tests.agent.conftest import ScriptedClient, reply, text, use

VOICE = "kL06KYMvPY56NluIQ72m"


def _args(**kw):
    base = {"text": "", "voice_id": VOICE, "start": None, "end": None, "direction": None, "mix": None, "line": None,
            "item_id": None, "model": "default", "fit": "fit", "picture": "default", "beat_at": -1, "key_word": ""}
    return {**base, **kw}


class Recorder:
    def __init__(self):
        self.calls = []

    def claim(self, project_id, item_id, **kw):
        self.calls.append(("claim", item_id, kw["text"]))
        return "J1"

    def begin(self, project_id, kind, label, **kw):
        self.calls.append(("begin", kind, label))
        return "J2"

    def step(self, job_id, label, progress=None):
        self.calls.append(("step", job_id, label))

    def settle(self, job_id, **kw):
        self.calls.append(("settle", job_id, kw.get("ok"), kw.get("code")))


def test_a_voiced_line_claims_its_job_reports_its_steps_and_settles_it(world):
    rec = Recorder()
    wb = dataclasses.replace(world.wb, jobs=rec)
    out = BY_NAME["synthesize_take"].run(wb, world.turn(), _args(text="Welcome to Goa.", start=1.0, end=4.0))
    assert out.text.startswith("Take c1 on i1")
    assert rec.calls[0] == ("claim", "i1", "Welcome to Goa.")
    assert ("step", "J1", "Synthesizing the new line") in rec.calls
    assert rec.calls[-1] == ("settle", "J1", True, None)


def test_a_line_that_fails_settles_its_job_failed_with_the_vendors_reason(world):
    rec = Recorder()

    def down(*a, **kw):
        raise RuntimeError("The voice service did not answer.")
    wb = dataclasses.replace(world.wb, jobs=rec, generate=down)
    BY_NAME["synthesize_take"].run(wb, world.turn(), _args(text="Welcome to Goa.", start=1.0, end=4.0))
    assert rec.calls[-1] == ("settle", "J1", False, "vendor_failed")


def test_lines_planned_with_words_stand_as_items_and_are_voiced_as_those_items(world):
    t = world.turn()
    out = BY_NAME["plan_lines"].run(world.wb, t, {"voice_id": VOICE, "speed": 1, "commentary": False, "lines": [
        {"start": 0.5, "end": 3.0, "text": "Welcome."}, {"start": 4.0, "end": 7.0, "text": "Goodbye."}]})
    assert "Planned as i1." in out.text and "Planned as i2." in out.text
    plan = world.repo.get_plan("p1", "plan1")
    assert [(i.item_id, i.status, i.new_text) for i in plan.items] == [("i1", "planned", "Welcome."), ("i2", "planned", "Goodbye.")]
    # Planned again at the same start: the same item, new words.
    BY_NAME["plan_lines"].run(world.wb, t, {"voice_id": VOICE, "speed": 1, "commentary": False, "lines": [
        {"start": 0.5, "end": 3.0, "text": "Hello."}]})
    assert [i.new_text for i in world.repo.get_plan("p1", "plan1").items] == ["Hello.", "Goodbye."]
    # Voiced by its start alone: the planned item, not a second one.
    res = BY_NAME["synthesize_take"].run(world.wb, t, _args(text="Goodbye.", start=4.0, end=7.0))
    assert res.text.startswith("Take c1 on i2"), res.text
    assert len(world.repo.get_plan("p1", "plan1").items) == 2


def test_stop_ends_the_turn_after_the_step_that_is_running(world):
    stop = {"now": False}
    t = dataclasses.replace(world.turn(), stop_requested=lambda: stop["now"])
    real = world.wb.generate

    def then_stop(*a, **kw):
        stop["now"] = True
        return real(*a, **kw)
    wb = dataclasses.replace(world.wb, generate=then_stop)
    client = ScriptedClient([reply(use("synthesize_take", "a", **_args(text="One.", start=0.5, end=3.0)),
                                   use("synthesize_take", "b", **_args(text="Two.", start=4.0, end=7.0)), stop="tool_use"),
                             reply(text("never asked"))])
    out = Agent(client).run(wb, t, [], "add two lines")
    assert out.stopped == STOPPED and out.question is None
    assert [m["text"] for m in world.made] == ["One."]
    assert len(client.calls) == 1                     # Claude is not asked again after Stop
