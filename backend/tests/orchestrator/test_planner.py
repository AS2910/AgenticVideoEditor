from app.orchestrator.planner import Frame, Line, OfflinePlanner

LINES = [
    Line(1, 0.0, 2.3, "Presenter", "Get 20% off today only."),
    Line(2, 2.5, 4.0, "Presenter", "Twenty percent, this week."),
    Line(3, 4.2, 5.0, None, "Thanks."),
]


def test_the_offline_planner_says_who_it_is():
    assert OfflinePlanner().identity == "offline"


def test_the_offline_planner_offers_no_shorter_line():
    assert OfflinePlanner().shorten("a long line", 0.6, LINES[0]) is None


def test_the_offline_planner_reads_the_clip_in_one_line():
    assert OfflinePlanner().read(LINES).opening == "3 lines, one person speaks."
    assert OfflinePlanner().read(LINES).roles == ()


def test_the_offline_planner_counts_the_people_who_speak():
    two = LINES + [Line(4, 5.2, 6.0, "Customer", "Thank you.")]
    assert OfflinePlanner().read(two).opening == "4 lines, 2 people speak."
    assert OfflinePlanner().read([LINES[2]]).opening == "1 line."


# ── UX-5: a clip with no speech ──────────────────────────────────────────────

def test_the_offline_planner_looks_without_seeing():
    sight = OfflinePlanner().look([Frame(0.3, "a.jpg"), Frame(3.9, "b.jpg")], 7.5)
    assert sight.opening == "No one speaks. 7.5 s of picture, 2 frames."
