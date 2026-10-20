"""A2's checks on their own: facts found by pattern and compared between
videos, one role in two voices, a glossary term said otherwise, a banned word
said, a required line missing, loudness apart, the text pass's issues held to
their quotes, the estimate from the price table, and fingerprints that follow
the text."""
from app.agent import project_check as pc
from app.agent.project_check import Passage, VideoText
from app.usage import claude_usd

RULES = [
    {"kind": "pronounce", "data": {"term": "Bhaji Cam", "say": "BAH-jee cam", "respell": "Bah jee cam"}},
    {"kind": "banned", "data": {"word": "cheap"}},
    {"kind": "required_line", "data": {"text": "T&C apply"}},
]


def video(vid, *passages, loud=None):
    return VideoText(vid, f"{vid}.mp4", tuple(passages), loud)


def test_facts_are_found_by_pattern_and_normalised():
    assert pc.facts("Get 20% off, only Rs. 499 till 5th November.") == {"price": ["₹499"], "percent": ["20%"], "date": ["5 Nov"]}
    assert pc.facts("Call +91 98765 43210 or visit www.BhajiCam.com/offer.") == {"url": ["bhajicam.com/offer"], "phone": ["9876543210"]}
    assert pc.facts("Now 30 percent off at ₹1,299 from Nov 7") == {"price": ["₹1299"], "percent": ["30%"], "date": ["7 Nov"]}
    assert pc.facts("Visit bhajicam dot in today, 499 rupees on 12/11") == {"url": ["bhajicam.in"], "price": ["₹499"], "date": ["12 Nov"]}
    assert pc.facts("Version 2.5 is here") == {}


def test_a_seeded_project_returns_exactly_its_conflicts():
    a = video("p1", Passage("Get 20% off the Bhaji Cam. T&C apply.", 1.0),
              Passage("Get Bah jee cam today", 5.0, "edit", "Narrator", "v-asha", ("Get", "Bah", "jee", "cam", "today")), loud=-14.0)
    b = video("p2", Passage("Get 30% off. It's cheap.", 2.0),
              Passage("Try Bhaji Cam now", 6.0, "edit", "Narrator", "v-ravi", ("Try", "Badge", "Cam", "now")), loud=-18.5)
    c = video("p3", Passage("Get 20% off. T&C apply.", 0.5))
    result = pc.deterministic([a, b, c], RULES, {"v-asha": "Asha", "v-ravi": "Ravi"})
    kinds = [i["kind"] for i in result.issues]
    assert kinds == ["fact", "voice", "pronounce", "banned", "required_line", "loudness"]
    fact, voice, said, banned, required, loud = result.issues
    assert fact["message"] == "The videos give different percentages: 20% in p1.mp4 and p3.mp4; 30% in p2.mp4."
    assert [(p["video_id"], p["t"]) for p in fact["places"]] == [("p1", 1.0), ("p3", 0.5), ("p2", 2.0)]
    assert voice["message"] == "“Narrator” is voiced by 2 different voices: Asha in p1.mp4; Ravi in p2.mp4."
    assert [p["video_id"] for p in said["places"]] == ["p2"] and said["places"][0]["t"] == 6.0
    assert "“cheap” is a banned word" in banned["message"] and banned["places"][0]["video_id"] == "p2"
    assert required["message"] == "“T&C apply” is a required line, and p2.mp4 does not say it." and required["places"][0]["t"] is None
    assert loud["message"].startswith("p1.mp4 is 4.5 LU louder than p2.mp4")
    assert result.notes == ["Loudness not checked for p3.mp4: no render measured yet."]


def test_videos_that_agree_raise_nothing():
    a = video("p1", Passage("Get 20% off at bhajicam.com. T&C apply.", 1.0), loud=-14.0)
    b = video("p2", Passage("Only today: 20 percent off, bhajicam.com. T&C apply.", 2.0), loud=-15.5)
    assert pc.deterministic([a, b], RULES).issues == []
    # One video speaking a role in two voices is its own choice, not a project conflict.
    one = video("p1", Passage("Hi", 1.0, "edit", "Narrator", "v1"), Passage("Bye", 2.0, "edit", "Narrator", "v2"))
    assert [i["kind"] for i in pc.deterministic([one, video("p2")], []).issues] == []


def test_the_fingerprint_follows_the_text_it_was_found_in():
    a = video("p1", Passage("Get 20% off.", 1.0))
    b = video("p2", Passage("Get 30% off.", 2.0))
    first = pc.deterministic([a, b], []).issues[0]["fingerprint"]
    assert pc.deterministic([a, b], []).issues[0]["fingerprint"] == first           # the same text: the same issue
    b2 = video("p2", Passage("Get 25% off.", 2.0))
    assert pc.deterministic([a, b2], []).issues[0]["fingerprint"] != first          # the text changed: a new one


def test_the_text_pass_keeps_only_issues_its_quotes_back():
    a = video("p1", Passage("Join the Diwali Dhamaka sale.", 1.0))
    b = video("p2", Passage("The Diwali Bonanza sale is on.", 3.0))
    raw = [
        {"message": "One video calls it Diwali Dhamaka \u2014 the other Diwali Bonanza.",
         "places": [{"video_id": "p1", "quote": "Diwali Dhamaka sale"}, {"video_id": "p2", "quote": "diwali bonanza sale"}]},
        {"message": "Made up.", "places": [{"video_id": "p1", "quote": "not said anywhere"}, {"video_id": "p2", "quote": "Bonanza"}]},
        {"message": "Unknown video.", "places": [{"video_id": "p9", "quote": "Diwali"}, {"video_id": "p2", "quote": "Bonanza"}]},
    ]
    out = pc.from_model(raw, [a, b])
    assert len(out) == 1 and out[0]["kind"] == "offer"
    assert "—" not in out[0]["message"]
    assert [(p["video_id"], p["t"]) for p in out[0]["places"]] == [("p1", 1.0), ("p2", 3.0)]


def test_the_estimate_comes_from_the_transcripts_and_the_price_table():
    vids = [video("p1", Passage("x" * 4000, 0.0)), video("p2", Passage("y" * 4000, 0.0))]
    est = pc.estimate(vids, "claude-haiku-4-5")
    assert est["input_tokens"] == -(-(len(pc.SYSTEM) + len(pc.request_text(vids))) // 4)
    assert est["usd"] == round(claude_usd("claude-haiku-4-5", est["input_tokens"], pc.EXPECTED_OUTPUT_TOKENS), 6)
    assert est["label"] == "about $0.01"
    big = [video("p1", Passage("x" * 400_000, 0.0))]
    assert pc.estimate(big, "claude-haiku-4-5")["label"] == "about $0.11"   # 100k tokens in, 400 out, rounded up to the cent
