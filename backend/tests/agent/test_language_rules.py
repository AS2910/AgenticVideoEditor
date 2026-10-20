"""B2: brand names never translate (a deterministic post-check on each take of
a language version) and the per-language glossary in the opening view."""
from app.agent.context import language_lines
from app.agent.word_rules import brand_terms, glossary_for, translated_brands
from app.store import languages
from app.store.rules import RuleError, clean

RULES = [{"kind": "pronounce", "data": {"term": "Bhajicam", "say": "bhaji cam", "brand": True}},
         {"kind": "pronounce", "data": {"term": "offer", "say": "offer", "lang": "hi", "translation": "ऑफ़र"}},
         {"kind": "pronounce", "data": {"term": "offer", "say": "offer", "lang": "ta", "translation": "சலுகை"}}]


def test_a_translated_brand_is_caught_and_a_kept_one_passes():
    assert brand_terms(RULES) == ["Bhajicam"]
    assert translated_brands("Bhajicam gives 20% off", "भाजीकैम पर 20% छूट", RULES) == ["Bhajicam"]
    assert translated_brands("Bhajicam gives 20% off", "BHAJICAM पर 20% छूट", RULES) == []
    assert translated_brands("Get 20% off", "20% छूट", RULES) == []           # not in the master's line: nothing owed


def test_the_glossary_is_per_language():
    assert glossary_for(RULES, "hi") == [("offer", "ऑफ़र")]
    lines = language_lines({"code": "ta", "label": "Tamil", "master_filename": "ad.mp4"}, RULES)
    assert lines[0].startswith("This video is the Tamil version of ad.mp4")
    assert "Never translate: Bhajicam." in lines[1] and "“offer” is “சலுகை”" in lines[2]
    assert language_lines(None, RULES) == []


def test_rule_fields_for_languages():
    assert clean("pronounce", {"term": "Bhajicam", "say": "x", "brand": "true"})["brand"] is True
    assert "brand" not in clean("pronounce", {"term": "Bhajicam", "say": "x", "brand": False})
    assert clean("pronounce", {"term": "a", "say": "a", "lang": "HI", "translation": "b"})["lang"] == "hi"
    for bad in ({"lang": "fr", "translation": "b"}, {"translation": "b"}):
        try:
            clean("pronounce", {"term": "a", "say": "a", **bad})
            raise AssertionError("should refuse")
        except RuleError:
            pass


def test_the_masters_language_is_read_from_its_script():
    assert languages.guess("Get 20% off") == "en"
    assert languages.guess("आज 20% छूट") == "hi"
    assert languages.guess("இன்று தள்ளுபடி") == "ta"
