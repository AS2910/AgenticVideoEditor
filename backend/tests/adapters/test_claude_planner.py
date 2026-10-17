"""Claude planner tests. No network: the SDK client is faked.

Phase 20c: the planner's `plan` and `revise` are gone (Voltage plans by
conversation, through its tools); what is left is `look`, `read` and
`shorten`, tested here."""
from types import SimpleNamespace

from app.adapters.claude_planner import ClaudePlanner, _Shortening
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


def test_shorten_returns_a_different_shorter_line_or_nothing():
    reader, messages = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text='"Two kinds, both on sale."'), usage=None))
    assert reader.shorten("Yes, we have two varieties, all on sale today.", 0.7, LINES[2]) == "Two kinds, both on sale."
    assert messages.calls[0]["output_config"] == {"effort": "low"}
    same, _ = planner(SimpleNamespace(stop_reason="end_turn", parsed_output=_Shortening(new_text="same"), usage=None))
    assert same.shorten("same", 0.7, LINES[2]) is None


# ── UX-2: reading the clip ───────────────────────────────────────────────────

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


# ── UX-5: a clip with no speech ──────────────────────────────────────────────

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
