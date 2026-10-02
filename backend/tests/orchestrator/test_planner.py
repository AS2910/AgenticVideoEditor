from app.orchestrator.planner import Line, RulePlanner

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
