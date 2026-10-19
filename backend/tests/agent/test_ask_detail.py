"""The ask tool's options: a short label and an optional detail line; and what
the turn's cap must rise by for the step it refused (pane-render)."""
import pytest

from app.agent.guards import TurnBudget, WaitingForUser
from app.agent.tools import BY_NAME


def test_ask_takes_a_label_and_a_detail_per_option(world):
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ask"].run(world.wb, world.turn(), {"question": "Which?", "guess": "Short one", "options": [
            {"label": "Short one", "detail": "The whole sentence, which is far too long to sit on a button by itself."},
            {"label": "Other", "detail": ""}]})
    assert w.value.options == ("Short one", "Other")
    assert w.value.details == ("The whole sentence, which is far too long to sit on a button by itself.", None)
    assert w.value.guess == "Short one"


def test_ask_still_takes_plain_strings_and_leaves_details_out(world):
    with pytest.raises(WaitingForUser) as w:
        BY_NAME["ask"].run(world.wb, world.turn(), {"question": "?", "options": ["Yes", "No"], "guess": ""})
    assert w.value.options == ("Yes", "No") and w.value.details is None


def test_the_ask_schema_names_label_and_detail():
    items = BY_NAME["ask"].schema["properties"]["options"]["items"]
    assert set(items["properties"]) == {"label", "detail"} and items["additionalProperties"] is False


def test_the_cap_names_exactly_what_the_refused_step_needs():
    budget = TurnBudget(usd=0.50)
    assert budget.needed_usd(0.50) == 0.0                    # nothing refused yet
    assert budget.refuses(0.47, 0.04) is not None
    assert budget.needed_usd(0.50) == 0.04                   # spent 0.50 by the question, the step 0.04
    assert budget.needed_usd(0.461) == 0.01                  # 0.001 short rounds up to a cent
    raised = TurnBudget(usd=0.54, excused=lambda: 0.02)     # carried on: its own thinking is not charged to the raise
    assert raised.refuses(0.52, 0.04) is None
    assert raised.refuses(0.53, 0.04) is not None
