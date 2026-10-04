"""Claude planner tests. No network: the SDK client is faked."""
from types import SimpleNamespace

from app.adapters.claude_planner import (
    ClaudePlanner, _Edit, _PlanReading, _Shortening, render_plan_request, to_proposal,
)
from app.orchestrator.planner import Line

LINES = [
    Line(1, 5.2, 6.9, "Customer", "Hi, I want to buy groceries."),
    Line(2, 7.5, 9.0, "Customer", "Start a live Bajicam session."),
    Line(3, 9.4, 9.9, "Shopkeeper", "Sure, sir."),
]


class FakeMessages:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def planner(result):
    messages = FakeMessages(result)
    return ClaudePlanner("k", "wrkspc_x", client=SimpleNamespace(messages=messages)), messages


def test_the_request_numbers_every_line_with_its_speaker_and_time():
    text = render_plan_request("Say Bhaji Cam", LINES, ["an earlier goal"])
    assert "2. [7.5s] Customer: Start a live Bajicam session." in text
    assert "Earlier goals in this project:\n- an earlier goal" in text
    assert text.endswith("Goal: Say Bhaji Cam")


def test_a_plan_comes_back_as_edits_and_suggestions_on_known_lines():
    reading = _PlanReading(
        summary="I read all 3 lines. One change does it.", findings=[], question=None,
        edits=[_Edit(line=2, new_text=' "Start a live Bhaji Cam session." ', mix="replace", reason="Brand name")],
        suggestions=[_Edit(line=3, new_text="Sure, sir. Everything is 30% off.", mix="concatenate", reason="The offer"),
                     _Edit(line=9, new_text="nope", mix="replace", reason="no such line")],
    )
    usage = SimpleNamespace(input_tokens=900, output_tokens=120)
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=reading, usage=usage))
    metered = []

    proposal = reader.plan("Say Bhaji Cam", LINES, meter=lambda m, i, o: metered.append((m, i, o)))

    assert proposal.summary == "I read all 3 lines. One change does it."
    assert [(c.line, c.new_text, c.mix) for c in proposal.edits] == [(2, "Start a live Bhaji Cam session.", "replace")]
    assert [c.line for c in proposal.suggestions] == [3]   # the unknown line is dropped
    assert messages.calls[0]["output_config"] == {"effort": "medium"}
    assert metered == [("claude-opus-5", 900, 120)]


def test_a_refusal_plans_nothing():
    reader, _ = planner(SimpleNamespace(stop_reason="refusal", parsed_output=None, usage=None))
    assert reader.plan("x", LINES).edits == ()


def test_to_proposal_drops_empty_lines():
    reading = _PlanReading(summary="", findings=[], question=None, edits=[_Edit(line=1, new_text='""', mix="replace", reason="")], suggestions=[])
    assert to_proposal(reading, LINES).edits == ()
    assert to_proposal(reading, LINES).summary == "Here's my plan."


def test_shorten_returns_a_different_shorter_line_or_nothing():
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text='"Two kinds, both on sale."'), usage=None))
    assert reader.shorten("Yes, we have two varieties, all on sale today.", 0.7, LINES[2]) == "Two kinds, both on sale."
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    same, _ = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text="same"), usage=None))
    assert same.shorten("same", 0.7, LINES[2]) is None


def test_findings_and_one_question_come_back_with_the_guess_checked():
    from app.adapters.claude_planner import _Question
    reading = _PlanReading(
        summary="One change.", findings=[" The brand name is said once. ", "", "The offer is not mentioned."],
        question=_Question(text="Who speaks for the brand?", options=["The Shopkeeper", "The Customer"], guess="nobody"),
        edits=[_Edit(line=2, new_text="x", mix="replace", reason="")], suggestions=[],
    )
    proposal = to_proposal(reading, LINES)
    assert proposal.findings == ("The brand name is said once.", "The offer is not mentioned.")
    assert proposal.question.text == "Who speaks for the brand?"
    assert proposal.question.guess == "The Shopkeeper"   # an unknown guess falls back to the first option


def test_an_answer_is_put_to_the_planner_in_the_request():
    text = render_plan_request("goal", LINES, [], answer=("Who speaks for the brand?", "The Shopkeeper"))
    assert "You asked: Who speaks for the brand?" in text
    assert "The user answered: The Shopkeeper" in text


def test_a_script_label_in_front_of_the_words_is_dropped():
    from app.adapters.claude_planner import strip_label
    names = ["Customer", "Shopkeeper"]
    assert strip_label("Shopkeeper: Of course, sir.", names) == "Of course, sir."
    assert strip_label("the customer: Thanks!", names) == "Thanks!"
    assert strip_label("Speaker B: Done.", names) == "Done."
    assert strip_label("Note: delivery is free.", names) == "Note: delivery is free."   # not a name


def test_an_added_line_can_name_who_says_it():
    reading = _PlanReading(
        summary="", findings=[], question=None,
        edits=[_Edit(line=1, new_text="Shopkeeper: Delivery is free.", mix="concatenate", reason="", speaker="Shopkeeper"),
               _Edit(line=2, new_text="x", mix="replace", reason="", speaker="Nobody")],
        suggestions=[],
    )
    edits = to_proposal(reading, LINES).edits
    assert (edits[0].new_text, edits[0].speaker) == ("Delivery is free.", "Shopkeeper")
    assert edits[1].speaker is None    # an unknown name is ignored


def test_each_line_shows_its_syllables_and_its_budget():
    lines = [Line(1, 5.2, 6.9, "Customer", "Hi, I want to buy groceries.", syllables=8, budget=10)]
    text = render_plan_request("goal", lines, [])
    assert "1. [5.2s] Customer: Hi, I want to buy groceries.  (8 syl now, up to 10 fit)" in text


# ── UX-2: reading the clip, revising the plan in words ───────────────────────

def test_reading_the_clip_names_each_speakers_role_and_opens_specifically():
    from app.adapters.claude_planner import _Reading, _Role, render_read_request
    reading = _Reading(opening=" Two people, three lines. The brand name is said once, at 0:07. ", roles=[
        _Role(speaker="Customer", role="customer.", why="Asks to buy."),
        _Role(speaker="Shopkeeper", role="Shopkeeper", why="Answers."),
        _Role(speaker="Shopkeeper", role="Owner", why="twice: dropped"),
        _Role(speaker="Nobody", role="Ghost", why="unknown: dropped"),
    ])
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=reading, usage=None))
    got = reader.read(LINES)
    assert got.opening == "Two people, three lines. The brand name is said once, at 0:07."
    assert [(r.speaker, r.role) for r in got.roles] == [("Customer", "Customer"), ("Shopkeeper", "Shopkeeper")]
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    assert "2. [0:07] Customer: Start a live Bajicam session." in render_read_request(LINES)


def test_a_revision_touches_only_the_items_it_names_and_may_add_a_line():
    from app.adapters.claude_planner import _ItemChange, _Revision, render_revise_request
    from app.orchestrator.planner import ItemView
    items = [
        ItemView("i1", 2, "Start a live Bajicam session.", "Start a live Bhaji Cam session.", "replace", None, True, "ready", "Customer"),
        ItemView("i2", 3, "Sure, sir.", "Sure, sir. Thirty off.", "over", "warmer", False, "planned", "Shopkeeper"),
    ]
    text = render_revise_request("not the first one, and calmer", items, LINES, "Say Bhaji Cam")
    assert 'i1. line 2 [0:07] Customer: "Start a live Bajicam session." → "Start a live Bhaji Cam session." (replaces the line; voiced)' in text
    assert 'i2. line 3 [0:09] Shopkeeper: "Sure, sir." → "Sure, sir. Thirty off." (added after, over the picture; not voiced yet; delivery: warmer; left out)' in text
    assert text.endswith("The user says: not the first one, and calmer")

    revision = _Revision(summary="Left out the first and calmed the second.", changes=[
        _ItemChange(item_id="i1", enabled=False),
        _ItemChange(item_id="i2", delivery="calmer", new_text='"Shopkeeper: Sure. Thirty off."', mix="concatenate"),
        _ItemChange(item_id="i2", delivery="as spoken"),
        _ItemChange(item_id="i9", enabled=False),
    ], additions=[_Edit(line=1, new_text="Welcome in!", mix="over", reason="A greeting", speaker="Shopkeeper")])
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=revision, usage=None))
    got = reader.revise("not the first one, and calmer", items, LINES, "Say Bhaji Cam")
    assert messages.calls[0]["output_config"] == {"effort": "medium"}
    assert got.new_goal is False
    assert [(c.item_id, c.enabled, c.new_text, c.mix, c.delivery, c.clear_delivery) for c in got.changes] == [
        ("i1", False, None, None, None, False),
        ("i2", None, "Sure. Thirty off.", "concatenate", "calmer", False),
        ("i2", None, None, None, None, True),
    ]
    assert [(a.line, a.new_text, a.mix, a.speaker) for a in got.additions] == [(1, "Welcome in!", "over", "Shopkeeper")]


def test_a_revision_can_say_it_is_really_a_new_goal():
    from app.adapters.claude_planner import _Revision
    revision = _Revision(summary="That's a new goal.", new_goal=True, changes=[], additions=[])
    reader, _ = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=revision, usage=None))
    assert reader.revise("make it a Diwali ad", [], LINES, "Say Bhaji Cam").new_goal is True


# ── UX-5: a clip with no speech ──────────────────────────────────────────────

def test_the_request_for_a_silent_clip_describes_the_picture_and_the_brief():
    from app.orchestrator.planner import Sight
    sight = Sight(opening="No one speaks. A beach at dusk.", setting="A wide beach at dusk", mood="calm",
                  people="two, far off", text_on_screen="", place_guess="Goa, India", confidence="medium",
                  beats=({"at": 0.3, "note": "wide shot of the beach"}, {"at": 7.2, "note": "the light fading"}))
    text = render_plan_request("Introduce the place", [], [], sight=sight, duration=7.5,
                               answers=(("What is the audio for?", "A warm welcome"),))
    assert "The clip has no speech. It is 7.5 s long." in text
    assert "- Setting: A wide beach at dusk" in text
    assert "- Place: Goa, India (medium confidence)" in text
    assert "- 0.3s: wide shot of the beach" in text
    assert "syllables fit in the whole clip" in text
    assert "You asked: What is the audio for?\nThe user answered: A warm welcome" in text
    assert "You may ask 2 more questions" in text
    assert text.endswith("Goal: Introduce the place")


def test_a_placed_edit_keeps_its_span_and_plays_over_the_sound():
    reading = _PlanReading(
        summary="One line.", findings=[], question=None,
        edits=[_Edit(line=0, start=0.5, end=2.4, new_text=' "Welcome to Goa." ', mix="layer", reason="The opening shot")],
        suggestions=[_Edit(line=0, start=0.5, end=2.4, new_text="This is Goa.", mix="layer", reason="Shorter")],
    )
    proposal = to_proposal(reading, [])
    [edit] = proposal.edits
    assert edit.placed and (edit.start, edit.end) == (0.5, 2.4)
    assert edit.new_text == "Welcome to Goa." and edit.mix == "layer"
    assert [s.new_text for s in proposal.suggestions] == ["This is Goa."]


def test_looking_sends_the_frames_as_images_and_reads_back_a_sight(tmp_path):
    from app.adapters.claude_planner import _Beat, _Sight
    from app.orchestrator.planner import Frame
    jpg = tmp_path / "f.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0 not really a jpeg")
    seen = _Sight(opening="No one speaks. A beach.", setting="beach", mood="calm", people="no one",
                  text_on_screen="", place_guess="", confidence="low", beats=[_Beat(at=0.3, note="sand")])
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=seen, usage=None))
    sight = reader.look([Frame(0.3, str(jpg))], 7.5)
    content = messages.calls[0]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "Frame at 0.3 s:"}
    assert content[1]["type"] == "image" and content[1]["source"]["media_type"] == "image/jpeg"
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    assert sight.opening == "No one speaks. A beach." and sight.beats == ({"at": 0.3, "note": "sand"},)
