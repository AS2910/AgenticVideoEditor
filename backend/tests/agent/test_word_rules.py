"""A3: the take check against the project's words, and the respelling sent
to the voice vendor (the display text never changes)."""
from app.adapters import pronounce
from app.agent.word_rules import check_take, check_text, tokens

RULES = [
    {"kind": "pronounce", "data": {"term": "Bhaji Cam", "say": "BAH-jee cam", "respell": "Bah jee cam"}},
    {"kind": "banned", "data": {"word": "cheap"}},
    {"kind": "required_line", "data": {"text": "T&C apply"}},
]


def test_a_take_that_mispronounces_a_glossary_term_fails_the_check():
    got = check_take("Try Bhaji Cam today.", ["Try", "Badge", "Cam", "today."], RULES)
    assert not got.ok and len(got.breaks) == 1
    assert got.breaks[0].startswith("“Bhaji Cam” did not come out as written")
    assert got.sentence().startswith("Breaks a word rule: ")
    assert got.to_dict() == {"breaks": list(got.breaks), "warnings": []}


def test_a_take_that_says_the_term_as_written_respelled_or_as_one_word_passes():
    assert check_take("Try Bhaji Cam today.", ["Try", "Bhaji", "Cam", "today."], RULES).ok
    assert check_take("Try Bhaji Cam today.", ["Try", "BAH-jee", "cam", "today."], RULES).ok   # the respelling it was sent
    assert check_take("Try Bhaji Cam today.", ["Try", "Bhajicam", "today."], RULES).ok
    assert check_take("Try Bhaji Cam today.", [], RULES).to_dict() is None   # no words to compare: nothing to say
    assert check_take("Something else.", ["Something", "else"], RULES).to_dict() is None


def test_a_banned_word_voltage_wrote_breaks_one_the_user_typed_only_warns():
    voltage = check_take("Cheap deals today.", ["Cheap", "deals", "today"], RULES, typed="make it punchier")
    assert voltage.breaks == ("Says “cheap”, a banned word in this project.",)
    mine = check_take("Cheap deals today.", ["Cheap", "deals", "today"], RULES, typed="Replace the line with “Cheap deals today”")
    assert mine.ok and mine.warnings and "Kept, because you typed it" in mine.warnings[0]


def test_a_typed_line_with_a_banned_word_gets_a_warning_never_a_block():
    assert check_text("Cheap deals, today only", RULES) == ["“cheap” is a banned word in this project. You can still voice it."]
    assert check_text("Great deals", RULES) == []


def test_tokens_split_hyphens_and_ignore_case():
    assert tokens("BAH-jee Cam's") == ["bah", "jee", "cam", "s"]


def test_respellings_go_to_the_vendor_whole_words_only_longest_first():
    pairs = pronounce.pairs_from(RULES + [{"kind": "pronounce", "data": {"term": "Bhaji Cam Pro", "say": "x", "respell": "Bah jee cam pro"}},
                                          {"kind": "pronounce", "data": {"term": "Volt", "say": "volt"}}])
    assert pairs == (("Bhaji Cam Pro", "Bah jee cam pro"), ("Bhaji Cam", "Bah jee cam"))
    assert pronounce.for_synthesis("Get the bhaji cam pro, or a Bhaji Cam.", pairs) == "Get the Bah jee cam pro, or a Bah jee cam."
    assert pronounce.for_synthesis("Bhaji Cameras", pairs) == "Bhaji Cameras"
    assert pronounce.for_synthesis("Bhaji Cam") == "Bhaji Cam"              # nothing set: unchanged
    with pronounce.respelling(pairs):
        assert pronounce.for_synthesis("Bhaji Cam") == "Bah jee cam"
    assert pronounce.for_synthesis("Bhaji Cam") == "Bhaji Cam"


def test_the_elevenlabs_request_carries_the_respelling_and_the_plan_keeps_the_words():
    from app.adapters.elevenlabs import to_request
    from app.domain.models import EditPlan, Selection
    plan = EditPlan(Selection(0.0, 2.0), "Try Bhaji Cam today.", "v1")
    with pronounce.respelling(pronounce.pairs_from(RULES)):
        body = to_request(plan, None, "eleven_multilingual_v2")
    assert body["text"] == "Try Bah jee cam today." and plan.new_text == "Try Bhaji Cam today."
