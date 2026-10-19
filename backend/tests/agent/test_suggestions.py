"""Chips from this video (2026-10-20): grounded, short, varied; a generic set without Claude."""
from app.agent import suggestions as S


def chip(label, kind="add", ground="frames", prompt=None):
    return {"label": label, "prompt": prompt or label, "kind": kind, "grounded_in": ground}


def test_a_silent_beach_with_no_place_name_yields_no_named_place():
    sources = "a wide beach at sunset, two people far off"
    out = S.clean([chip("Introduce this beach at sunset"), chip("Welcome to Goa", kind="change")], sources)
    assert [c.label for c in out] == ["Introduce this beach at sunset"]


def test_a_brand_said_in_the_transcript_can_be_a_chip():
    sources = "Start a live Bhaji Cam session. Sure, sir."
    out = S.clean([chip("Say Bhaji Cam clearly", kind="fix", ground="words")], sources)
    assert [c.label for c in out] == ["Say Bhaji Cam clearly"]
    assert S.clean([chip("Say Masala Cam clearly", kind="fix", ground="words")], sources) == []


def test_the_briefs_offer_can_be_a_chip():
    out = S.clean([chip("Add the 30% Diwali offer", kind="change", ground="brief")], "Get 20% off today only. Brief: Diwali sale, 30% off")
    assert out and out[0].grounded_in == "brief"


def test_labels_are_short_and_kinds_do_not_repeat():
    long = "Make the narration warmer and slower over the whole of the ending stretch"
    out = S.clean([chip(long, kind="voice"), chip("Try a man's voice", kind="voice"), chip("Export", kind="finish"),
                   chip("x", kind="other"), chip("Add a line at 0:03", kind="add"), chip("Fix line 2", kind="fix")], "")
    assert all(len(c.label) <= S.MAX_LABEL for c in out)
    assert [c.kind for c in out] == ["voice", "finish", "add", "fix"]
    assert out[0].prompt == long   # the prompt keeps the whole ask


def test_offline_gives_the_generic_set_and_nothing_specific():
    for has_speech in (True, False):
        out = S.fallback(has_speech)
        assert 3 <= len(out) <= 4 and all(len(c.label) <= S.MAX_LABEL for c in out)
        assert all(not S.names_in(c.label) for c in out)


def test_the_next_block_is_taken_off_the_reply():
    reply = 'Four lines are ready, building to the knockdown at 0:13.\n<next>[{"label": "Make line 2 warmer", "prompt": "Voice line 2 again, warmer.", "kind": "voice", "grounded_in": "words"}]</next>'
    words, raw = S.split_reply(reply)
    assert words == "Four lines are ready, building to the knockdown at 0:13."
    assert S.clean(raw, "")[0].label == "Make line 2 warmer"
    assert S.split_reply("No block here.") == ("No block here.", [])
    assert S.split_reply("Broken <next>not json</next>") == ("Broken", [])
