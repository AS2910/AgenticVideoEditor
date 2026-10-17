"""The opening view of a turn (20e): what is in the video already is listed with the plan."""
from types import SimpleNamespace

from app.agent.context import opening
from app.domain.models import Selection


def test_opening_lists_the_shipped_edits_after_the_plan():
    edit = SimpleNamespace(edit_id="e3", reverted=False,
                           plan=SimpleNamespace(selection=Selection(0.0, 7.4), new_text="Golden sands.", mix="layer"))
    gone = SimpleNamespace(edit_id="e1", reverted=True, plan=edit.plan)
    head = opening(None, duration=7.5, filename="beach.mp4", speakers=[], lines=0, autonomy="draft",
                   spent_usd=0.9, ceiling_usd=10.0, turn_usd=0.5, sight="A beach.", edits=[gone, edit])
    assert head.endswith("In the video already (shipped; undo_edit takes one out):\n"
                         "- e3 at 0.0–7.4 s: “Golden sands.” — layered over the picture and sound")
    assert "e1" not in head
    assert opening(None, duration=7.5, filename="beach.mp4", speakers=[], lines=0, autonomy="draft",
                   spent_usd=0.0, ceiling_usd=10.0, turn_usd=0.5).count("In the video") == 0
