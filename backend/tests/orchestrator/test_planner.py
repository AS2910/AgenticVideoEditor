from app.orchestrator.planner import ItemView, Line, RulePlanner

LINES = [
    Line(1, 0.0, 2.3, "Presenter", "Get 20% off today only."),
    Line(2, 2.5, 4.0, "Presenter", "Twenty percent, this week."),
    Line(3, 4.2, 5.0, None, "Thanks."),
]


def test_a_quoted_change_is_applied_to_every_line_that_says_it():
    proposal = RulePlanner().plan('change "20% off" to "30% off"', LINES)
    assert [(c.line, c.new_text) for c in proposal.edits] == [(1, "Get 30% off today only.")]
    assert proposal.summary == "Found 1 line to change."
    assert proposal.suggestions == ()


def test_the_rule_planner_cannot_read_a_goal_in_prose():
    proposal = RulePlanner().plan("make it a Diwali ad", LINES)
    assert proposal.edits == ()
    assert "Claude" in proposal.summary


def test_a_change_nobody_says_plans_nothing():
    proposal = RulePlanner().plan('change "half price" to "free"', LINES)
    assert proposal.edits == () and 'No line says "half price"' in proposal.summary


def test_the_rule_planner_offers_no_shorter_line():
    assert RulePlanner().shorten("a long line", 0.6, LINES[0]) is None


def test_the_rule_planner_reports_what_it_read():
    proposal = RulePlanner().plan('change "20% off" to "30% off"', LINES)
    assert proposal.findings == ("3 lines", '"20% off" is said 1 time.')
    assert proposal.question is None


ITEMS = [
    ItemView("i1", 1, "Get 20% off today only.", "Get 30% off today only.", "replace", None, True, "ready"),
    ItemView("i2", 2, "Twenty percent, this week.", "Thirty percent, this week.", "replace", None, True, "planned"),
    ItemView("i3", 3, "Thanks.", "Thanks, and come again.", "over", None, True, "planned"),
]


def test_the_rule_planner_reads_the_clip_in_one_line():
    assert RulePlanner().read(LINES).opening == "3 lines, one person speaks."
    assert RulePlanner().read(LINES).roles == ()


def test_offline_a_revision_leaves_out_the_item_you_name():
    revision = RulePlanner().revise("not the second one", ITEMS, LINES, "30% off")
    assert [(c.item_id, c.enabled) for c in revision.changes] == [("i2", False)]
    assert revision.summary == "Changed 1 item in the plan."
    by_time = RulePlanner().revise("skip the one at 0:04", ITEMS, LINES, "30% off")
    assert [(c.item_id, c.enabled) for c in by_time.changes] == [("i3", False)]
    back = RulePlanner().revise("put the last one back", ITEMS, LINES, "30% off")
    assert [(c.item_id, c.enabled) for c in back.changes] == [("i3", True)]


def test_offline_a_quoted_change_rewords_the_items_that_say_it():
    revision = RulePlanner().revise('change "Thirty" to "Forty"', ITEMS, LINES, "30% off")
    assert [(c.item_id, c.new_text) for c in revision.changes] == [("i2", "Forty percent, this week.")]


def test_offline_prose_cannot_revise_the_plan():
    revision = RulePlanner().revise("make it warmer", ITEMS, LINES, "30% off")
    assert revision.changes == () and revision.new_goal is False and "offline" in revision.summary
